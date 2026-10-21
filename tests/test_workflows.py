"""Procedures (SM-003), stimulus safety (SM-004), reporting, and the CLI end-to-end workflow."""

import json
import threading
import time
import zipfile

import numpy as np
import pytest

from sonicclue import procedures
from sonicclue.acquisition.backends import SimulatedBackend
from sonicclue.domain.errors import SafetyError, StateError, ValidationError
from sonicclue.domain.model import (
    CaptureContext,
    ChannelConfig,
    Equipment,
    InterventionRecord,
    Mounting,
    Placement,
    ProblemDescription,
    SensorDescriptor,
    SensorKind,
    StimulusRecord,
)
from sonicclue.domain.units import Quantity
from sonicclue.stimulus import ABSOLUTE_MAX_DBFS, OutputController, generate


# ---------------------------------------------------------------- procedures


def test_library_valid_and_placeholders_resolve():
    lib = procedures.library()
    assert len(lib) == 15
    for d in lib.values():
        params = {p: "X" for p in d.parameters}
        for i in range(len(d.steps)):
            s = procedures.resolved_step(d, i, params)
            assert "{" not in s.instruction + s.title + s.condition_label + "".join(s.equipment_state), (d.id, s.id)
        assert d.success and d.purpose


def test_state_machine_transitions_and_invalid_events():
    d = procedures.get("isolation_comparison")
    with pytest.raises(ValidationError):
        procedures.start("c", d, {})
    r = procedures.start("c", d, {"target": "pc"})
    with pytest.raises(StateError):
        procedures.acknowledge(r)  # first step is a capture
    r = procedures.record_capture(r, "cap1", accepted=False)
    assert r.captures == {"before__rejected": ["cap1"]} and r.repeat_index == 0
    r = procedures.record_capture(r, "cap2", accepted=True)
    r = procedures.record_capture(r, "cap3", accepted=True)
    assert procedures.current(r)[0].kind == "intervention"
    r = procedures.pause(r)
    with pytest.raises(StateError):
        procedures.record_intervention(r, InterventionRecord(description="pads"))
    r = procedures.resume(r)
    r = procedures.record_intervention(r, InterventionRecord(description="pads", changes_transmission_path=True))
    r = procedures.record_capture(r, "cap4", True)
    r = procedures.record_capture(r, "cap5", True)
    assert r.state == "completed"
    for fn in (procedures.pause, procedures.cancel, procedures.resume):
        with pytest.raises(StateError):
            fn(r)


def _sim_case(app):
    app.create_case("p", ProblemDescription(summary="hum"), [Equipment(id="pc", name="PC", kind="computer"),
                                                             Equipment(id="hvac", name="AC", kind="hvac")],
                    [SensorDescriptor(id="mic1", kind=SensorKind.STUDIO_MIC, quantity=Quantity.SOUND_PRESSURE)])
    from sonicclue.app.service import CaptureSpec

    return CaptureSpec(channels=[ChannelConfig(index=0, label="mic", sensor_id="mic1", agc="off", input_gain_db=30,
                                               placement=Placement(position_id="P1", mounting=Mounting.STAND))],
                       duration_s=3.0, backend="simulated", device=0, context=CaptureContext(equipment_state={"pc": "on", "hvac": "on"}))


def test_gates_reject_clipping_then_accept_and_persist(app):
    base = _sim_case(app)
    run = app.start_procedure("baseline")
    run = app.procedure_action(run.id, "ack")
    orig = app.sim.world.render
    app.sim.world.render = lambda fs, ch, n, start: np.clip(orig(fs, ch, n, start) * 500, -1, 1).astype(np.float32)
    run, m, failed = app.run_step_capture(run.id, base)
    assert failed and "clipping" in failed[0] and run.step_index == 1 and run.repeat_index == 0
    app.sim.world.render = orig
    run, m, failed = app.run_step_capture(run.id, base)
    assert not failed and run.repeat_index == 1
    # persistence: reopen the case and resume where we were
    cid = app.case().id
    app.close_case()
    app.open_case(cid)
    run = app.run(run.id)
    assert run.state == "running" and run.repeat_index == 1 and len(run.captures["baseline__rejected"]) == 1
    run, m, failed = app.run_step_capture(run.id, base)
    assert run.state == "completed"


def test_comparable_gate_rejects_moved_sensor(app):
    base = _sim_case(app)
    run = app.start_procedure("equipment_state", {"target": "pc"})
    run, _, f = app.run_step_capture(run.id, base)
    assert not f
    moved = base.channels[0].model_copy(update={"placement": Placement(position_id="P3", mounting=Mounting.STAND)})
    run, _, f = app.run_step_capture(run.id, base)
    run = app.procedure_action(run.id, "ack")
    from sonicclue.app.service import CaptureSpec

    run, _, f = app.run_step_capture(run.id, CaptureSpec(**{**base.__dict__, "channels": [moved]}))
    assert f and "not comparable" in f[0]


def test_stimulus_step_requires_armed_output(app):
    base = _sim_case(app)
    app.add_equipment(Equipment(id="spk", name="Monitor", kind="speaker"))
    run = app.start_procedure("speaker_buzz", {"target": "spk"})
    run = app.procedure_action(run.id, "ack")
    with pytest.raises(StateError):
        app.run_step_capture(run.id, base)
    app.arm_output(0, backend="simulated", level_limit_dbfs=-12, max_duration_s=30, confirmed=True)
    run, m, f = app.run_step_capture(run.id, base)
    assert m.stimulus is not None and m.stimulus.level_dbfs == -18 and m.stimulus.kind == "sweep"
    assert app.output.state.value == "disarmed"  # one-shot: disarmed after the step


# ---------------------------------------------------------------- stimulus safety


def test_output_never_plays_without_arming_and_confirmation():
    oc = OutputController(SimulatedBackend())
    with pytest.raises(SafetyError):
        oc.play(StimulusRecord(kind="sine", level_dbfs=-20), 1)
    with pytest.raises(SafetyError):
        oc.arm(0, 48000, confirmed=False)
    assert oc.state.value == "disarmed"


def test_level_and_duration_limits_and_one_shot():
    be = SimulatedBackend()
    oc = OutputController(be)
    oc.arm(0, 48000, level_limit_dbfs=0.0, max_duration_s=1.0, confirmed=True)
    eff = oc.play(StimulusRecord(kind="sine", level_dbfs=0.0, params={"freq": 440}), 10)
    assert eff.level_dbfs == ABSOLUTE_MAX_DBFS
    assert oc.wait(5)
    assert oc.state.value == "disarmed"
    rendered = np.concatenate(be.last_output.rendered)
    assert np.max(np.abs(rendered)) <= 10 ** (ABSOLUTE_MAX_DBFS / 20) + 1e-6
    with pytest.raises(SafetyError):
        oc.play(StimulusRecord(kind="sine", level_dbfs=-20), 1)  # one-shot: must re-arm


def test_arm_expiry_feedback_guard_and_stop():
    oc = OutputController(SimulatedBackend(), arm_timeout_s=0.1)
    with pytest.raises(SafetyError):
        oc.arm(0, 48000, confirmed=True, active_input_device=0)
    oc.arm(0, 48000, confirmed=True)
    time.sleep(0.2)
    with pytest.raises(SafetyError, match="expired"):
        oc.play(StimulusRecord(kind="sine", level_dbfs=-20), 1)
    oc2 = OutputController(SimulatedBackend())
    oc2.arm(0, 48000, confirmed=True, max_duration_s=30)
    oc2.play(StimulusRecord(kind="pink", level_dbfs=-30), 30)
    oc2.stop()
    assert oc2.state.value == "disarmed"
    oc2.stop()  # idempotent


def test_generated_signals_have_fades_and_peak_level():
    for k in ("sine", "sweep", "white", "pink", "band_noise", "impulse"):
        x = generate(StimulusRecord(kind=k, level_dbfs=-20, params={"freq": 1000, "f0": 100, "f1": 5000}), 48000, 1.0)
        assert abs(x[0]) < 1e-3 and abs(x[-1]) < 1e-3
        assert np.max(np.abs(x)) <= 10 ** (-20 / 20) + 1e-6


def test_audition_does_not_modify_data():
    oc = OutputController(SimulatedBackend())
    data = np.linspace(-0.5, 0.5, 48000).astype(np.float32)
    ref = data.copy()
    oc.arm(0, 48000, confirmed=True, level_limit_dbfs=-30)
    oc.audition(data, 48000)
    oc.stop()
    np.testing.assert_array_equal(data, ref)


# ---------------------------------------------------------------- reports + demo + CLI


@pytest.fixture(scope="module")
def demo_ws(tmp_path_factory):
    from sonicclue.app.demo import run_demo
    from sonicclue.app.service import SonicClueApp

    ws = tmp_path_factory.mktemp("demo")
    app = SonicClueApp(ws, sim_speed=60)
    cid = run_demo(app, progress=lambda m: None, duration_scale=0.4)
    app.shutdown()
    return ws, cid


def test_demo_diagnosis_matches_simulated_ground_truth(demo_ws):
    from sonicclue.app.service import SonicClueApp

    ws, cid = demo_ws
    app = SonicClueApp(ws)
    app.open_case(cid)
    try:
        _check_demo(app)
    finally:
        app.shutdown()


def _check_demo(app):
    s = app.latest_diagnosis()
    lv = {h.id: h.level.value for h in s.hypotheses}
    # ground truth of SimWorld: pc fan is a tonal source with a structural path; hvac adds broadband rumble
    assert lv["H-SRC-pc"] == "strongly_supported"
    assert lv["H-STR-pc"] == "strongly_supported"  # airborne control + isolation both support it
    assert lv["H-SRC-hvac"] in ("supported", "strongly_supported")
    assert lv.get("H-STR-hvac", "undetermined") == "undetermined"  # fan-tone evidence must not transfer to the AC
    assert s.conclusion == "multiple_explanations"
    assert app.verify_case() == []


def test_reports_all_formats_classes_and_redaction(demo_ws, tmp_path):
    from sonicclue.app.service import SonicClueApp

    ws, cid = demo_ws
    app = SonicClueApp(ws)
    app.open_case(cid)
    html = app.export_report("html", tmp_path / "r.html").read_text()
    for tag in ("MEASURED", "CALCULATED", "INFERRED", "USER", "UNRESOLVED", "SIMULATED"):
        assert tag in html
    assert "<img" in html
    pdf = app.export_report("pdf", tmp_path / "r.pdf").read_bytes()
    assert pdf[:4] == b"%PDF" and len(pdf) > 20000
    j = json.loads(app.export_report("json", tmp_path / "r.json").read_text())
    assert j["schema_version"] == "1.0.0" and j["report_version"] >= 3
    assert {s["key"] for s in j["sections"]} >= {"summary", "evidence", "hypotheses", "comparisons", "limitations", "reproduction"}
    with zipfile.ZipFile(app.export_report("csv", tmp_path / "r.zip")) as z:
        names = z.namelist()
    assert "statements.csv" in names and any(n.startswith("psd_") for n in names)
    red = app.export_report("html", tmp_path / "red.html", redact=("names", "locations")).read_text()
    assert "Desktop computer" not in red.split("Candidate equipment")[1].split("</table>")[0]
    assert "vocal position" not in red and "[redacted]" in red
    app.shutdown()


def test_cli_end_to_end(tmp_path, capsys):
    from sonicclue.cli.main import main

    ws = str(tmp_path / "w")
    assert main(["--workspace", ws, "selftest"]) == 0
    assert main(["--workspace", ws, "--json", "case", "new", "--title", "cli", "--equipment", "pc=PC:computer",
                 "--sensor", "mic1=studio_mic"]) == 0
    cid = json.loads(capsys.readouterr().out.strip().splitlines()[-1] if False else capsys.readouterr().out or "{}").get("case_id") \
        if False else None
    from sonicclue.storage.store import Workspace

    cid = Workspace(tmp_path / "w").list_cases()[0]["id"]
    common = ["--workspace", ws, "--sim-speed", "60"]
    dev = ["--backend", "simulated", "--device", "0", "--duration", "3", "--ch", "0:mic:mic1:P1:stand:30:off"]
    assert main(common + ["procedure", "start", "--case", cid, "--procedure", "equipment_state", "--param", "target=pc"]) == 0
    for _ in range(7):
        assert main(common + ["procedure", "step", "--case", cid] + dev) == 0
    out = capsys.readouterr().out
    assert "completed" in out
    assert main(common + ["diagnose", "--case", cid, "-v"]) == 0
    out = capsys.readouterr().out
    assert "PC is an excitation source" in out
    assert main(common + ["report", "--case", cid, "--format", "json", "--out", str(tmp_path / "x.json")]) == 0
    assert main(common + ["archive", "export", str(tmp_path / "a.scarchive"), "--case", cid]) == 0
    assert main(["--workspace", str(tmp_path / "w2"), "archive", "import", str(tmp_path / "a.scarchive")]) == 0
    assert main(common + ["case", "verify", "--case", cid]) == 0
    # error paths: exit codes
    assert main(common + ["capture", "--case", cid, "--backend", "simulated", "--device", "7", "--duration", "1"]) == 1
    assert main(common + ["case", "show", "--case", "nope"]) == 2
    assert main(common + ["stimulus", "--backend", "simulated", "--device", "0"]) == 1  # missing --confirm


_ = (SensorDescriptor, json)


def test_align_two_independent_devices_via_import(app, tmp_path):
    import soundfile as sf

    from sonicclue.dsp import signals

    app.create_case("align")
    common = signals.white_noise(0.05, 20, 48000, seed=5) + signals.sine(117, 0.05, 20, 48000)
    a = common + signals.white_noise(0.01, 20, 48000, seed=6)
    b = signals.drifted(signals.delay(common, 0.0042, 48000), 25.0) + signals.white_noise(0.01, 20.0005, 48000, seed=7)[: int(20 * 48000 * (1 + 25e-6))]
    sf.write(tmp_path / "a.wav", a.astype("float32"), 48000, subtype="FLOAT")
    sf.write(tmp_path / "b.wav", b.astype("float32"), 48000, subtype="FLOAT")
    ma, mb = app.import_audio(tmp_path / "a.wav"), app.import_audio(tmp_path / "b.wav")
    r = app.align_captures(ma.id, mb.id, "ch1", "ch1")
    m = r["mapping"]
    assert abs(m.offset_s - 0.0042) < 3 * m.residual_s + 1 / 48000
    assert abs(m.drift_ppm - 25.0) < 3.0
    assert m.eligible_max_freq_hz > 1000
    assert any(abs(f - 117) < 2 for f, _ in r["coherent"])
    assert app.store.list("clock_mapping")[0].id == m.id
    html = app.export_report("html", tmp_path / "r.html").read_text()
    assert "Clock mapping" in html and "drift" in html
    # counterexample: unrelated recordings cannot be aligned
    sf.write(tmp_path / "c.wav", signals.white_noise(0.05, 20, 48000, seed=99).astype("float32"), 48000, subtype="FLOAT")
    mc = app.import_audio(tmp_path / "c.wav")
    r2 = app.align_captures(ma.id, mc.id, "ch1", "ch1")
    assert r2["mapping"].eligible_max_freq_hz == 0.0 and not r2["coherent"]


def test_annotations_reach_report_as_user_assertions(app, tmp_path):
    app.create_case("notes")
    a = app.annotate("case", "The hum started after the new fridge was installed")
    assert a.id.startswith("note-")
    import json as _j

    doc = _j.loads(app.export_report("json", tmp_path / "r.json").read_text())
    st = [s for sec in doc["sections"] if sec["key"] == "problem" for s in sec["statements"]]
    assert any(s["cls"] == "user_asserted" and "fridge" in s["text"] for s in st)
    red = app.export_report("html", tmp_path / "r.html", redact=("notes",)).read_text()
    assert "fridge" not in red


def test_cli_history_and_info(tmp_path, capsys):
    from sonicclue.cli.main import main
    from sonicclue.storage.store import Workspace

    ws = str(tmp_path / "w")
    assert main(["--workspace", ws, "case", "new", "--title", "h"]) == 0
    cid = Workspace(tmp_path / "w").list_cases()[0]["id"]
    assert main(["--workspace", ws, "case", "history", "--case", cid]) == 0
    assert "case.create" in capsys.readouterr().out
    assert main(["--workspace", ws, "--json", "info"]) == 0
    assert '"sonicclue"' in capsys.readouterr().out


# ---------------------------------------------------------------- audit regressions


def test_redaction_covers_device_names_and_evidence_text(demo_ws, tmp_path):
    from sonicclue.app.service import SonicClueApp

    ws, cid = demo_ws
    app = SonicClueApp(ws)
    app.open_case(cid)
    plain = app.export_report("html", tmp_path / "p.html").read_text()
    red = app.export_report("html", tmp_path / "r.html", redact=("names",)).read_text()
    dev = app.captures()[0].device.name
    assert dev in plain and dev not in red
    ev = app.latest_diagnosis().evidence[0].summary
    assert ev in plain.replace("&amp;", "&") or ev[:20] in plain
    assert ev[:30] not in red
    app.shutdown()


def test_compare_refuses_missing_spectra():
    from conftest import analyzed_item
    from sonicclue.compare.compare import compare
    from sonicclue.domain.errors import AnalysisError

    rng = np.random.default_rng(1)
    a = analyzed_item(0.01 * rng.standard_normal(48000 * 20).astype(np.float32), cid="cap-aaaaaa")
    b = analyzed_item(0.01 * rng.standard_normal(48000 * 20).astype(np.float32), cid="cap-bbbbbb")
    a.arrays.clear()
    with pytest.raises(AnalysisError, match="no stored spectra"):
        compare("case-test01", [a], [b], "mic")


def test_failed_import_leaves_no_capture_dir(app, tmp_path):
    cid = app.create_case("imp")
    app.open_case(cid)
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    before = set((app._s().path / "captures").iterdir())
    with pytest.raises(Exception):
        app.import_audio(bad)
    assert set((app._s().path / "captures").iterdir()) == before


def test_close_case_cancels_and_waits_for_jobs(app):
    cid = app.create_case("jobs")
    app.open_case(cid)
    started = threading.Event()
    seen = {}

    def job(cancel):
        started.set()
        while not cancel():
            time.sleep(0.01)
        seen["cancelled"] = True

    fut, _ = app.jobs.submit(job)
    assert started.wait(2)
    app.close_case()
    assert fut.done() and seen.get("cancelled")
    app.open_case(cid)  # pool still usable afterwards
    assert app.jobs.submit(lambda cancel: 7)[0].result(2) == 7


def test_output_finish_spawns_one_mute_thread():
    be = SimulatedBackend()
    oc = OutputController(be)
    oc.arm(0, 48000, confirmed=True)
    oc.play(StimulusRecord(kind="sine", level_dbfs=-30, params={"freq": 440}), 0.2)
    assert oc.wait(5)
    assert oc.state.value == "disarmed" and oc.last_error is None
