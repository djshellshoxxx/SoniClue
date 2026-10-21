"""Explainable diagnostic reasoning (docs/specs/09-diagnostic-reasoning.md).

Pipeline: evidence extraction -> rule evaluation -> conclusion/abstention -> next tests.

Design rules:
* Deterministic, versioned rules (RULESET_VERSION; each rule "R-xxx@rev").
  Same inputs give the same snapshot, which makes results testable and auditable.
* Support is ordinal (strongly_supported ... contradicted). No percentages:
  SonicClue has no validated probabilistic model (DEC-011), and a number
  would imply a calibrated probability that does not exist.
* Evidence carries its statement class (measured / calculated / inferred /
  user_asserted). Hypothesis text comes from fixed templates keyed to rule
  outcomes. There is no free-form "likely cause" text.
* Coherence, frequency coincidence and spectral peaks are "consistent with"
  evidence only. They never raise a source or path hypothesis to
  "supported" without an intervention (on/off, isolation, airborne control,
  damping) that could have contradicted it (ADV-002, ADV-003, ADV-009).
* Non-comparable comparisons produce NOT_COMPARABLE evidence and no
  effect evidence (ADV-004, ADV-005, ADV-008). Interventions that change the
  source and the path together give CONFOUNDED_INTERVENTION (ADV-007).
* A residual after switching a source off creates an additional-source
  hypothesis; the total is never attributed to one source (ADV-001).
  Contribution shares are never computed from totals alone (ADV-010).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from ..domain.model import (
    ACOUSTIC_KINDS,
    SUPPORT_ORDER,
    VIBRATION_KINDS,
    AnalysisResult,
    CaptureManifest,
    Case,
    ComparisonResult,
    DiagnosisSnapshot,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    HypothesisCategory,
    ProcedureRun,
    Severity,
    StatementClass,
    SupportLevel,
    utcnow,
)

RULESET_VERSION = "1.0.0"
TONE_PROMINENCE_DB = 15.0
STATE_MAX_UNCERTAINTY_DB = 3.0  # a "no effect" result only counts if the comparison could have resolved 3 dB
AIRBORNE_STRUCTURAL_DB = 6.0
AIRBORNE_SIMILAR_DB = 3.0
POSITION_GRADIENT_DB = 6.0
PRIMARY = {HypothesisCategory.SOURCE, HypothesisCategory.ADDITIONAL_SOURCE, HypothesisCategory.ELECTRICAL_HUM,
           HypothesisCategory.RECORDING_CHAIN, HypothesisCategory.RATTLE, HypothesisCategory.MEASUREMENT_ARTIFACT}


@dataclass
class CaptureView:
    manifest: CaptureManifest
    analysis: AnalysisResult | None


@dataclass
class DiagnosticInputs:
    case: Case
    captures: list[CaptureView]
    comparisons: list[ComparisonResult] = field(default_factory=list)
    runs: list[ProcedureRun] = field(default_factory=list)


def _eid(kind: str, *parts) -> str:
    h = hashlib.sha1("|".join([kind, *map(str, parts)]).encode(), usedforsecurity=False).hexdigest()[:10]
    return f"ev-{kind[:6]}-{h}"


def _same_f(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, 0.01 * max(a, b))


class _Ctx:
    def __init__(self, inp: DiagnosticInputs):
        self.inp = inp
        self.sensors = {s.id: s for s in inp.case.sensors}
        self.caps = {c.manifest.id: c for c in inp.captures}
        self.runs = {r.id: r for r in inp.runs}
        self.ev: list[EvidenceItem] = []
        self.stable_runs: set[str] = set()  # runs whose ABA stability comparison passed

    def kind_of(self, manifest: CaptureManifest, label: str):
        ch = next((c for c in manifest.channels if c.label == label), None)
        if ch and ch.sensor_id in self.sensors:
            return self.sensors[ch.sensor_id].kind
        return None

    def is_acoustic(self, m, label):
        k = self.kind_of(m, label)
        return k is None or k in ACOUSTIC_KINDS

    def is_vibration(self, m, label):
        return self.kind_of(m, label) in VIBRATION_KINDS

    def add(self, **kw) -> EvidenceItem:
        e = EvidenceItem(**kw)
        if all(x.id != e.id for x in self.ev):
            self.ev.append(e)
        return e


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def _extract_measurements(cx: _Ctx) -> list[tuple[float, str]]:
    """Tones, families, transients, resonance indicators, quality. Returns the problem tones (f, channel label)."""
    clusters: dict[tuple[str, int], list] = defaultdict(list)
    for cv in cx.inp.captures:
        an = cv.analysis
        if an is None:
            continue
        for ch in an.channels:
            invalid = [q for q in ch.quality if q.severity is Severity.INVALID]
            for q in invalid:
                if q.code.value in ("clipping", "agc_active", "silence", "cal_gain_mismatch"):
                    cx.add(id=_eid("mq", cv.manifest.id, ch.label, q.code.value), kind=EvidenceKind.MEASUREMENT_QUALITY,
                           statement_class=StatementClass.MEASURED,
                           summary=f"Capture '{cv.manifest.context.condition_label or cv.manifest.id}', {ch.label}: {q.message}",
                           params={"code": q.code.value}, sources=[cv.manifest.id, an.id], channel_label=ch.label, valid=True)
            if any(q.code.value in ("clipping", "silence") for q in invalid):
                continue
            for pk in ch.peaks:
                if pk.prominence_db >= TONE_PROMINENCE_DB:
                    key = None
                    for (lab, fk), _ in clusters.items():
                        if lab == ch.label and _same_f(fk / 10, pk.freq_hz):
                            key = (lab, fk)
                            break
                    clusters[key or (ch.label, int(round(pk.freq_hz * 10)))].append((pk, cv, an))
                if pk.q.status == "valid" and (pk.q.value or 0) >= 5 and pk.prominence_db >= 10:
                    cx.add(id=_eid("res", ch.label, round(pk.freq_hz)), kind=EvidenceKind.RESONANCE,
                           statement_class=StatementClass.CALCULATED,
                           summary=f"Resonance-like peak at {pk.freq_hz:.1f} Hz (Q about {pk.q.value:.0f}) on {ch.label}; "
                                   "a measurable bandwidth suggests a damped resonance, but a peak alone does not identify the object",
                           params={"q": round(pk.q.value, 1), "tap": False}, sources=[cv.manifest.id], channel_label=ch.label,
                           freq_hz=pk.freq_hz)
            for fam in ch.families:
                kind = EvidenceKind.MAINS_HARMONICS if fam.mains != "none" else EvidenceKind.HARMONIC_FAMILY
                txt = (f"Harmonic family on {ch.label}: fundamental {fam.f0_hz:.1f} Hz, orders {fam.orders}"
                       + (f"; related to {fam.mains} Hz mains (could be electrical, or mechanical hum from mains-powered equipment)"
                          if fam.mains != "none" else ""))
                cx.add(id=_eid("fam", ch.label, round(fam.f0_hz, 1), fam.mains), kind=kind, statement_class=StatementClass.CALCULATED,
                       summary=txt, params={"orders": len(fam.orders), "mains": fam.mains}, sources=[cv.manifest.id],
                       channel_label=ch.label, freq_hz=fam.f0_hz)
            tr = ch.transients
            if tr.event_count >= 3 and (tr.periodic or tr.events_per_min >= 6) and tr.max_excess_db >= 10:
                cx.add(id=_eid("tr", cv.manifest.id, ch.label), kind=EvidenceKind.TRANSIENTS, statement_class=StatementClass.MEASURED,
                       summary=f"{tr.event_count} impulsive events on {ch.label} ({tr.events_per_min:.0f}/min, "
                               f"{'periodic' if tr.periodic else 'irregular'}, up to {tr.max_excess_db:.0f} dB above background)",
                       params={"periodic": tr.periodic, "rate": round(tr.events_per_min, 1), "subject": "",
                               "procedure": cv.manifest.context.procedure_run_id or ""},
                       sources=[cv.manifest.id], channel_label=ch.label)
        for cr in an.cross:
            la = next(c.label for c in an.channels if c.channel == cr.ch_a)
            lb = next(c.label for c in an.channels if c.channel == cr.ch_b)
            mixed = (cx.is_acoustic(cv.manifest, la) and cx.is_vibration(cv.manifest, lb)) or \
                    (cx.is_vibration(cv.manifest, la) and cx.is_acoustic(cv.manifest, lb))
            if not (cr.eligible and mixed):
                continue
            for cp in cr.coherent_peaks:
                cx.add(id=_eid("coh", la, lb, round(cp.freq_hz)), kind=EvidenceKind.STRUCTURAL_COHERENCE,
                       statement_class=StatementClass.CALCULATED,
                       summary=f"{la} and {lb} are coherent at {cp.freq_hz:.1f} Hz (gamma^2 {cp.coherence:.2f} > threshold "
                               f"{cr.coherence_threshold:.2f}, {cr.n_averages} averages): consistent with a shared excitation. "
                               "Coherence does not show which way energy travels, and the contact sensor may be picking up airborne sound",
                       params={"coherence": round(cp.coherence, 3), "threshold": round(cr.coherence_threshold, 3)},
                       sources=[cv.manifest.id], freq_hz=cp.freq_hz)
    tones = []
    for (lab, _), items in clusters.items():
        best = max(items, key=lambda t: t[0].prominence_db)
        pk, cv, an = best
        f = float(sum(i[0].freq_hz for i in items) / len(items))
        cx.add(id=_eid("tone", lab, round(f, 1)), kind=EvidenceKind.TONE, statement_class=StatementClass.MEASURED,
               summary=f"Tone at {f:.1f} Hz on {lab}, up to {pk.prominence_db:.0f} dB above the local noise floor "
                       f"(seen in {len({i[1].manifest.id for i in items})} capture(s))",
               params={"prominence_db": round(pk.prominence_db, 1), "level_db": round(pk.level_db, 1)},
               sources=sorted({i[1].manifest.id for i in items}), channel_label=lab, freq_hz=f)
        tones.append((f, lab))
    return tones


def _off_direction(sa: str, sb: str) -> int:
    """+1 if B is the 'off' condition, -1 if A is, 0 if neither."""
    if sb == "off" and sa != "off":
        return 1
    if sa == "off" and sb != "off":
        return -1
    return 0


def _extract_comparisons(cx: _Ctx) -> None:
    unstable_runs = set()
    for c in cx.inp.comparisons:
        if c.kind == "generic" and c.comparable and not c.changed_equipment and c.intervention is None and c.procedure_run_id \
                and not c.overall_significant:
            cx.stable_runs.add(c.procedure_run_id)
    for c in cx.inp.comparisons:
        if c.kind == "generic" and c.comparable and not c.changed_equipment and c.intervention is None and c.overall_significant:
            unstable_runs.add(c.procedure_run_id)
            cx.add(id=_eid("stab", c.id), kind=EvidenceKind.MEASUREMENT_QUALITY, statement_class=StatementClass.CALCULATED,
                   summary=f"Conditions drifted: '{c.label_a}' and '{c.label_b}' differ by {c.overall_delta_db:+.1f} dB although "
                           "nothing was changed, so comparisons from this run are not reliable",
                   params={"code": "unstable"}, sources=[c.id])
    for c in cx.inp.comparisons:
        src = [c.id]
        if not c.comparable:
            iss = "; ".join(i.message for i in c.issues if i.effect == "invalidates")[:400]
            cx.add(id=_eid("nc", c.id), kind=EvidenceKind.NOT_COMPARABLE, statement_class=StatementClass.CALCULATED,
                   summary=f"'{c.label_a}' vs '{c.label_b}' cannot be compared: {iss}", sources=src, valid=False)
            continue
        valid = c.procedure_run_id not in unstable_runs or c.procedure_run_id is None
        changed = {k: v for k, v in c.changed_equipment.items() if k != "input"}
        if c.intervention is not None and c.kind != "state":
            iv = c.intervention
            flags = [iv.changes_source_output, iv.changes_transmission_path, iv.changes_receiver]
            run = cx.runs.get(c.procedure_run_id or "")
            proc = run.procedure_id if run else ""
            if (iv.changes_source_output and (iv.changes_transmission_path or iv.changes_receiver)) or all(f is None for f in flags) or changed:
                why = "it changed the source output and the transmission at the same time" if iv.changes_source_output else \
                      ("other equipment also changed state" if changed else "its effects on source/path/receiver were not described")
                cx.add(id=_eid("conf", c.id), kind=EvidenceKind.CONFOUNDED_INTERVENTION, statement_class=StatementClass.INFERRED,
                       summary=f"Intervention '{iv.description}' changed the level by {c.overall_delta_db:+.1f} dB, but the effect "
                               f"cannot be attributed: {why} (ADV-007)",
                       params={"delta_db": c.overall_delta_db, "target": iv.target}, sources=src, valid=valid)
                continue
            factor = "source" if iv.changes_source_output else ("path" if iv.changes_transmission_path else "receiver")
            if proc == "damping_comparison":
                factor = "damping"
            reduced = [t.freq_hz for t in c.tone_deltas if t.status in ("reduced", "disappeared")]
            unchanged = [t.freq_hz for t in c.tone_deltas if t.status == "unchanged"]
            cx.add(id=_eid("iv", c.id), kind=EvidenceKind.INTERVENTION_EFFECT, statement_class=StatementClass.CALCULATED,
                   summary=f"Intervention '{iv.description}' ({factor}) changed the level by {c.overall_delta_db:+.1f} dB "
                           f"(+/-{c.overall_uncertainty_db:.1f} dB, {c.repeatability} repeatability): "
                           + ("significant" if c.overall_significant else "not significant")
                           + (f"; tones reduced at {', '.join(f'{f:.0f}' for f in reduced)} Hz" if reduced else ""),
                   params={"target": iv.target, "factor": factor, "delta_db": c.overall_delta_db, "u_db": c.overall_uncertainty_db,
                           "significant": c.overall_significant, "reduced": ",".join(f"{f:.2f}" for f in reduced),
                           "unchanged": ",".join(f"{f:.2f}" for f in unchanged), "procedure": proc},
                   sources=src, valid=valid)
            continue
        if not changed:
            continue
        if len(changed) > 1:
            cx.add(id=_eid("multi", c.id), kind=EvidenceKind.NOT_COMPARABLE, statement_class=StatementClass.CALCULATED,
                   summary=f"'{c.label_a}' vs '{c.label_b}': several things changed at once ({', '.join(changed)}); "
                           "the effect cannot be assigned to one of them",
                   sources=src, valid=False)
            continue
        (eq, (sa, sb)), = changed.items()
        direction = _off_direction(sa, sb)
        if direction == 0:
            continue
        d_off = c.overall_delta_db * direction
        if c.overall_significant and d_off < 0:
            cx.add(id=_eid("se", c.id, "all"), kind=EvidenceKind.STATE_EFFECT, statement_class=StatementClass.CALCULATED,
                   summary=f"Switching {eq} off lowered the overall level by {abs(d_off):.1f} dB (+/-{c.overall_uncertainty_db:.1f} dB, "
                           f"{c.repeatability} repeatability)",
                   params={"subject": eq, "delta_db": round(d_off, 2), "u_db": c.overall_uncertainty_db, "repeatability": c.repeatability,
                           "run": c.procedure_run_id or c.id},
                   sources=src, valid=valid)
        elif not c.overall_significant and c.overall_uncertainty_db <= STATE_MAX_UNCERTAINTY_DB:
            cx.add(id=_eid("nse", c.id, "all"), kind=EvidenceKind.NO_STATE_EFFECT, statement_class=StatementClass.CALCULATED,
                   summary=f"Switching {eq} off did not change the overall level measurably ({d_off:+.1f} dB, "
                           f"+/-{c.overall_uncertainty_db:.1f} dB)",
                   params={"subject": eq, "delta_db": round(d_off, 2), "u_db": c.overall_uncertainty_db,
                           "run": c.procedure_run_id or c.id}, sources=src, valid=valid)
        for t in c.tone_deltas:
            if t.delta_db is None:
                continue
            td = t.delta_db * direction
            gone_when_off = (direction == 1 and t.status in ("reduced", "disappeared")) or \
                            (direction == -1 and t.status in ("increased", "appeared"))
            if gone_when_off:
                cx.add(id=_eid("se", c.id, round(t.freq_hz, 1)), kind=EvidenceKind.STATE_EFFECT, statement_class=StatementClass.CALCULATED,
                       summary=f"Tone {t.freq_hz:.1f} Hz fell by {abs(td):.1f} dB with {eq} off",
                       params={"subject": eq, "delta_db": round(td, 2), "repeatability": c.repeatability,
                               "run": c.procedure_run_id or c.id},
                       sources=src, freq_hz=t.freq_hz, valid=valid)
                # Residual check (ADV-001): a tone still detected in both conditions after a significant drop
                if t.status in ("reduced", "increased") and abs(td) < 20:
                    cx.add(id=_eid("resid", c.id, round(t.freq_hz, 1)), kind=EvidenceKind.RESIDUAL_AFTER_OFF,
                           statement_class=StatementClass.INFERRED,
                           summary=f"Tone {t.freq_hz:.1f} Hz is still present with {eq} off (only {abs(td):.1f} dB lower): "
                                   "another source probably also contributes at this frequency",
                           params={"subject": eq}, sources=src, freq_hz=t.freq_hz, valid=valid)
            elif t.status == "unchanged":
                cx.add(id=_eid("nse", c.id, round(t.freq_hz, 1)), kind=EvidenceKind.NO_STATE_EFFECT, statement_class=StatementClass.CALCULATED,
                       summary=f"Tone {t.freq_hz:.1f} Hz did not change with {eq} off",
                       params={"subject": eq, "delta_db": round(td, 2)}, sources=src, freq_hz=t.freq_hz, valid=valid)


def _peaks(cv: CaptureView | None, label_pred) -> list:
    if cv is None or cv.analysis is None:
        return []
    out = []
    for ch in cv.analysis.channels:
        if label_pred(ch.label):
            out += [(ch.label, pk) for pk in ch.peaks]
    return out


def _extract_procedures(cx: _Ctx, tones: list[tuple[float, str]]) -> None:
    for run in cx.inp.runs:
        if run.state != "completed":
            continue
        caps = {k: [cx.caps.get(i) for i in v] for k, v in run.captures.items() if not k.endswith("__rejected")}
        pid = run.procedure_id
        first = lambda key: next((c for c in caps.get(key, []) if c and c.analysis), None)  # noqa: E731
        if pid == "electrical_hum":
            a, b = first("normal"), first("terminated")
            if not (a and b):
                continue
            ac = lambda lab: cx.is_acoustic(a.manifest, lab)  # noqa: E731
            pb = _peaks(b, ac)
            for lab, pk in _peaks(a, ac):
                if pk.prominence_db < 10:
                    continue
                persists = any(_same_f(pk.freq_hz, q.freq_hz) and q.prominence_db >= 6 for _, q in pb)
                cx.add(id=_eid("chain", run.id, round(pk.freq_hz, 1)), kind=EvidenceKind.CHAIN_NOISE_TEST,
                       statement_class=StatementClass.MEASURED,
                       summary=f"Tone {pk.freq_hz:.1f} Hz " + ("is STILL present" if persists else "disappears")
                               + " with the microphone disconnected" + (" (generated in the recording chain)" if persists else
                                                                        " (it comes through the microphone)"),
                       params={"persists": persists}, sources=[a.manifest.id, b.manifest.id], channel_label=lab, freq_hz=pk.freq_hz)
        elif pid == "alias_check":
            a, b = first("rate_a"), first("rate_b")
            if not (a and b):
                continue
            ny = min(a.manifest.sample_rate_hz, b.manifest.sample_rate_hz) * 0.45
            pb = _peaks(b, lambda _l: True)
            for lab, pk in _peaks(a, lambda _l: True):
                if pk.prominence_db < 10 or pk.freq_hz > ny:
                    continue
                stays = any(_same_f(pk.freq_hz, q.freq_hz) for _, q in pb)
                cx.add(id=_eid("alias", run.id, round(pk.freq_hz, 1)), kind=EvidenceKind.ALIAS_TEST, statement_class=StatementClass.MEASURED,
                       summary=f"Tone {pk.freq_hz:.1f} Hz " + ("stays at the same frequency" if stays else "MOVES")
                               + " when the sample rate changes" + ("" if stays else ": it is an alias of ultrasonic content"),
                       params={"moves": not stays}, sources=[a.manifest.id, b.manifest.id], channel_label=lab, freq_hz=pk.freq_hz)
        elif pid == "airborne_control":
            a, b = first("mounted"), first("decoupled")
            if not (a and b):
                continue
            vib = lambda lab: cx.is_vibration(a.manifest, lab)  # noqa: E731
            pb = {round(q.freq_hz): q for _, q in _peaks(b, vib)}
            for lab, pk in _peaks(a, vib):
                if pk.prominence_db < 10:
                    continue
                q = next((v for k, v in pb.items() if _same_f(k, pk.freq_hz)), None)
                diff = pk.level_db - q.level_db if q else pk.prominence_db
                if diff >= AIRBORNE_STRUCTURAL_DB:
                    structural = True
                elif diff < AIRBORNE_SIMILAR_DB:
                    structural = False
                else:
                    continue
                cx.add(id=_eid("air", run.id, round(pk.freq_hz, 1)), kind=EvidenceKind.AIRBORNE_CONTROL,
                       statement_class=StatementClass.MEASURED,
                       summary=f"At {pk.freq_hz:.1f} Hz the mounted contact sensor reads {diff:.1f} dB above the decoupled one: "
                               + ("real structural vibration" if structural else "its signal is explained by airborne sound"),
                       params={"structural": structural, "diff_db": round(diff, 1)}, sources=[a.manifest.id, b.manifest.id],
                       channel_label=lab, freq_hz=pk.freq_hz)
        elif pid in ("source_location_survey", "receiver_position_survey", "contact_survey", "vibration_survey"):
            want_vib = pid in ("contact_survey", "vibration_survey")
            levels = []
            for key, lst in caps.items():
                cv = next((c for c in lst if c and c.analysis), None)
                if not cv:
                    continue
                for ch in cv.analysis.channels:
                    ok = cx.is_vibration(cv.manifest, ch.label) if want_vib else cx.is_acoustic(cv.manifest, ch.label)
                    if ok:
                        mch = next(c for c in cv.manifest.channels if c.label == ch.label)
                        levels.append((ch.levels.level_db, mch.placement.position_id or key, mch.placement.location, cv.manifest.id))
                        break
            if len(levels) >= 2:
                levels.sort(reverse=True)
                spread = levels[0][0] - levels[-1][0]
                if spread >= POSITION_GRADIENT_DB:
                    cx.add(id=_eid("pos", run.id), kind=EvidenceKind.POSITION_GRADIENT, statement_class=StatementClass.MEASURED,
                           summary=f"{'Vibration' if want_vib else 'Sound'} level is highest at {levels[0][1]}"
                                   f"{' (' + levels[0][2] + ')' if levels[0][2] else ''}, {spread:.1f} dB above the lowest position "
                                   + ("" if want_vib else "(at low frequency, room modes can also create such differences)"),
                           params={"position": levels[0][1], "location": levels[0][2], "spread_db": round(spread, 1),
                                   "vibration": want_vib}, sources=[x[3] for x in levels])
        elif pid == "resonance_investigation":
            cv = first("tap")
            if not cv:
                continue
            obj = run.params.get("object", "object")
            for ch in cv.analysis.channels:
                for pk in ch.peaks:
                    if pk.prominence_db < 10:
                        continue
                    match = next((f for f, _ in tones if abs(f - pk.freq_hz) <= 0.03 * f), None)
                    cx.add(id=_eid("tap", run.id, round(pk.freq_hz)), kind=EvidenceKind.RESONANCE, statement_class=StatementClass.MEASURED,
                           summary=f"Tapping {obj} excites a ring at {pk.freq_hz:.1f} Hz"
                                   + (f", matching the problem tone at {match:.1f} Hz" if match else ""),
                           params={"tap": True, "subject": obj, "matches": match if match else -1.0},
                           sources=[cv.manifest.id], channel_label=ch.label, freq_hz=pk.freq_hz)
        elif pid == "speaker_buzz":
            cv = first("sweep")
            if not cv or cv.manifest.stimulus is None:
                continue
            p = cv.manifest.stimulus.params
            f0, f1, T = p.get("f0", 30.0), p.get("f1", 2000.0), p.get("duration", 20.0)
            for ch in cv.analysis.channels:
                times = [t for t in ch.transients.event_times_s if t <= T]
                if len(times) >= 2:
                    freqs = sorted({round(f0 * (f1 / f0) ** (t / T)) for t in times})
                    cx.add(id=_eid("buzz", run.id, ch.label), kind=EvidenceKind.TRANSIENTS, statement_class=StatementClass.MEASURED,
                           summary=f"Buzz/rattle events during the sweep of {run.params.get('target', 'the speaker')} at about "
                                   f"{', '.join(map(str, freqs[:8]))} Hz",
                           params={"periodic": False, "rate": float(len(times)), "subject": run.params.get("target", ""),
                                   "procedure": run.id}, sources=[cv.manifest.id], channel_label=ch.label)
                    break


def _extract_user(cx: _Ctx) -> None:
    p = cx.inp.case.problem
    if p.summary or p.character:
        cx.add(id=_eid("user", cx.inp.case.id), kind=EvidenceKind.USER_OBSERVATION, statement_class=StatementClass.USER_ASSERTED,
               summary=f"User report: {p.summary or ''} " + (f"[{', '.join(p.character)}]" if p.character else ""),
               params={"character": ",".join(p.character)})


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _level(sup: int, strong_sup: int, con: int) -> SupportLevel:
    if sup and con:
        return SupportLevel.WEAKENED
    if con:
        return SupportLevel.CONTRADICTED
    if strong_sup >= 2 or (strong_sup >= 1 and sup >= 2):
        return SupportLevel.STRONG
    if sup:
        return SupportLevel.SUPPORTED
    return SupportLevel.UNDETERMINED


def _rules(cx: _Ctx, tones) -> list[Hypothesis]:
    ev = [e for e in cx.ev if e.valid]
    by = defaultdict(list)
    for e in ev:
        by[e.kind].append(e)
    hyps: list[Hypothesis] = []
    eq_names = {e.id: e.name for e in cx.inp.case.equipment}

    # R-SRC-001: equipment as excitation source (on/off evidence only)
    for eq in cx.inp.case.equipment:
        sup = [e for e in by[EvidenceKind.STATE_EFFECT] if e.params.get("subject") == eq.id]
        con = [e for e in by[EvidenceKind.NO_STATE_EFFECT] if e.params.get("subject") == eq.id and e.freq_hz is None]
        con_t = [e for e in by[EvidenceKind.NO_STATE_EFFECT] if e.params.get("subject") == eq.id and e.freq_hz is not None]
        # Independence is per procedure run (or standalone comparison), not per channel:
        # the same on/off sequence seen on two channels is one experiment. A run
        # contradicts only if NO channel showed an effect in that run (a quiet
        # secondary channel does not cancel an effect seen at the receiver).
        comps = {e.params.get("run") or e.sources[0] for e in sup}
        con = [e for e in con if (e.params.get("run") or e.sources[0]) not in comps]
        con_runs = {e.params.get("run") or e.sources[0] for e in con}
        # Strong = two independent experiments, or one experiment with measured
        # repeatability whose A-B-A stability check passed.
        stable_measured = any(e.params.get("repeatability") == "measured" and e.params.get("run") in cx.stable_runs for e in sup)
        strong = len(comps) + (1 if stable_measured else 0)
        lvl = _level(len(comps), strong, len(con_runs))
        freqs = sorted({round(e.freq_hz, 1) for e in sup if e.freq_hz})
        expl = []
        if sup:
            expl.append(f"Switching {eq.name} off changed the problem in {len(comps)} independent experiment(s)"
                        + (" with measured repeatability and a passed on-off-on stability check" if stable_measured
                           else " (single experiment without a passed stability check)"))
        if con:
            expl.append(f"Switching {eq.name} off had no measurable effect in {len(con)} comparison(s) able to resolve 3 dB")
        if con_t and not sup:
            expl.append(f"{len(con_t)} tone(s) were unchanged with {eq.name} off")
        if not sup and not con:
            expl.append(f"No on/off comparison of {eq.name} yet. Spectral similarity alone cannot implicate it (ADV-002)")
        stmt = f"{eq.name} is an excitation source of the problem" + (f" (tones {', '.join(map(str, freqs))} Hz)" if freqs else "")
        hyps.append(Hypothesis(id=f"H-SRC-{eq.id}", category=HypothesisCategory.SOURCE, subject=eq.id, statement=stmt, level=lvl,
                               supporting=[e.id for e in sup], contradicting=[e.id for e in con],
                               missing_tests=[] if lvl is SupportLevel.STRONG else [f"equipment_state:{eq.id}"],
                               rules=["R-SRC-001@1"], explanation=expl))

    # R-ADD-001: residual after a source is off -> additional source (ADV-001)
    seen = set()
    for e in by[EvidenceKind.RESIDUAL_AFTER_OFF]:
        key = round(e.freq_hz or 0)
        if key in seen:
            continue
        seen.add(key)
        explained = [s for s in by[EvidenceKind.STATE_EFFECT] if s.freq_hz and _same_f(s.freq_hz, e.freq_hz)
                     and s.params.get("subject") != e.params.get("subject")]
        hyps.append(Hypothesis(
            id=f"H-ADD-{key}", category=HypothesisCategory.ADDITIONAL_SOURCE, subject="unidentified", freq_hz=e.freq_hz,
            statement=f"Another source (besides {eq_names.get(e.params.get('subject'), e.params.get('subject'))}) contributes at {e.freq_hz:.1f} Hz",
            level=SupportLevel.SUPPORTED, supporting=[e.id] + [s.id for s in explained], rules=["R-ADD-001@1"],
            missing_tests=[f"equipment_state:{q.id}" for q in cx.inp.case.equipment if q.id != e.params.get("subject")][:3],
            explanation=["The tone remains after switching the first source off, so the total cannot be attributed to one source",
                         "Contribution shares are not estimated: that needs an on/off test for each source (ADV-010)"]
                        + ([f"Also reduced when {eq_names.get(s.params.get('subject'), '?')} is off" for s in explained])))

    src_level = {h.subject: h.level for h in hyps if h.category is HypothesisCategory.SOURCE}

    # R-PATH-001 / R-PATH-002: structural vs airborne path
    air = by[EvidenceKind.AIRBORNE_CONTROL]
    coh = by[EvidenceKind.STRUCTURAL_COHERENCE]
    ivs = by[EvidenceKind.INTERVENTION_EFFECT]
    for eq in cx.inp.case.equipment:
        path_iv = [e for e in ivs if e.params.get("target") in (eq.id, eq.name) and e.params.get("factor") == "path"]
        if SUPPORT_ORDER[src_level.get(eq.id, SupportLevel.UNDETERMINED)] < 3 and not path_iv:
            continue
        # Frequency-specific evidence (airborne control, coherence) only bears on this
        # equipment at the frequencies where switching it off changed the signal.
        eq_freqs = [e.freq_hz for e in by[EvidenceKind.STATE_EFFECT] if e.params.get("subject") == eq.id and e.freq_hz]
        linked = lambda e: e.freq_hz is not None and any(_same_f(e.freq_hz, f) for f in eq_freqs)  # noqa: E731
        sup, con = [], []
        for e in air:
            if linked(e):
                (sup if e.params.get("structural") else con).append(e)
        for e in path_iv:
            reduced = bool(e.params.get("reduced"))
            if (e.params.get("significant") and (e.params.get("delta_db") or 0) < 0) or reduced:
                sup.append(e)
            elif not e.params.get("significant") and (e.params.get("u_db") or 99) <= STATE_MAX_UNCERTAINTY_DB:
                con.append(e)
        consistent = [e for e in coh if linked(e)]
        lvl = _level(len(sup), len(sup), len(con))
        if lvl is SupportLevel.CONTRADICTED:
            lvl = SupportLevel.WEAKENED  # failing to find a structural path does not rule one out entirely
        expl = []
        if consistent and not sup:
            expl.append("Microphone and contact/vibration signals are coherent, but that is only consistent with a structural "
                        "path: airborne excitation of the contact sensor has not been excluded (ADV-003)")
        if sup:
            expl.append("A decisive test (airborne control or isolation) supports transmission through the structure")
        if con:
            expl.append("Airborne control or isolation results argue against a dominant structural path")
        hyps.append(Hypothesis(id=f"H-STR-{eq.id}", category=HypothesisCategory.STRUCTURAL_PATH, subject=eq.id,
                               statement=f"Vibration from {eq.name} travels through supports/structure to the receiver",
                               level=lvl, supporting=[e.id for e in sup + consistent], contradicting=[e.id for e in con],
                               missing_tests=[t for t, need in (("airborne_control:", not air),
                                                                (f"isolation_comparison:{eq.id}", not path_iv)) if need],
                               rules=["R-PATH-001@1"], explanation=expl))
        air_lvl = SupportLevel.SUPPORTED if (lvl is SupportLevel.WEAKENED and SUPPORT_ORDER[src_level.get(eq.id, SupportLevel.UNDETERMINED)] >= 3) \
            else SupportLevel.UNDETERMINED
        hyps.append(Hypothesis(id=f"H-AIR-{eq.id}", category=HypothesisCategory.AIRBORNE_PATH, subject=eq.id,
                               statement=f"Sound from {eq.name} reaches the receiver mainly through the air", level=air_lvl,
                               supporting=[e.id for e in con] if air_lvl is SupportLevel.SUPPORTED else [],
                               rules=["R-PATH-002@1"],
                               explanation=["Inferred by elimination: the source is supported and the structural path is weakened"]
                               if air_lvl is SupportLevel.SUPPORTED else ["No test has yet separated airborne from structural transmission"],
                               missing_tests=[] if air_lvl is SupportLevel.SUPPORTED else [f"isolation_comparison:{eq.id}"]))

    # R-RES-001: resonance
    res_groups: dict[int, list] = defaultdict(list)
    for e in by[EvidenceKind.RESONANCE]:
        res_groups[round(e.freq_hz or 0)].append(e)
    damp = [e for e in ivs if e.params.get("factor") == "damping"]
    for fk, items in res_groups.items():
        f = items[0].freq_hz
        tap = [e for e in items if e.params.get("tap") and (e.params.get("matches") or -1) > 0]
        subj = next((str(e.params.get("subject")) for e in tap), "a structure near the sensor")
        dsup = [e for e in damp if any(_same_f(float(x), f) for x in str(e.params.get("reduced") or "").split(",") if x)]
        dcon = [e for e in damp if any(_same_f(float(x), f) for x in str(e.params.get("unchanged") or "").split(",") if x)]
        lvl = _level(len(tap) + len(dsup), len(dsup) + (1 if tap and dsup else 0), len(dcon))
        hyps.append(Hypothesis(id=f"H-RES-{fk}", category=HypothesisCategory.RESONANCE, subject=subj, freq_hz=f,
                               statement=f"{subj[0].upper() + subj[1:]} resonates near {f:.1f} Hz and amplifies the problem",
                               level=lvl, supporting=[e.id for e in items if e not in tap] + [e.id for e in tap + dsup],
                               contradicting=[e.id for e in dcon], rules=["R-RES-001@1"],
                               missing_tests=[t for t, need in (("resonance_investigation:", not tap), ("damping_comparison:", not damp)) if need],
                               explanation=(["A resonance-like peak alone does not identify the resonating object"] if not tap else
                                            [f"Tap test on {subj} rings at the problem frequency"])
                               + (["Damping reduced the tone"] if dsup else [])))

    # R-RAT-001: rattle / buzz
    tr = by[EvidenceKind.TRANSIENTS]
    if tr:
        subj = next((str(e.params.get("subject")) for e in tr if e.params.get("subject")), "a loose part")
        strong = [e for e in tr if e.params.get("periodic") or e.params.get("subject")]
        hyps.append(Hypothesis(id="H-RAT", category=HypothesisCategory.RATTLE, subject=subj,
                               statement=f"Intermittent impacts (rattle or buzz) from {subj} contribute",
                               level=SupportLevel.SUPPORTED if strong else SupportLevel.UNDETERMINED,
                               supporting=[e.id for e in tr], rules=["R-RAT-001@1"],
                               missing_tests=["speaker_buzz:"] if not any(e.params.get("subject") for e in tr) else [],
                               explanation=["Impulsive events were detected; periodic events or events locked to a sweep point to "
                                            "a mechanical rattle rather than random background"]))

    # R-HUM-001 / R-CHN-001: mains-related hum vs recording-chain noise
    mains = by[EvidenceKind.MAINS_HARMONICS]
    chain = by[EvidenceKind.CHAIN_NOISE_TEST]
    fams = {round(e.freq_hz or 0): e for e in mains}
    for e in chain:
        if e.params.get("persists") and not any(_same_f(e.freq_hz, k) for k in fams):
            fams[round(e.freq_hz)] = e
    for f0, e0 in fams.items():
        rel = [c for c in chain if any(_same_f(c.freq_hz, f0 * k) for k in range(1, 8))]
        pos = [c for c in rel if c.params.get("persists")]
        neg = [c for c in rel if not c.params.get("persists")]
        chain_lvl = _level(1 if pos else 0, 0, 1 if (neg and not pos) else 0)
        hyps.append(Hypothesis(id=f"H-CHN-{f0}", category=HypothesisCategory.RECORDING_CHAIN, subject="recording chain",
                               freq_hz=float(f0), statement=f"The {f0} Hz hum is generated electrically in the recording chain "
                                                            "(ground loop, cable, interface)", level=chain_lvl,
                               supporting=[c.id for c in pos] + ([e0.id] if e0.kind is EvidenceKind.MAINS_HARMONICS else []),
                               contradicting=[c.id for c in neg], rules=["R-CHN-001@1"],
                               missing_tests=[] if rel else ["electrical_hum:"],
                               explanation=["Present with the microphone disconnected" if pos else
                                            ("Absent with the microphone disconnected" if neg else
                                             "Mains-related harmonics can be electrical or acoustic; the disconnect test separates them")]))
        mains_src = [s for s in by[EvidenceKind.STATE_EFFECT] if s.freq_hz and any(_same_f(s.freq_hz, f0 * k) for k in range(1, 8))]
        hum_lvl = SupportLevel.WEAKENED if pos else (SupportLevel.SUPPORTED if (neg and mains_src) else SupportLevel.UNDETERMINED)
        hyps.append(Hypothesis(id=f"H-HUM-{f0}", category=HypothesisCategory.ELECTRICAL_HUM,
                               subject=eq_names.get(mains_src[0].params.get("subject"), "mains-powered equipment") if mains_src else "mains-powered equipment",
                               freq_hz=float(f0), statement=f"Mains-powered equipment radiates {f0} Hz hum acoustically or mechanically "
                                                            "(transformer, motor, ballast)",
                               level=hum_lvl, supporting=[s.id for s in mains_src] + [c.id for c in neg], contradicting=[c.id for c in pos],
                               rules=["R-HUM-001@1"], missing_tests=["electrical_hum:"] if not rel else [],
                               explanation=["The hum persists without the microphone, which argues for the recording chain"] if pos else
                               ["Hum reaches the recording through the microphone"] if neg else
                               ["Not yet separated from recording-chain hum"]))

    # R-ART-001: measurement artifacts
    mq = by[EvidenceKind.MEASUREMENT_QUALITY]
    codes = sorted({str(e.params.get("code")) for e in mq})
    if codes:
        hyps.append(Hypothesis(id="H-ART-quality", category=HypothesisCategory.MEASUREMENT_ARTIFACT, subject="measurement",
                               statement="Measurement problems (" + ", ".join(codes) + ") may explain part of what was observed",
                               level=SupportLevel.SUPPORTED, supporting=[e.id for e in mq], rules=["R-ART-001@1"],
                               explanation=["These captures should be repeated with corrected settings before drawing conclusions"],
                               missing_tests=["baseline:"]))
    alias_ev = by[EvidenceKind.ALIAS_TEST]
    alias_risk = [(cv.manifest.id, q) for cv in cx.inp.captures if cv.analysis for ch in cv.analysis.channels for q in ch.quality
                  if q.code.value == "alias_risk"]
    if alias_ev or alias_risk:
        moving = [e for e in alias_ev if e.params.get("moves")]
        staying = [e for e in alias_ev if not e.params.get("moves")]
        lvl = SupportLevel.SUPPORTED if moving else (SupportLevel.CONTRADICTED if staying else SupportLevel.UNDETERMINED)
        hyps.append(Hypothesis(id="H-ART-alias", category=HypothesisCategory.MEASUREMENT_ARTIFACT, subject="sampling",
                               statement="Some tones are aliases of ultrasonic content, not real audible sound", level=lvl,
                               supporting=[e.id for e in moving], contradicting=[e.id for e in staying], rules=["R-ART-002@1"],
                               missing_tests=[] if alias_ev else ["alias_check:"],
                               explanation=["Tones moved with the sample rate"] if moving else
                               ["Tones stayed fixed across sample rates"] if staying else ["Tones near Nyquist; not yet tested"]))
    return hyps


def _conclude(cx: _Ctx, hyps: list[Hypothesis]) -> tuple[str, list[str]]:
    reasons = []
    if not cx.inp.captures:
        return "inconclusive", ["No measurements yet: record a baseline first"]
    if not any(c.analysis for c in cx.inp.captures):
        return "inconclusive", ["Captures have not been analysed yet"]
    nc = [e for e in cx.ev if e.kind is EvidenceKind.NOT_COMPARABLE]
    if cx.inp.comparisons and len(nc) == len(cx.inp.comparisons):
        reasons.append("None of the comparisons were comparable: " + nc[0].summary)
    primary = [h for h in hyps if h.category in PRIMARY and SUPPORT_ORDER[h.level] >= 3 and h.id != "H-ART-quality"]
    if any(h.id == "H-ART-quality" for h in hyps):
        reasons.append("Some captures have measurement problems (see the measurement hypothesis)")
    if not primary:
        reasons.append("No explanation has reached 'supported': the evidence so far cannot separate the candidates")
        return "inconclusive", reasons
    if len(primary) == 1:
        return "leading_explanation", reasons
    return "multiple_explanations", reasons


def diagnose(inp: DiagnosticInputs) -> DiagnosisSnapshot:
    from .next_tests import recommend

    cx = _Ctx(inp)
    tones = _extract_measurements(cx)
    _extract_comparisons(cx)
    _extract_procedures(cx, tones)
    _extract_user(cx)
    hyps = _rules(cx, tones)
    hyps.sort(key=lambda h: (-SUPPORT_ORDER[h.level], -len(h.supporting), len(h.contradicting), h.id))
    conclusion, reasons = _conclude(cx, hyps)
    nxt = recommend(inp, hyps, conclusion)
    return DiagnosisSnapshot(id=f"dx-{uuid.uuid4().hex[:12]}", case_id=inp.case.id, created_utc=utcnow(),
                             ruleset_version=RULESET_VERSION, conclusion=conclusion, abstention_reasons=reasons,
                             evidence=cx.ev, hypotheses=hyps, next_tests=nxt)


__all__ = ["diagnose", "DiagnosticInputs", "CaptureView", "RULESET_VERSION"]
