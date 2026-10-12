"""Analysis pipeline: capture data + calibration -> AnalysisResult (+ arrays).

Pure function of its inputs (no I/O). ``storage`` persists the result and
``app`` schedules it on a worker thread. ALGORITHM_VERSION is bumped whenever
a change could alter numerical output; stored results keep the version that
produced them (provenance).
"""

from __future__ import annotations

import itertools
import math
import uuid
from dataclasses import dataclass

import numpy as np

from .. import __version__
from ..domain import units
from ..domain.model import (
    ACOUSTIC_KINDS,
    AnalysisConfig,
    AnalysisResult,
    BandLevel,
    CalibrationProfile,
    CaptureManifest,
    ChannelAnalysis,
    CoherentPeak,
    CrossChannelResult,
    HarmonicFamily,
    LevelSummary,
    QualityCode,
    QualityFlag,
    SensorDescriptor,
    Severity,
    TaggedValue,
    TonalPeak,
    TransientSummary,
    utcnow,
)
from ..domain.units import Quantity
from ..dsp import cross, levels, spectral, tonal, transient
from ..sensors import calibration as cal
from ..sensors.capabilities import capabilities

ALGORITHM_VERSION = "1.0.0"
MAX_CROSS_PAIRS = 15
# Statistically significant coherence can still be tiny with many averages;
# below this value a shared component explains less than half the power.
COHERENCE_MIN_PRACTICAL = 0.5


@dataclass
class AnalysisOutput:
    result: AnalysisResult
    arrays: dict[str, np.ndarray]


def _tv(v, reason):
    if v is None or not math.isfinite(v):
        return TaggedValue(status="unavailable", reason=reason)
    return TaggedValue(status="valid", value=float(v))


def analyze(manifest: CaptureManifest, data: np.ndarray, sensors: dict[str, SensorDescriptor],
            calibrations: dict[str, CalibrationProfile], config: AnalysisConfig | None = None,
            cancel=None) -> AnalysisOutput:
    """``data``: float array of shape (frames, channels) in FS. ``cancel``: optional
    callable returning True to abort (checked between channels; raises CancelledError)."""
    from ..domain.errors import AnalysisError, CancelledError

    cfg = config or AnalysisConfig()
    fs = manifest.sample_rate_hz
    if data.ndim != 2 or data.shape[1] != len(manifest.channels):
        raise AnalysisError(f"data shape {data.shape} does not match {len(manifest.channels)} channels")
    gaps = [(g.start_frame, g.end_frame) for g in manifest.gaps]
    fmax = min(cfg.fmax_hz or fs / 2, fs / 2)
    arrays: dict[str, np.ndarray] = {}
    chans: list[ChannelAnalysis] = []
    valids: dict[int, np.ndarray] = {}
    scaled: dict[int, np.ndarray] = {}
    calibrated: set[int] = set()
    top_flags: list[QualityFlag] = []
    if manifest.source == "simulated":
        top_flags.append(QualityFlag(code=QualityCode.SIMULATED_DATA, severity=Severity.WARNING,
                                     message="SIMULATED data: not a physical measurement"))
    for col, ch in enumerate(manifest.channels):
        if cancel and cancel():
            raise CancelledError("analysis cancelled")
        # float32 end to end (the converter's native precision); kernels promote
        # bounded blocks to float64 internally, so full-length float64 copies are avoided.
        x = np.ascontiguousarray(data[:, col], dtype=np.float32)
        scr = levels.screen_channel(x, fs, ch.index, gaps)
        flags = list(scr.flags)
        sensor = sensors.get(ch.sensor_id) if ch.sensor_id else None
        quantity = sensor.quantity if sensor else Quantity.RELATIVE
        prof = calibrations.get(ch.calibration_id) if ch.calibration_id else None
        st = cal.evaluate(prof, ch, sensor)
        flags += st.flags
        scale = 1.0
        if st.usable and prof is not None:
            scale = 1.0 / prof.sensitivity_fs_per_unit
            quantity = prof.quantity
            calibrated.add(ch.index)
        else:
            quantity = Quantity.RELATIVE
        if ch.agc == "on":
            flags.append(QualityFlag(code=QualityCode.AGC_ACTIVE, severity=Severity.INVALID, channel=ch.index,
                                     message="automatic gain control is ON: levels and level comparisons are invalid"))
        elif ch.agc == "unknown" and (sensor is None or sensor.kind in ACOUSTIC_KINDS):
            flags.append(QualityFlag(code=QualityCode.AGC_UNKNOWN, severity=Severity.WARNING, channel=ch.index,
                                     message="AGC state unknown: confirm it is off before trusting level comparisons"))
        xs = np.nan_to_num(x, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if scale != 1.0:
            xs *= np.float32(scale)
        del x
        valids[ch.index] = scr.valid
        scaled[ch.index] = xs  # kept for cross-channel analysis
        rms, peak, dc = levels.level_stats(xs, scr.valid)
        unit = units.UNIT[quantity]
        lv = LevelSummary(rms=rms, peak=peak, crest_db=_tv(20 * math.log10(peak / rms) if rms > 0 and peak > 0 else None, "no AC signal"),
                          level_db=units.amplitude_db(rms, quantity), level_ref=units.DB_LABEL[quantity], unit=unit,
                          calibrated=ch.index in calibrated, dc_offset_fs=dc / scale if scale else dc)
        plan = spectral.plan_segments(scr.valid, fs, cfg.resolution_hz, cfg.overlap, cfg.min_averages, cfg.min_nperseg)
        peaks: list[TonalPeak] = []
        fams: list[HarmonicFamily] = []
        bands: list[BandLevel] = []
        floor_db = units.DB_FLOOR
        n_avg = nper = 0
        res = enbw = 0.0
        if plan is None:
            flags.append(QualityFlag(code=QualityCode.SHORT_CAPTURE, severity=Severity.INVALID, channel=ch.index,
                                     message=f"not enough contiguous valid data for spectral analysis (need {cfg.min_nperseg} samples)"))
        else:
            if not plan.sufficient:
                flags.append(QualityFlag(code=QualityCode.INSUFFICIENT_AVERAGES, severity=Severity.WARNING, channel=ch.index,
                                         message=f"only {plan.n_eff} independent averages (target {cfg.min_averages}); "
                                                 "spectra are noisy and coherence is not eligible"))
            f, p = spectral.masked_welch(xs, fs, plan, cfg.window)
            in_cal = np.ones_like(f, bool)
            if ch.index in calibrated and prof is not None:
                corr = cal.fr_correction_db(prof, f)
                in_cal = np.isfinite(corr)
                p = p * np.where(in_cal, 10 ** (np.nan_to_num(corr) / 10), 1.0)
                lo, hi = prof.valid_band_hz
                if cfg.fmin_hz < lo or fmax > hi:
                    flags.append(QualityFlag(code=QualityCode.CAL_OUT_OF_BAND, severity=Severity.WARNING, channel=ch.index,
                                             message=f"analysis band extends outside calibration validity {lo:g}-{hi:g} Hz; "
                                                     "values there are uncorrected"))
            wm = spectral.window_metrics(cfg.window, plan.nperseg)
            enbw = wm.enbw_hz(fs)
            res = float(f[1] - f[0])
            n_avg, nper = plan.n_eff, plan.nperseg
            sel = (f >= cfg.fmin_hz) & (f <= fmax)
            floor = tonal.noise_floor_db(p)
            floor_db = float(np.median(floor[sel]) + 10 * math.log10(max(res, 1e-12))) if sel.any() else units.DB_FLOOR
            ref2 = units.DB_REFERENCE[quantity] ** 2
            for t in tonal.detect_tones(f, p, cfg.window, enbw, cfg.tone_prominence_db, max(cfg.fmin_hz, 2 * res), fmax, cfg.max_peaks):
                k = t["bin"]
                peaks.append(TonalPeak(freq_hz=t["freq_hz"], level_db=units.power_db(t["power"], quantity),
                                       prominence_db=t["prominence_db"], rms=t["rms"],
                                       q=_tv(t["q"], "resolution-limited (narrower than analysis bandwidth)"),
                                       cal_in_band=bool(in_cal[k])))
                if t["freq_hz"] > 0.45 * fs:
                    flags.append(QualityFlag(code=QualityCode.ALIAS_RISK, severity=Severity.WARNING, channel=ch.index,
                                             message=f"tone at {t['freq_hz']:.0f} Hz is near Nyquist; run the alias check procedure"))
            for fam in tonal.harmonic_families([{"freq_hz": pk.freq_hz} for pk in peaks], res):
                fams.append(HarmonicFamily(f0_hz=fam["f0_hz"], orders=fam["orders"], mains=fam["mains"]))
            for lo_, fm, hi_, pw, ok in spectral.band_levels(f, p, cfg.band_type, max(cfg.fmin_hz, res), fmax):
                ok = ok and bool(in_cal[(f >= lo_) & (f < hi_)].all())
                bands.append(BandLevel(center_hz=fm, low_hz=lo_, high_hz=hi_, level_db=units.power_db(pw, quantity), power=pw, valid=ok))
            if cfg.store_arrays:
                arrays[f"psd_{ch.index}"] = p.astype(np.float64)
                arrays[f"f_{ch.index}"] = f.astype(np.float64)
                sf, st_, sx = spectral.spectrogram(xs, fs, cfg.spectrogram_nperseg, cfg.window, fmax=min(fmax, 20000))
                arrays[f"spec_f_{ch.index}"] = sf.astype(np.float32)
                arrays[f"spec_t_{ch.index}"] = st_.astype(np.float32)
                arrays[f"spec_{ch.index}"] = (10 * np.log10(np.maximum(sx, 1e-30) / ref2)).astype(np.float32)
                ef, ep = transient.envelope_spectrum(xs, fs, fmax=200.0)
                arrays[f"env_f_{ch.index}"] = ef
                arrays[f"env_{ch.index}"] = ep
        ev = transient.detect_events(xs, scr.valid, fs, cfg.event_frame_s, cfg.event_threshold_db)
        dur_min = max(manifest.frames / fs / 60.0, 1e-9)
        tr = TransientSummary(event_count=len(ev["times"]), events_per_min=len(ev["times"]) / dur_min,
                              median_interval_s=_tv(ev["median_interval_s"], "fewer than two events"),
                              periodic=ev["periodic"], max_excess_db=ev["max_excess_db"], event_times_s=ev["times"][:2000])
        if cfg.store_arrays:
            arrays[f"wave_{ch.index}"] = _overview(xs)
        chans.append(ChannelAnalysis(channel=ch.index, label=ch.label, quantity=quantity, unit=units.UNIT[quantity],
                                     calibrated=ch.index in calibrated, levels=lv, noise_floor_db=floor_db, peaks=peaks,
                                     families=fams, transients=tr, bands=bands, n_averages=n_avg, nperseg=nper,
                                     resolution_hz=res, enbw_hz=enbw, excluded_frames=int((~scr.valid).sum()), quality=flags))
    caps = capabilities(list(manifest.channels), sensors, calibrated, shared_clock=True)
    crosses = _cross(manifest, chans, scaled, valids, cfg, fs, fmax, arrays, cancel)
    result = AnalysisResult(id=f"an-{uuid.uuid4().hex[:12]}", capture_id=manifest.id, created_utc=utcnow(), config=cfg,
                            algorithm_version=ALGORITHM_VERSION, tier=caps.tier, channels=chans, cross=crosses,
                            quality=top_flags + list(manifest.quality), software_version=__version__)
    return AnalysisOutput(result, arrays)


def _overview(x: np.ndarray, points: int = 4000) -> np.ndarray:
    """Min/max envelope for waveform display: shape (2, m)."""
    if len(x) <= points:
        return np.vstack([x, x]).astype(np.float32)
    g = len(x) // points
    r = x[: g * points].reshape(points, g)
    return np.vstack([r.min(axis=1), r.max(axis=1)]).astype(np.float32)


def _cross(manifest, chans, scaled, valids, cfg, fs, fmax, arrays, cancel):
    from ..domain.errors import CancelledError

    out = []
    idx = [c.channel for c in chans]
    pairs = list(itertools.combinations(idx, 2))[:MAX_CROSS_PAIRS]
    by = {c.channel: c for c in chans}
    for a, b in pairs:
        if cancel and cancel():
            raise CancelledError("analysis cancelled")
        ca, cb = by[a], by[b]
        bad = [q for q in ca.quality + cb.quality if q.severity is Severity.INVALID and q.code in
               (QualityCode.SILENCE, QualityCode.SHORT_CAPTURE)]
        mask = valids[a] & valids[b]
        plan = spectral.plan_segments(mask, fs, max(cfg.resolution_hz, 2.0), cfg.overlap, cfg.min_averages, cfg.min_nperseg)
        if bad or plan is None:
            out.append(CrossChannelResult(ch_a=a, ch_b=b, sync_basis="shared_clock", eligible=False,
                                          reason="channel invalid (silent/short)" if bad else "insufficient common valid data",
                                          max_valid_freq_hz=0.0, n_averages=0, coherence_threshold=1.0,
                                          delay_s=TaggedValue(status="unavailable", reason="not computed"),
                                          delay_ambiguity_ratio=1.0))
            continue
        f, pxx, pyy, pxy = spectral.masked_csd(scaled[a], scaled[b], fs, plan, cfg.window)
        coh, h1, ok = cross.coherence_and_transfer(pxx, pyy, pxy)
        thr = cross.coherence_threshold(plan.n_eff, cfg.coherence_alpha)
        eligible = plan.n_eff >= cfg.min_averages
        reason = "shared converter clock; averaging sufficient" if eligible else \
            f"only {plan.n_eff} independent averages (< {cfg.min_averages}): coherence not interpretable"
        # Contiguous common data for the delay estimate (longest valid run).
        runs = spectral.valid_runs(mask)
        delay, amb = (None, 1.0)
        if runs:
            r0, r1 = max(runs, key=lambda r: r[1] - r[0])
            seg = slice(r0, min(r1, r0 + int(30 * fs)))
            delay, amb = cross.estimate_delay(scaled[a][seg], scaled[b][seg], fs, max_lag_s=0.1)
        cpk = []
        if eligible:
            freqs = sorted({round(pk.freq_hz, 1) for pk in ca.peaks + cb.peaks})
            for fq in freqs:
                k = int(np.argmin(np.abs(f - fq)))
                if ok[k] and coh[k] > max(thr, COHERENCE_MIN_PRACTICAL):
                    cpk.append(CoherentPeak(freq_hz=float(f[k]), coherence=float(coh[k]),
                                            transfer_db=float(20 * np.log10(max(abs(h1[k]), 1e-30))), phase_rad=float(np.angle(h1[k]))))
        if cfg.store_arrays:
            arrays[f"coh_{a}_{b}"] = np.nan_to_num(coh, nan=-1.0)
            arrays[f"cohf_{a}_{b}"] = f
            arrays[f"h1db_{a}_{b}"] = np.nan_to_num(20 * np.log10(np.maximum(np.abs(np.nan_to_num(h1)), 1e-30)), nan=-300)
        dtv = TaggedValue(status="valid", value=delay) if (delay is not None and amb <= 0.8) else \
            TaggedValue(status="invalid" if delay is not None else "unavailable",
                        value=delay if delay is not None else None,
                        reason="ambiguous correlation peak (periodic signal)" if delay is not None else "no common signal")
        out.append(CrossChannelResult(ch_a=a, ch_b=b, sync_basis="shared_clock", eligible=eligible, reason=reason,
                                      max_valid_freq_hz=fmax if eligible else 0.0, n_averages=plan.n_eff,
                                      coherence_threshold=thr, delay_s=dtv, delay_ambiguity_ratio=amb, coherent_peaks=cpk[:20]))
    return out


def tone_level_at(arrays: dict[str, np.ndarray], channel: int, freq_hz: float, window: str = "hann") -> float | None:
    """Integrated power (unit^2) around ``freq_hz`` from stored PSD arrays."""
    fk, pk = f"f_{channel}", f"psd_{channel}"
    if fk not in arrays or pk not in arrays:
        return None
    f, p = arrays[fk], arrays[pk]
    if len(f) < 2:
        return None
    df = f[1] - f[0]
    k = int(round(freq_hz / df))
    h = spectral.MAIN_LOBE_HALF_BINS.get(window, 3)
    if k < 0 or k >= len(p):
        return None
    return float(np.sum(p[max(0, k - h) : k + h + 1]) * df)


def band_power(arrays: dict[str, np.ndarray], channel: int, lo: float, hi: float) -> float | None:
    fk, pk = f"f_{channel}", f"psd_{channel}"
    if fk not in arrays:
        return None
    return spectral.integrate_band(arrays[fk], arrays[pk], lo, hi)
