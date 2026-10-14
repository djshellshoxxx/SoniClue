"""Report model builder (docs/specs/14-reporting-and-export.md).

``build_report`` is a pure function from case data to a ReportDocument plus
figure data. Renderers (html, pdf, json, csv) live in ``reporting.render``.
Every statement carries a StatementClass. Measured, calculated, inferred,
user-asserted and unresolved statements are visibly distinguished in every
format.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field

import numpy as np

from .. import BUILD_ID, __version__
from ..diagnostics.engine import RULESET_VERSION
from ..domain.model import (
    SUPPORT_ORDER,
    AnalysisResult,
    CalibrationProfile,
    Case,
    CaptureManifest,
    ComparisonResult,
    DiagnosisSnapshot,
    ProcedureRun,
    ReportDocument,
    ReportSection,
    ReportStatement,
    ReportTable,
    StatementClass,
    utcnow,
)

M, C, I, U, Q = (StatementClass.MEASURED, StatementClass.CALCULATED, StatementClass.INFERRED,
                 StatementClass.USER_ASSERTED, StatementClass.UNRESOLVED)
REDACTABLE = ("names", "locations", "serials", "notes")

LIMITATIONS = [
    "Uncalibrated channels report levels relative to the converter's full scale (dBFS); they are not sound pressure or acceleration.",
    "Contact pickups give relative vibration only and also respond to airborne sound.",
    "Coherence and matching frequencies show that signals are related; they do not establish cause or transmission direction.",
    "Support levels are ordinal judgements from deterministic rules, not probabilities.",
    "Comparisons assume the background and the unchanged equipment stayed constant between captures; ABA repeats check this.",
    "Hardware qualification status of the devices used is listed in the setup section; unqualified devices may be inaccurate.",
]


@dataclass
class FigureSpec:
    title: str
    xlabel: str
    ylabel: str
    series: list[tuple[str, np.ndarray, np.ndarray]]
    logx: bool = True


@dataclass
class ReportInputs:
    case: Case
    captures: list[tuple[CaptureManifest, AnalysisResult | None, dict]]
    comparisons: list[ComparisonResult]
    diagnosis: DiagnosisSnapshot | None
    calibrations: list[CalibrationProfile]
    runs: list[ProcedureRun]
    annotations: list = field(default_factory=list)
    qualification: dict[str, str] = field(default_factory=dict)  # device name -> status
    clock_mappings: list = field(default_factory=list)
    report_version: int = 1
    redact: tuple[str, ...] = ()


def _red(text: str, kind: str, redact) -> str:
    return "[redacted]" if (kind in redact and text) else text


def case_digest(case: Case, captures) -> str:
    h = hashlib.sha256(case.model_dump_json().encode())
    for m, _, _ in sorted(captures, key=lambda t: t[0].id):
        for c in m.chunks:
            h.update(c.sha256.encode())
    return h.hexdigest()


def build_report(inp: ReportInputs) -> tuple[ReportDocument, dict[str, FigureSpec]]:
    r = inp.redact
    case = inp.case
    figs: dict[str, FigureSpec] = {}
    sections: list[ReportSection] = []
    dx = inp.diagnosis
    simulated = any(m.source == "simulated" for m, _, _ in inp.captures)

    # 1 summary
    st = []
    if simulated:
        st.append(ReportStatement(cls=M, text="WARNING: this case contains SIMULATED data. It demonstrates the workflow and is not a physical measurement."))
    if dx:
        concl = {"leading_explanation": "One explanation is supported by the evidence.",
                 "multiple_explanations": "Several explanations are supported; they may act together.",
                 "inconclusive": "The evidence does not yet support any explanation (SonicClue abstains)."}[dx.conclusion]
        st.append(ReportStatement(cls=I, text=concl, refs=[dx.id]))
        for h in dx.hypotheses[:5]:
            if SUPPORT_ORDER[h.level] >= 3:
                st.append(ReportStatement(cls=I, text=f"{h.statement} [{h.level.value.replace('_', ' ')}]", refs=[h.id]))
        for reason in dx.abstention_reasons:
            st.append(ReportStatement(cls=Q, text=reason))
    else:
        st.append(ReportStatement(cls=Q, text="No diagnosis has been computed for this case yet."))
    sections.append(ReportSection(key="summary", title="Summary", statements=st))

    # 2 problem
    p = case.problem
    st = [ReportStatement(cls=U, text=_red(p.summary, "notes", r) or "(no description given)")]
    if p.character:
        st.append(ReportStatement(cls=U, text="Character: " + ", ".join(p.character)))
    if p.receiver:
        st.append(ReportStatement(cls=U, text="Affected receiver: " + _red(p.receiver, "locations", r)))
    if p.approx_band_hz:
        st.append(ReportStatement(cls=U, text=f"Approximate band of interest: {p.approx_band_hz[0]:g}-{p.approx_band_hz[1]:g} Hz"))
    for a in inp.annotations:
        st.append(ReportStatement(cls=U, text=f"Note ({a.target}): " + _red(a.text, "notes", r)))
    eq_tab = ReportTable(title="Candidate equipment", columns=["id", "name", "kind"],
                         rows=[[e.id, _red(e.name, "names", r), e.kind] for e in case.equipment])
    sections.append(ReportSection(key="problem", title="Problem description", statements=st, tables=[eq_tab]))

    # 3 setup
    sens_tab = ReportTable(title="Sensors", columns=["id", "kind", "model", "serial", "quantity"],
                           rows=[[s.id, s.kind.value, s.model, _red(s.serial, "serials", r), s.quantity.value] for s in case.sensors])
    cal_tab = ReportTable(title="Calibration profiles", columns=["id", "sensor", "sensitivity (FS/unit)", "ref gain dB", "valid band Hz",
                                                                 "uncertainty dB (k=2)", "method", "created"],
                          rows=[[c.id, c.sensor_id, f"{c.sensitivity_fs_per_unit:.4g}", "-" if c.reference_gain_db is None else f"{c.reference_gain_db:g}",
                                 f"{c.valid_band_hz[0]:g}-{c.valid_band_hz[1]:g}", f"{c.uncertainty_db:.2f}", c.method,
                                 c.created_utc.date().isoformat()] for c in inp.calibrations])
    devs = sorted({m.device.name for m, _, _ in inp.captures})
    qual_tab = ReportTable(title="Device qualification", columns=["device", "status"],
                           rows=[[_red(d, "names", r), inp.qualification.get(d, "UNQUALIFIED")] for d in devs])
    tiers = sorted({a.tier for _, a, _ in inp.captures if a})
    st = [ReportStatement(cls=C, text=f"Capability tier(s) of the analysed captures: {', '.join(map(str, tiers)) or 'n/a'}")]
    st.append(ReportStatement(cls=M, text="Devices not marked QUALIFIED have not been verified on reference hardware; their accuracy is unknown."))
    sections.append(ReportSection(key="setup", title="Sensors, calibration and devices", statements=st, tables=[sens_tab, cal_tab, qual_tab]))

    # 4 measurements
    cap_rows, lvl_rows = [], []
    for m, a, arrays in inp.captures:
        flags = "; ".join(sorted({q.code.value for q in m.quality})) or "-"
        cap_rows.append([m.id, m.created_utc.strftime("%Y-%m-%d %H:%M"), _red(m.context.condition_label, "notes", r) or "-",
                         f"{m.duration_s:.1f}", f"{m.sample_rate_hz:g}", _red(m.device.name, "names", r), m.source, m.status, flags])
        if a:
            for ch in a.channels:
                mch = next((x for x in m.channels if x.index == ch.channel), None)
                pos = mch.placement.position_id or _red(mch.placement.location, "locations", r) if mch else ""
                q = "; ".join(sorted({x.code.value for x in ch.quality})) or "-"
                lvl_rows.append([m.id, ch.label, pos or "-", f"{ch.levels.level_db:.1f} {ch.levels.level_ref}",
                                 ", ".join(f"{pk.freq_hz:.1f}" for pk in ch.peaks[:6]) or "-", str(ch.n_averages), q])
    sections.append(ReportSection(key="measurements", title="Measurements",
                                  statements=[ReportStatement(cls=M, text=f"{len(inp.captures)} captures. Original samples are stored unmodified "
                                                                          "(float32) with SHA-256 checksums.")],
                                  tables=[ReportTable(title="Captures", columns=["id", "time (UTC)", "condition", "s", "Hz", "device", "source",
                                                                                "status", "quality flags"], rows=cap_rows),
                                          ReportTable(title="Channel levels and tones", columns=["capture", "channel", "position", "level",
                                                                                                 "tones (Hz)", "averages", "flags"], rows=lvl_rows)],
                                  figures=_spectrum_figures(inp, figs)))

    # 5 methodology
    an = next((a for _, a, _ in inp.captures if a), None)
    st = []
    if an:
        c = an.config
        st.append(ReportStatement(cls=C, text=f"Spectra: Welch PSD, {c.window} window, target resolution {c.resolution_hz:g} Hz, "
                                              f"{c.overlap*100:.0f}% overlap, at least {c.min_averages} independent averages; one-sided density "
                                              f"(unit^2/Hz); segments touching gaps or clipping excluded. Analysis algorithm {an.algorithm_version}."))
        st.append(ReportStatement(cls=C, text=f"Tones: local median noise floor, prominence >= {c.tone_prominence_db:g} dB, main-lobe power "
                                              f"integration. Coherence significance at alpha={c.coherence_alpha:g}: threshold 1-alpha^(1/(n-1))."))
    st.append(ReportStatement(cls=C, text="Comparisons: delta = after - before in dB; significant only if |delta| exceeds both the 95% interval "
                                          "(Welch-Satterthwaite t-interval with repeats, or estimated from averaging) and 1 dB."))
    st.append(ReportStatement(cls=C, text=f"Diagnostic ruleset {RULESET_VERSION}: deterministic rules with ordinal support levels."))
    for run in inp.runs:
        st.append(ReportStatement(cls=M, text=f"Procedure {run.procedure_id} rev {run.revision} ({run.state}), params {run.params or '-'}",
                                  refs=[run.id]))
    sections.append(ReportSection(key="methodology", title="Test methodology", statements=st))

    # 6 evidence
    if dx:
        st = [ReportStatement(cls=e.statement_class, text=("[redacted]" if ("names" in r or "notes" in r) else e.summary) + ("" if e.valid else " [not usable as evidence]"), refs=[e.id])
              for e in dx.evidence]
        sections.append(ReportSection(key="evidence", title="Evidence", statements=st))
        # 7 hypotheses
        rows = []
        st = []
        for h in dx.hypotheses:
            rows.append([h.level.value.replace("_", " "), h.statement, str(len(h.supporting)), str(len(h.contradicting)), ", ".join(h.rules)])
            for line in h.explanation:
                st.append(ReportStatement(cls=I, text=f"{h.statement}: {line}", refs=[h.id]))
            if h.missing_tests and SUPPORT_ORDER[h.level] < 4:
                st.append(ReportStatement(cls=Q, text=f"Open for '{h.statement}': missing tests {', '.join(t.rstrip(':') for t in h.missing_tests)}"))
        sections.append(ReportSection(key="hypotheses", title="Competing hypotheses", statements=st,
                                      tables=[ReportTable(title="Hypotheses (ranked)", columns=["support", "hypothesis", "supporting", "conflicting", "rules"], rows=rows)]))
    # 8 comparisons
    rows = []
    st = []
    for c in inp.comparisons:
        rows.append([c.id, f"{c.label_a} -> {c.label_b}", c.channel_label, f"{c.overall_delta_db:+.1f}", f"{c.overall_uncertainty_db:.1f}",
                     "yes" if c.overall_significant else "no", c.repeatability, "yes" if c.comparable else "NO"])
        for i in c.issues:
            st.append(ReportStatement(cls=C, text=f"{c.label_a} vs {c.label_b}: {i.message} ({i.effect})", refs=[c.id]))
        if c.intervention:
            st.append(ReportStatement(cls=U, text=f"Intervention: {_red(c.intervention.description, 'notes', r)} "
                                                  f"(source {c.intervention.changes_source_output}, path {c.intervention.changes_transmission_path}, "
                                                  f"receiver {c.intervention.changes_receiver})", refs=[c.id]))
    for m in inp.clock_mappings:
        st.append(ReportStatement(cls=C, text=f"Clock mapping {m.reference_capture_id} <- {m.other_capture_id}: offset {m.offset_s * 1000:.3f} ms, "
                                              f"drift {m.drift_ppm:+.2f} ppm, timing uncertainty {m.residual_s * 1e6:.1f} us; synchronized analysis "
                                              + (f"allowed below {m.eligible_max_freq_hz:.0f} Hz" if m.eligible_max_freq_hz > 0 else "NOT allowed"),
                                  refs=[m.id]))
    figs_c = _comparison_figures(inp, figs)
    sections.append(ReportSection(key="comparisons", title="Before/after comparisons and interventions", statements=st,
                                  tables=[ReportTable(title="Comparisons (delta = B - A)", columns=["id", "conditions", "channel", "delta dB", "+/- dB (95%)",
                                                                                                    "significant", "repeatability", "comparable"], rows=rows)],
                                  figures=figs_c))
    # 9 next tests
    if dx:
        st = [ReportStatement(cls=I, text=f"{t.title}: {t.reason}" + ("" if t.available else f" (unavailable: {t.unavailable_reason})"))
              for t in dx.next_tests]
        sections.append(ReportSection(key="next_tests", title="Recommended next tests", statements=st))
    # 10 limitations
    st = [ReportStatement(cls=Q, text=t) for t in LIMITATIONS]
    for m, a, _ in inp.captures:
        for q in m.quality:
            if q.severity.value != "info":
                st.append(ReportStatement(cls=M, text=f"{m.id}: {q.message}"))
    sections.append(ReportSection(key="limitations", title="Measurement limitations", statements=st))
    # 11 reproduction
    st = [ReportStatement(cls=M, text=f"Software SonicClue {__version__} (build {BUILD_ID}); ruleset {RULESET_VERSION}.")]
    for m, a, _ in inp.captures[:20]:
        chs = "; ".join(f"{c.label}: sensor {c.sensor_id or '-'}, pos {c.placement.position_id or _red(c.placement.location, 'locations', r) or '-'}, "
                        f"mount {c.placement.mounting.value}, gain {c.input_gain_db if c.input_gain_db is not None else '?'} dB, AGC {c.agc}"
                        for c in m.channels)
        st.append(ReportStatement(cls=M, text=f"{m.id} ({m.context.condition_label or '-'}): {m.sample_rate_hz:g} Hz, {chs}; "
                                              f"equipment {json.dumps(m.context.equipment_state)}"))
    sections.append(ReportSection(key="reproduction", title="Reproduction instructions", statements=st))

    doc = ReportDocument(id=f"rep-{uuid.uuid4().hex[:12]}", case_id=case.id, report_version=inp.report_version, created_utc=utcnow(),
                         software_version=__version__, ruleset_version=RULESET_VERSION, redactions=list(r),
                         case_digest=case_digest(case, inp.captures), sections=sections)
    return doc, figs


def _spectrum_figures(inp: ReportInputs, figs: dict) -> list[str]:
    keys = []
    for m, a, arrays in inp.captures[:6]:
        if not a or not arrays:
            continue
        series = []
        for ch in a.channels:
            f, p = arrays.get(f"f_{ch.channel}"), arrays.get(f"psd_{ch.channel}")
            if f is None or p is None:
                continue
            from ..domain import units

            ref2 = units.DB_REFERENCE[ch.quantity] ** 2
            series.append((f"{ch.label} ({ch.unit})", f[1:], 10 * np.log10(np.maximum(p[1:], 1e-30) / ref2)))
        if series:
            k = f"psd_{m.id}"
            figs[k] = FigureSpec(title=f"Spectrum: {m.context.condition_label or m.id}", xlabel="Frequency (Hz)",
                                 ylabel="PSD (dB re ref^2/Hz)", series=series)
            keys.append(k)
    return keys


def _comparison_figures(inp: ReportInputs, figs: dict) -> list[str]:
    keys = []
    for c in inp.comparisons[:6]:
        if not c.band_deltas:
            continue
        x = np.array([b.center_hz for b in c.band_deltas])
        y = np.array([b.delta_db for b in c.band_deltas])
        k = f"cmp_{c.id}"
        figs[k] = FigureSpec(title=f"Band level change: {c.label_a} -> {c.label_b}", xlabel="Band centre (Hz)", ylabel="Delta (dB)",
                             series=[("delta", x, y)])
        keys.append(k)
    return keys
