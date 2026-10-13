#!/usr/bin/env python3
"""Generate JSON Schemas and contract examples from the canonical pydantic models.

    python tools/gen_schemas.py            # write docs/specs/schemas + docs/specs/contracts/examples
    python tools/gen_schemas.py --check    # exit 1 if checked-in schemas are stale (used by CI/tests)

Valid examples come from a deterministic fixture built through the real APIs.
Invalid examples are deterministic mutations, one per constraint class:
missing required field, out-of-range value, bad enum, pattern violation,
unknown field and newer schema_version. Each invalid example has a sibling
``*.expected-error.json`` naming the JSON-Schema keyword and the JSON
Pointer, or "semantic" for rules only pydantic enforces (cross-field checks).
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sonicclue.domain import model as M  # noqa: E402
from sonicclue.domain.units import Quantity  # noqa: E402

SCHEMA_DIR = ROOT / "docs/specs/schemas"
EX_DIR = ROOT / "docs/specs/contracts/examples"
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
SHA = "0" * 63 + "a"


def schemas() -> dict[str, dict]:
    out = {}
    for name, cls in M.CONTRACT_TYPES.items():
        s = cls.model_json_schema(mode="validation")
        s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        s["$id"] = f"https://circuitdriftlabs.example/sonicclue/schemas/{name}-{M.SCHEMA_VERSION}.json"
        out[name] = s
    return out


def valid_examples() -> dict[str, object]:
    ch0 = M.ChannelConfig(index=0, label="mic", sensor_id="mic1", calibration_id="cal-0001", input_gain_db=30.0, agc="off",
                          placement=M.Placement(location="desk, vocal position", position_id="P1", distance_m=0.4, mounting=M.Mounting.STAND))
    ch1 = M.ChannelConfig(index=1, label="desk", sensor_id="ct1", input_gain_db=20.0, agc="off",
                          placement=M.Placement(location="desk top", position_id="C1", mounting=M.Mounting.WAX, orientation="+z normal"))
    sensor = M.SensorDescriptor(id="mic1", kind=M.SensorKind.MEASUREMENT_MIC, model="ECM8000", serial="A123",
                                quantity=Quantity.SOUND_PRESSURE, axis="omni", usable_band_hz=(20.0, 20000.0))
    case = M.Case(id="case-0123456789ab", title="Low hum on vocal recordings", created_utc=T0, updated_utc=T0,
                  problem=M.ProblemDescription(summary="hum at the desk", character=["hum", "tonal"], receiver="vocal mic",
                                               approx_band_hz=(30.0, 400.0)),
                  equipment=[M.Equipment(id="pc", name="Desktop computer", kind="computer")],
                  sensors=[sensor, M.SensorDescriptor(id="ct1", kind=M.SensorKind.CONTACT_PICKUP, quantity=Quantity.RELATIVE)])
    flag = M.QualityFlag(code=M.QualityCode.DROPOUT_GAP, severity=M.Severity.WARNING, message="1 dropout zero-filled",
                         start_frame=480000, end_frame=481024)
    cap = M.CaptureManifest(id="cap-0123456789ab", case_id=case.id, created_utc=T0, source="live",
                            device=M.DeviceInfo(backend="portaudio", host_api="Windows WASAPI", name="USB Audio CODEC", device_index=3),
                            sample_rate_hz=48000.0, channels=[ch0, ch1], frames=960000,
                            chunks=[M.ChunkRef(file="chunk_00000.wav", start_frame=0, frames=480000, sha256=SHA),
                                    M.ChunkRef(file="chunk_00001.wav", start_frame=480000, frames=480000, sha256=SHA)],
                            gaps=[M.Gap(start_frame=480000, end_frame=481024, reason="queue_overflow")], quality=[flag],
                            clock_domain="portaudio:USB Audio CODEC:cap-0123456789ab",
                            context=M.CaptureContext(condition_label="pc off", equipment_state={"pc": "off"},
                                                     procedure_run_id="run-0123456789ab", procedure_step="off", procedure_revision="1"),
                            software_version="0.1.0+dev")
    calp = M.CalibrationProfile(id="cal-0001", sensor_id="mic1", quantity=Quantity.SOUND_PRESSURE, sensitivity_fs_per_unit=0.0213,
                                reference_freq_hz=1000.0, reference_gain_db=30.0,
                                fr_correction=[M.FrPoint(freq_hz=20.0, correction_db=1.5), M.FrPoint(freq_hz=1000.0, correction_db=0.0)],
                                valid_band_hz=(20.0, 20000.0), uncertainty_db=0.45, method="calibrator", source_capture_id=cap.id,
                                created_utc=T0)
    clk = M.ClockMapping(id="clk-0001", reference_capture_id="cap-a", other_capture_id="cap-b", basis="common_event", offset_s=0.0123,
                         drift_ppm=40.3, residual_s=2.2e-6, ambiguity_ratio=0.08, valid_to_s=30.0, eligible_max_freq_hz=24000.0,
                         method="windowed cross-correlation", created_utc=T0)
    tv = M.TaggedValue(status="valid", value=12.3)
    na = M.TaggedValue(status="unavailable", reason="resolution-limited")
    chan = M.ChannelAnalysis(channel=0, label="mic", quantity=Quantity.SOUND_PRESSURE, unit="Pa", calibrated=True,
                             levels=M.LevelSummary(rms=0.02, peak=0.08, crest_db=tv, level_db=60.0, level_ref="dB re 20 uPa", unit="Pa",
                                                   calibrated=True, dc_offset_fs=0.0),
                             noise_floor_db=10.0, peaks=[M.TonalPeak(freq_hz=117.0, level_db=55.0, prominence_db=30.0, rms=0.011, q=na)],
                             families=[M.HarmonicFamily(f0_hz=117.0, orders=[1, 2, 3])],
                             transients=M.TransientSummary(event_count=0, events_per_min=0, median_interval_s=M.TaggedValue(status="unavailable", reason="fewer than two events"),
                                                           periodic=False, max_excess_db=3.0),
                             bands=[M.BandLevel(center_hz=125.89, low_hz=112.2, high_hz=141.25, level_db=56.0, power=0.0002, valid=True)],
                             n_averages=20, nperseg=32768, resolution_hz=1.46, enbw_hz=2.2, excluded_frames=1024)
    an = M.AnalysisResult(id="an-0001", capture_id=cap.id, created_utc=T0, config=M.AnalysisConfig(), algorithm_version="1.0.0", tier=5,
                          channels=[chan], arrays_file="an-0001.npz", software_version="0.1.0+dev")
    cmp_ = M.ComparisonResult(id="cmp-0001", case_id=case.id, kind="state", procedure_run_id="run-0123456789ab", label_a="pc on",
                              label_b="pc off", captures_a=["cap-a"], captures_b=["cap-b"], channel_label="mic", comparable=True,
                              overall_delta_db=-6.2, overall_uncertainty_db=0.6, overall_significant=True, repeatability="measured",
                              band_deltas=[M.BandDelta(center_hz=125.89, delta_db=-15.0, uncertainty_db=0.8, significant=True)],
                              tone_deltas=[M.ToneDelta(freq_hz=117.0, level_a_db=55.0, level_b_db=20.0, delta_db=-35.0, status="disappeared")],
                              changed_equipment={"pc": ["on", "off"]}, algorithm_version="1.0.0", created_utc=T0)
    run = M.ProcedureRun(id="run-0123456789ab", case_id=case.id, procedure_id="equipment_state", revision="1", params={"target": "pc"},
                         state="running", step_index=2, repeat_index=1, captures={"on_1": ["cap-a", "cap-b"]}, started_utc=T0, updated_utc=T0)
    ev = M.EvidenceItem(id="ev-se-0001", kind=M.EvidenceKind.STATE_EFFECT, statement_class=M.StatementClass.CALCULATED,
                        summary="Tone 117.0 Hz fell by 35.0 dB with pc off", params={"subject": "pc", "delta_db": -35.0},
                        sources=["cmp-0001"], freq_hz=117.0)
    hyp = M.Hypothesis(id="H-SRC-pc", category=M.HypothesisCategory.SOURCE, subject="pc", statement="Desktop computer is an excitation source",
                       level=M.SupportLevel.SUPPORTED, supporting=[ev.id], rules=["R-SRC-001@1"], missing_tests=["equipment_state:pc"],
                       explanation=["Switching it off changed the problem in 1 experiment"])
    dx = M.DiagnosisSnapshot(id="dx-0001", case_id=case.id, created_utc=T0, ruleset_version="1.0.0", conclusion="leading_explanation",
                             evidence=[ev], hypotheses=[hyp],
                             next_tests=[M.NextTest(procedure_id="isolation_comparison", title="Isolation comparison", params={"target": "pc"},
                                                    reason="Separates structural vs airborne path", discriminates=["H-STR-pc"], pairs_separated=1,
                                                    difficulty=2, available=True)])
    rep = M.ReportDocument(id="rep-0001", case_id=case.id, report_version=1, created_utc=T0, software_version="0.1.0", ruleset_version="1.0.0",
                           redactions=["serials"], case_digest="f" * 64,
                           sections=[M.ReportSection(key="summary", title="Summary",
                                                     statements=[M.ReportStatement(cls=M.StatementClass.INFERRED, text="One explanation is supported.")])])
    arc = M.ArchiveManifest(case_id=case.id, created_utc=T0, software_version="0.1.0",
                            entries=[M.ArchiveEntry(path="case.db", size=40960, sha256=SHA)])
    from sonicclue import procedures

    return {
        "case": case, "capture_manifest": cap, "calibration_profile": calp, "clock_mapping": clk, "analysis_result": an,
        "comparison_result": cmp_, "procedure_run": run, "diagnosis_snapshot": dx, "report": rep, "archive_manifest": arc,
        "sensor_descriptor": sensor, "channel_config": ch0, "quality_flag": flag, "analysis_config": M.AnalysisConfig(),
        "procedure_definition": procedures.get("equipment_state"), "evidence_item": ev, "hypothesis": hyp,
        "bridge_hello": M.BridgeHello(protocol_version=1, device_model="ADXL345-bridge", firmware_version="0.1.0", sample_rate_hz=1600.0,
                                      axes=3, full_scale_g=4.0),
        "bridge_data": M.BridgeData(seq=17, sample_counter=27200, device_time_us=17000000, axes=3, samples=[[12, -4, 1020], [13, -3, 1019]]),
        "bridge_error": M.BridgeError(code=3, message="FIFO overrun"),
    }


# (name, mutation description, mutate(dict) -> dict, expected keyword, json pointer)
def _del(path):
    def f(d):
        d = copy.deepcopy(d)
        cur = d
        for k in path[:-1]:
            cur = cur[k]
        del cur[path[-1]]
        return d
    return f


def _set(path, val):
    def f(d):
        d = copy.deepcopy(d)
        cur = d
        for k in path[:-1]:
            cur = cur[k]
        cur[path[-1]] = val
        return d
    return f


INVALID = [
    ("case", "missing_title", _del(["title"]), "required", ""),
    ("case", "unknown_field", _set(["colour"], "blue"), "additionalProperties", ""),
    ("case", "newer_schema", _set(["schema_version"], "1.9.0"), "semantic", "/schema_version"),
    ("case", "bad_character_enum", _set(["problem", "character"], ["squeal"]), "enum", "/problem/character/0"),
    ("capture_manifest", "negative_rate", _set(["sample_rate_hz"], -48000), "exclusiveMinimum", "/sample_rate_hz"),
    ("capture_manifest", "bad_sha", _set(["chunks", 0, "sha256"], "xyz"), "pattern", "/chunks/0/sha256"),
    ("capture_manifest", "path_traversal_chunk", _set(["chunks", 0, "file"], "../evil.wav"), "pattern", "/chunks/0/file"),
    ("capture_manifest", "noncontiguous_chunks", _set(["chunks", 1, "start_frame"], 10), "semantic", "/chunks"),
    ("capture_manifest", "bad_source_enum", _set(["source"], "cloud"), "enum", "/source"),
    ("calibration_profile", "zero_sensitivity", _set(["sensitivity_fs_per_unit"], 0), "exclusiveMinimum", "/sensitivity_fs_per_unit"),
    ("calibration_profile", "relative_quantity", _set(["quantity"], "relative"), "semantic", ""),
    ("calibration_profile", "unsorted_fr", _set(["fr_correction"], [{"freq_hz": 1000, "correction_db": 0}, {"freq_hz": 20, "correction_db": 1}]),
     "semantic", "/fr_correction"),
    ("sensor_descriptor", "contact_as_accel", _set(["kind"], "contact_pickup"), "semantic", ""),
    ("sensor_descriptor", "bad_id_pattern", _set(["id"], "mic 1/../x"), "pattern", "/id"),
    ("channel_config", "gain_out_of_range", _set(["input_gain_db"], 500), "anyOf", "/input_gain_db"),  # optional field: anyOf[number<=90, null]
    ("channel_config", "bad_agc", _set(["agc"], "auto"), "enum", "/agc"),
    ("quality_flag", "reversed_range", _set(["end_frame"], 1), "semantic", ""),
    ("analysis_config", "overlap_too_big", _set(["overlap"], 0.99), "exclusiveMaximum", "/overlap"),
    ("clock_mapping", "huge_drift", _set(["drift_ppm"], 9000), "maximum", "/drift_ppm"),
    ("comparison_result", "empty_group", _set(["captures_a"], []), "minItems", "/captures_a"),
    ("procedure_run", "bad_state", _set(["state"], "done"), "enum", "/state"),
    ("hypothesis", "bad_level", _set(["level"], "probable"), "enum", "/level"),
    ("evidence_item", "bad_class", _set(["statement_class"], "proven"), "enum", "/statement_class"),
    ("report", "zero_version", _set(["report_version"], 0), "minimum", "/report_version"),
    ("archive_manifest", "bad_format", _set(["format"], "zip"), "const", "/format"),
    ("bridge_data", "seq_overflow", _set(["seq"], 70000), "maximum", "/seq"),
    ("bridge_hello", "axes_4", _set(["axes"], 4), "maximum", "/axes"),
]


def build(write: bool = True) -> dict[str, str]:
    files: dict[str, str] = {}
    for name, s in schemas().items():
        files[f"schemas/{name}.schema.json"] = json.dumps(s, indent=2, sort_keys=True) + "\n"
    vals = {k: M.dump_dict(v) for k, v in valid_examples().items()}
    for name, d in vals.items():
        files[f"contracts/examples/valid/{name}.json"] = json.dumps(d, indent=2) + "\n"
    for name, tag, fn, kw, ptr in INVALID:
        files[f"contracts/examples/invalid/{name}.{tag}.json"] = json.dumps(fn(vals[name]), indent=2) + "\n"
        files[f"contracts/examples/invalid/{name}.{tag}.expected-error.json"] = json.dumps(
            {"contract": name, "keyword": kw, "path": ptr}, indent=2) + "\n"
    if write:
        base = ROOT / "docs/specs"
        for rel, text in files.items():
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    return files


if __name__ == "__main__":
    if "--check" in sys.argv:
        files = build(write=False)
        stale = [rel for rel, text in files.items() if not (ROOT / "docs/specs" / rel).exists()
                 or (ROOT / "docs/specs" / rel).read_text() != text]
        if stale:
            print("stale or missing:", *stale[:10], sep="\n  ")
            sys.exit(1)
        print(f"{len(files)} contract files up to date")
    else:
        print(f"wrote {len(build())} files")
