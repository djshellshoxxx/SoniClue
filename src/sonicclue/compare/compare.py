"""Before/after comparison of capture groups (docs/specs/08 section 9).

Delta convention: delta = B - A in dB (negative means quieter in B).
Overall level: band power over [lo, hi] (the problem band if set, otherwise
the analysed band), from the stored PSD.
Bands: fractional-octave levels valid in every capture.
Tones: union of tones detected in either group, clustered within
max(2*df, 0.5%). Each is compared by integrated main-lobe power in every
capture, with uncertainty from tone SNR and averaging:
sd_dB ~ 4.343 * 2 * sqrt(Pn/Pt) / sqrt(n_eff), floored at 0.1 dB.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import numpy as np

from ..analysis.pipeline import ALGORITHM_VERSION, band_power, tone_level_at
from ..domain import units
from ..domain.errors import AnalysisError
from ..domain.model import (
    AnalysisResult,
    BandDelta,
    CaptureManifest,
    ComparisonResult,
    ToneDelta,
    utcnow,
)
from ..dsp import stats
from . import comparability


@dataclass
class Item:
    manifest: CaptureManifest
    analysis: AnalysisResult
    arrays: dict


def _chan(item: Item, label: str):
    ch = next((c for c in item.analysis.channels if c.label == label), None)
    if ch is None:
        raise AnalysisError(f"channel '{label}' not in analysis of {item.manifest.id}")
    return ch


def compare(case_id: str, group_a: list[Item], group_b: list[Item], channel_label: str, *, label_a: str = "A",
            label_b: str = "B", kind: str = "generic", run_id: str | None = None,
            band: tuple[float, float] | None = None) -> ComparisonResult:
    if not group_a or not group_b:
        raise AnalysisError("both groups need at least one capture")
    ref = group_a[0]
    issues = []
    for it in group_a[1:] + group_b:
        issues += comparability.check(ref.manifest, it.manifest, channel_label, ref.analysis, it.analysis)
    issues = comparability.merge(issues)
    comparable = not any(i.effect == "invalidates" for i in issues)
    chans = [(_chan(it, channel_label), it) for it in group_a + group_b]
    fs_min = min(it.manifest.sample_rate_hz for it in group_a + group_b)
    lo = max(band[0] if band else ref.analysis.config.fmin_hz, max(c.resolution_hz for c, _ in chans) * 2)
    hi = min(band[1] if band else (ref.analysis.config.fmax_hz or fs_min / 2), fs_min / 2)

    def overall(it):
        ch = _chan(it, channel_label)
        p = band_power(it.arrays, ch.channel, lo, hi)
        sd = stats.welch_level_sd_db(ch.n_averages, (hi - lo) / max(ch.enbw_hz, 1e-9))
        if p is None:
            raise AnalysisError(f"capture {it.manifest.id} has no stored spectra; re-run its analysis with arrays enabled")
        return units.power_db(p, ch.quantity), sd

    oa = [overall(it) for it in group_a]
    ob = [overall(it) for it in group_b]
    d, u, sig, rep = stats.compare_levels([x for x, _ in oa], [x for x, _ in ob],
                                          float(np.mean([s for _, s in oa])), float(np.mean([s for _, s in ob])))
    # bands valid in all captures
    band_sets = []
    for ch, it in chans:
        band_sets.append({round(b.center_hz, 3): b for b in ch.bands if b.valid and b.high_hz <= hi and b.low_hz >= lo})
    common = set(band_sets[0]).intersection(*band_sets[1:]) if band_sets else set()
    na = len(group_a)
    bds = []
    for cfreq in sorted(common):
        la = [band_sets[i][cfreq].level_db for i in range(na)]
        lb = [band_sets[i][cfreq].level_db for i in range(na, len(band_sets))]
        b0 = band_sets[0][cfreq]
        sd = stats.welch_level_sd_db(chans[0][0].n_averages, (b0.high_hz - b0.low_hz) / max(chans[0][0].enbw_hz, 1e-9))
        bd, bu, bsig, _ = stats.compare_levels(la, lb, sd, sd)
        bds.append(BandDelta(center_hz=cfreq, delta_db=round(bd, 3), uncertainty_db=round(bu, 3), significant=bsig))
    # tones
    res = max(c.resolution_hz for c, _ in chans)
    found: list[tuple[float, str]] = []
    for ch, it in chans:
        grp = "A" if it in group_a else "B"
        for pk in ch.peaks:
            if lo <= pk.freq_hz <= hi:
                found.append((pk.freq_hz, grp))
    clusters: list[list[tuple[float, str]]] = []
    for f, g in sorted(found):
        if clusters and abs(f - clusters[-1][0][0]) <= max(2 * res, 0.005 * f):
            clusters[-1].append((f, g))
        else:
            clusters.append([(f, g)])
    tds = []
    for cl in clusters[:40]:
        f = float(np.mean([x for x, _ in cl]))
        groups = {g for _, g in cl}

        def lvl(it):
            ch = _chan(it, channel_label)
            p = tone_level_at(it.arrays, ch.channel, f, it.analysis.config.window)
            if p is None or p <= 0:
                return None, 1.0
            floor_p = units.db_to_power(ch.noise_floor_db, ch.quantity) if ch.noise_floor_db > units.DB_FLOOR else 0.0
            ratio = min(1.0, floor_p / p) if p > 0 else 1.0
            sd = max(0.1, 4.343 * 2 * math.sqrt(ratio) / math.sqrt(max(ch.n_averages, 1)))
            return units.power_db(p, ch.quantity), sd

        la_ = [lvl(it) for it in group_a]
        lb_ = [lvl(it) for it in group_b]
        if any(x is None for x, _ in la_ + lb_):
            continue
        la, lb = [x for x, _ in la_], [x for x, _ in lb_]
        td, tu, tsig, _ = stats.compare_levels(la, lb, float(np.mean([s for _, s in la_])), float(np.mean([s for _, s in lb_])))
        if groups == {"A"}:
            # detected only before: "disappeared" if it dropped into the noise by >= 6 dB
            status = ("disappeared" if td <= -6 else "reduced") if (tsig and td < 0) else "unchanged"
        elif groups == {"B"}:
            status = "appeared" if tsig and td > 0 else "unchanged"
        else:
            status = "unchanged" if not tsig else ("reduced" if td < 0 else "increased")
        tds.append(ToneDelta(freq_hz=round(f, 2), level_a_db=round(stats.power_mean_db(la), 2),
                             level_b_db=round(stats.power_mean_db(lb), 2), delta_db=round(td, 2), status=status))
    sa, sb = ref.manifest.context.equipment_state, group_b[0].manifest.context.equipment_state
    changed = {k: [sa.get(k, "?"), sb.get(k, "?")] for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)}
    return ComparisonResult(
        id=f"cmp-{uuid.uuid4().hex[:12]}", case_id=case_id, kind=kind, procedure_run_id=run_id,
        label_a=label_a, label_b=label_b, captures_a=[it.manifest.id for it in group_a],
        captures_b=[it.manifest.id for it in group_b], channel_label=channel_label, comparable=comparable, issues=issues,
        overall_delta_db=round(d, 3), overall_uncertainty_db=round(u, 3), overall_significant=sig, repeatability=rep,
        band_deltas=bds, tone_deltas=tds, changed_equipment=changed, intervention=group_b[0].manifest.context.intervention,
        algorithm_version=ALGORITHM_VERSION, created_utc=utcnow())
