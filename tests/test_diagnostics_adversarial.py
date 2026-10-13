"""Adversarial diagnostic cases ADV-001..ADV-010 (docs/specs/09 section 8).

Each case is built from real synthetic signals through the real analysis and
comparison pipeline. Each asserts what the engine must NOT conclude, not
just what it outputs.
"""

import numpy as np
import pytest

from sonicclue.compare.compare import compare
from sonicclue.diagnostics import CaptureView, DiagnosticInputs, diagnose
from sonicclue.domain.model import (
    SUPPORT_ORDER,
    ChannelConfig,
    InterventionRecord,
    Mounting,
    Placement,
    ProcedureRun,
    SupportLevel,
    utcnow,
)
from sonicclue.dsp import signals

from conftest import FS, analyzed_item, mic_contact_case

DUR = 8.0


def tone_scene(fan=True, ac=True, ac_tone=False, seed=1, fan_gain=1.0):
    x = signals.white_noise(1e-3, DUR, FS, seed=seed)
    if fan:
        x += fan_gain * signals.harmonics(117.0, [0.05, 0.02, 0.01], DUR, FS)
    if ac:
        x += signals.band_noise(0.01, 30, 200, DUR, FS, seed=seed + 50)
        if ac_tone:
            x += signals.sine(117.0, 0.03, DUR, FS)  # second source at the same frequency
    return x


def items(n, cid_prefix, **kw):
    gen = kw.pop("gen")
    return [analyzed_item(gen(seed=10 + i), cid=f"{cid_prefix}{i:04d}xx", **kw) for i in range(n)]


def run_dx(case, its, comps, runs=()):
    return diagnose(DiagnosticInputs(case=case, captures=[CaptureView(i.manifest, i.analysis) for i in its],
                                     comparisons=comps, runs=list(runs)))


def H(snap, hid):
    return next((h for h in snap.hypotheses if h.id == hid), None)


def test_baseline_alone_is_inconclusive_shared_tone_no_path():
    """ADV-002: a tone at 117 Hz with two candidate machines, no interventions -> no source is supported."""
    case = mic_contact_case()
    its = items(2, "capbase", gen=lambda seed: tone_scene(seed=seed), state={"pc": "on", "hvac": "on"})
    s = run_dx(case, its, [])
    assert s.conclusion == "inconclusive"
    assert all(SUPPORT_ORDER[h.level] <= 2 for h in s.hypotheses if h.category.value == "source")
    assert any(e.kind.value == "tone" for e in s.evidence)
    assert s.next_tests and s.next_tests[0].procedure_id == "equipment_state"


def test_on_off_supports_correct_source_and_not_the_other():
    case = mic_contact_case()
    on = items(2, "capon", gen=lambda seed: tone_scene(fan=True, seed=seed), state={"pc": "on", "hvac": "on"})
    off = items(2, "capoff", gen=lambda seed: tone_scene(fan=False, seed=seed), state={"pc": "off", "hvac": "on"})
    c = compare("case-test01", on, off, "mic", label_a="pc on", label_b="pc off", kind="state")
    assert c.comparable and any(t.status in ("reduced", "disappeared") for t in c.tone_deltas if abs(t.freq_hz - 117) < 1)
    s = run_dx(case, on + off, [c])
    pc = H(s, "H-SRC-pc")
    assert pc.level in (SupportLevel.SUPPORTED, SupportLevel.STRONG)
    assert H(s, "H-SRC-hvac").level is SupportLevel.UNDETERMINED  # not implicated by pc's test
    assert s.conclusion == "leading_explanation"


def test_adv001_two_sources_residual_creates_additional_source():
    """Two sources at 117 Hz: switching the fan off leaves a residual tone -> additional-source hypothesis."""
    case = mic_contact_case()
    on = items(2, "capon", gen=lambda seed: tone_scene(fan=True, ac_tone=True, seed=seed), state={"pc": "on", "hvac": "on"})
    off = items(2, "capoff", gen=lambda seed: tone_scene(fan=False, ac_tone=True, seed=seed), state={"pc": "off", "hvac": "on"})
    c = compare("case-test01", on, off, "mic", label_a="pc on", label_b="pc off", kind="state")
    s = run_dx(case, on + off, [c])
    add = [h for h in s.hypotheses if h.category.value == "additional_source"]
    assert add and abs(add[0].freq_hz - 117) < 1 and SUPPORT_ORDER[add[0].level] >= 3
    # ADV-010: no contribution shares or percentages are claimed
    assert not any("%" in h.statement for h in s.hypotheses)
    assert any("not estimated" in x for x in add[0].explanation)


def test_adv004_changed_sensor_mount_blocks_comparison():
    case = mic_contact_case()
    on = items(2, "capon", gen=lambda seed: tone_scene(seed=seed), state={"pc": "on"}, mounting=Mounting.STAND)
    off = items(2, "capoff", gen=lambda seed: tone_scene(fan=False, seed=seed), state={"pc": "off"}, mounting=Mounting.HANDHELD)
    c = compare("case-test01", on, off, "mic", kind="state")
    assert not c.comparable and any(i.field == "mounting" for i in c.issues)
    s = run_dx(case, on + off, [c])
    assert H(s, "H-SRC-pc").level is SupportLevel.UNDETERMINED
    assert any(e.kind.value == "not_comparable" for e in s.evidence)
    assert s.conclusion == "inconclusive"


def test_adv005_agc_unknown_blocks_level_comparison():
    case = mic_contact_case()
    on = items(1, "capon", gen=lambda seed: tone_scene(seed=seed), state={"pc": "on"}, agc="unknown")
    off = items(1, "capoff", gen=lambda seed: tone_scene(fan=False, seed=seed), state={"pc": "off"}, agc="unknown")
    c = compare("case-test01", on, off, "mic", kind="state")
    assert not c.comparable and any(i.field == "agc" for i in c.issues)
    s = run_dx(case, on + off, [c])
    assert H(s, "H-SRC-pc").level is SupportLevel.UNDETERMINED


def test_adv008_quieter_due_to_mic_position_not_a_fix():
    """'Fix' recording is 6 dB quieter only because the microphone moved."""
    case = mic_contact_case()
    before = items(2, "capbef", gen=lambda seed: tone_scene(seed=seed), position="P1")
    after = items(2, "capaft", gen=lambda seed: 0.5 * tone_scene(seed=seed), position="P2",
                  intervention=InterventionRecord(description="foam panel", changes_source_output=False,
                                                  changes_transmission_path=True, changes_receiver=False))
    c = compare("case-test01", before, after, "mic", kind="intervention")
    assert c.overall_delta_db < -5
    assert not c.comparable and any(i.field == "position_id" for i in c.issues)
    s = run_dx(case, before + after, [c])
    assert not any(e.kind.value == "intervention_effect" for e in s.evidence)


def test_adv007_fix_changing_source_and_path_is_confounded():
    case = mic_contact_case()
    before = items(2, "capbef", gen=lambda seed: tone_scene(seed=seed))
    after = items(2, "capaft", gen=lambda seed: tone_scene(fan_gain=0.2, seed=seed),
                  intervention=InterventionRecord(description="new quieter fan on rubber mounts", target="pc", changes_source_output=True,
                                                  changes_transmission_path=True, changes_receiver=False))
    c = compare("case-test01", before, after, "mic", kind="intervention")
    assert c.comparable and c.overall_significant
    s = run_dx(case, before + after, [c])
    assert any(e.kind.value == "confounded_intervention" for e in s.evidence)
    assert not any(e.kind.value == "intervention_effect" for e in s.evidence)
    assert H(s, "H-STR-pc") is None or SUPPORT_ORDER[H(s, "H-STR-pc").level] <= 2


def test_adv003_coherence_with_contact_sensor_does_not_establish_structural_path():
    """Contact pickup excited only by airborne sound: coherent with the mic, yet no structural path may be supported."""
    case = mic_contact_case()
    chans = [ChannelConfig(index=0, label="mic", sensor_id="mic1", agc="off", input_gain_db=30, placement=Placement(position_id="P1")),
             ChannelConfig(index=1, label="desk", sensor_id="ct1", agc="off", input_gain_db=20,
                           placement=Placement(position_id="C1", mounting=Mounting.WAX))]

    def scene(fan, seed):
        mic = tone_scene(fan=fan, ac=False, seed=seed)
        contact = 0.3 * mic + signals.white_noise(1e-4, DUR, FS, seed=seed + 7)  # airborne pickup only
        return np.stack([mic, contact], 1)

    on = [analyzed_item(scene(True, 20 + i), cid=f"capon{i:04d}xx", channels=chans, state={"pc": "on"}) for i in range(2)]
    off = [analyzed_item(scene(False, 30 + i), cid=f"capoff{i:04d}xx", channels=chans, state={"pc": "off"}) for i in range(2)]
    cs = [compare("case-test01", on, off, lab, kind="state") for lab in ("mic", "desk")]
    s = run_dx(case, on + off, cs)
    assert any(e.kind.value == "structural_coherence" for e in s.evidence)
    st = H(s, "H-STR-pc")
    assert st is not None and st.level is SupportLevel.UNDETERMINED
    assert any("ADV-003" in x for x in st.explanation)
    assert H(s, "H-SRC-pc").level in (SupportLevel.SUPPORTED, SupportLevel.STRONG)


def test_adv009_insufficient_averaging_makes_cross_channel_ineligible():
    chans = [ChannelConfig(index=0, label="mic", sensor_id="mic1", agc="off"),
             ChannelConfig(index=1, label="desk", sensor_id="ct1", agc="off")]
    x = np.stack([signals.white_noise(0.1, 0.02, FS, seed=1), signals.white_noise(0.1, 0.02, FS, seed=2)], 1)
    it = analyzed_item(x, channels=chans)
    cr = it.analysis.cross[0]
    assert not cr.eligible and cr.coherent_peaks == []
    assert any(q.code.value in ("insufficient_averages", "short_capture") for q in it.analysis.channels[0].quality)


def test_adv006_alias_check_moves_tone():
    case = mic_contact_case()
    run = ProcedureRun(id="run-alias01", case_id="case-test01", procedure_id="alias_check", revision="1", state="completed",
                       step_index=2, repeat_index=0, captures={"rate_a": ["capa0000xx"], "rate_b": ["capb0000xx"]},
                       started_utc=utcnow(), updated_utc=utcnow())

    def ultra(fs, seed):  # 30 kHz tone sampled without anti-alias filter appears at |30000 - fs|
        t = np.arange(int(DUR * fs)) / fs
        return 0.05 * np.sin(2 * np.pi * 30000.0 * t) + signals.white_noise(1e-4, DUR, fs, seed=seed)

    a = analyzed_item(ultra(48000.0, 1), cid="capa0000xx", fs=48000.0, run="run-alias01")
    b = analyzed_item(ultra(44100.0, 2), cid="capb0000xx", fs=44100.0, run="run-alias01")
    assert any(abs(p.freq_hz - 18000) < 2 for p in a.analysis.channels[0].peaks)
    s = run_dx(case, [a, b], [], [run])
    ev = [e for e in s.evidence if e.kind.value == "alias_test"]
    assert ev and any(e.params["moves"] for e in ev)
    assert H(s, "H-ART-alias").level is SupportLevel.SUPPORTED


def test_chain_noise_test_separates_recording_chain_from_acoustic_hum():
    case = mic_contact_case()

    def hum(seed):
        return signals.harmonics(50.0, [0.01, 0.004, 0.003], DUR, FS) + signals.white_noise(1e-4, DUR, FS, seed=seed)

    run = ProcedureRun(id="run-hum001", case_id="case-test01", procedure_id="electrical_hum", revision="1", state="completed",
                       step_index=3, repeat_index=0, captures={"normal": ["capn0000xx"], "terminated": ["capt0000xx"]},
                       started_utc=utcnow(), updated_utc=utcnow())
    a = analyzed_item(hum(1), cid="capn0000xx", run="run-hum001")
    b = analyzed_item(hum(2), cid="capt0000xx", run="run-hum001")  # hum persists without mic -> chain
    s = run_dx(case, [a, b], [], [run])
    chn = [h for h in s.hypotheses if h.category.value == "recording_chain"]
    hum_h = [h for h in s.hypotheses if h.category.value == "electrical_hum"]
    assert chn and chn[0].level is SupportLevel.SUPPORTED
    assert hum_h and hum_h[0].level is SupportLevel.WEAKENED
    # counterexample: hum absent without mic -> chain contradicted
    b2 = analyzed_item(signals.white_noise(1e-4, DUR, FS, seed=3), cid="capt0000xx", run="run-hum001")
    s2 = run_dx(case, [a, b2], [], [run])
    assert [h for h in s2.hypotheses if h.category.value == "recording_chain"][0].level is SupportLevel.CONTRADICTED


def test_unstable_conditions_invalidate_run_evidence():
    """ABA: the two 'on' groups differ although nothing changed -> state evidence from that run is not used."""
    case = mic_contact_case()
    on1 = items(2, "capona", gen=lambda seed: tone_scene(seed=seed), state={"pc": "on"}, run="run-x00001")
    on2 = items(2, "caponb", gen=lambda seed: 2.0 * tone_scene(seed=seed), state={"pc": "on"}, run="run-x00001")
    off = items(2, "capoff", gen=lambda seed: tone_scene(fan=False, seed=seed), state={"pc": "off"}, run="run-x00001")
    c = compare("case-test01", on1 + on2, off, "mic", kind="state", run_id="run-x00001")
    stab = compare("case-test01", on1, on2, "mic", kind="generic", run_id="run-x00001")
    assert stab.overall_significant
    s = run_dx(case, on1 + on2 + off, [c, stab])
    assert H(s, "H-SRC-pc").level is SupportLevel.UNDETERMINED
    assert any(e.params.get("code") == "unstable" for e in s.evidence if e.kind.value == "measurement_quality")


def test_clipped_capture_yields_measurement_artifact_hypothesis():
    case = mic_contact_case()
    it = analyzed_item(signals.clip(signals.sine(117.0, 2.0, DUR, FS)), cid="capclip0xx")
    s = run_dx(case, [it], [])
    art = H(s, "H-ART-quality")
    assert art is not None and "clipping" in art.statement
    assert s.conclusion == "inconclusive"


def test_snapshot_is_deterministic():
    case = mic_contact_case()
    on = items(2, "capon", gen=lambda seed: tone_scene(seed=seed), state={"pc": "on"})
    off = items(2, "capoff", gen=lambda seed: tone_scene(fan=False, seed=seed), state={"pc": "off"})
    c = compare("case-test01", on, off, "mic", kind="state")
    a, b = run_dx(case, on + off, [c]), run_dx(case, on + off, [c])
    assert [(h.id, h.level) for h in a.hypotheses] == [(h.id, h.level) for h in b.hypotheses]
    assert [e.id for e in a.evidence] == [e.id for e in b.evidence]


_ = pytest
