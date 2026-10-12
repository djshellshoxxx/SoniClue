"""Calibration (INV-006), capabilities and synchronization tests."""

import math

import numpy as np
import pytest

from sonicclue.analysis.pipeline import analyze
from sonicclue.domain.errors import CalibrationError
from sonicclue.domain.model import ChannelConfig, FrPoint, SensorDescriptor, SensorKind, utcnow
from sonicclue.domain.units import Quantity, spl_db_to_pa
from sonicclue.dsp import signals
from sonicclue.sensors import calibration as cal
from sonicclue.sensors.capabilities import capabilities
from sonicclue.sync import align, check_timestamps, estimate_mapping

from conftest import FS, make_manifest

MIC = SensorDescriptor(id="mic1", kind=SensorKind.MEASUREMENT_MIC, quantity=Quantity.SOUND_PRESSURE)
CONTACT = SensorDescriptor(id="ct1", kind=SensorKind.CONTACT_PICKUP, quantity=Quantity.RELATIVE)


def _calibrator(sens=0.02, level=94.0, f=1000.0, dur=6.0, noise=1e-5, wobble=0.0):
    pa = spl_db_to_pa(level)
    x = signals.sine(f, pa * math.sqrt(2) * sens, dur, FS)
    if wobble:
        x *= 1 + wobble * np.sin(2 * np.pi * 0.2 * signals.time_axis(dur, FS))
    return x + signals.white_noise(noise, dur, FS, seed=3)


def test_calibrate_from_94db_recovers_sensitivity():
    p = cal.calibrate_from_tone(_calibrator(0.02), FS, MIC, 94.0, 1000.0, gain_db=30.0)
    assert p.sensitivity_fs_per_unit == pytest.approx(0.02, rel=0.002)
    assert p.reference_gain_db == 30.0 and p.method == "calibrator"
    assert 0.39 < p.uncertainty_db < 0.6


@pytest.mark.parametrize("kw,code", [({"noise": 0.05}, "SC_CAL_LOW_SNR"), ({"f": 250.0}, "SC_CAL_NO_TONE"),
                                     ({"wobble": 0.2}, "SC_CAL_UNSTABLE"), ({"dur": 1.0}, "SC_CAL_SHORT")])
def test_calibration_rejections(kw, code):
    with pytest.raises(CalibrationError) as e:
        cal.calibrate_from_tone(_calibrator(**kw), FS, MIC, 94.0, 1000.0, gain_db=0)
    assert e.value.code == code


def test_contact_pickup_cannot_be_calibrated():
    with pytest.raises(CalibrationError):
        cal.calibrate_from_tone(_calibrator(), FS, CONTACT, 94.0, 1000.0, gain_db=0)
    with pytest.raises(ValueError):
        SensorDescriptor(id="x", kind=SensorKind.CONTACT_PICKUP, quantity=Quantity.ACCELERATION)


def test_inv006_calibration_direction_end_to_end():
    """A 1 Pa (94 dB) tone through sensitivity 0.02 FS/Pa must read 94 dB SPL, not 94 +/- 2*34 dB."""
    prof = cal.calibrate_from_tone(_calibrator(0.02), FS, MIC, 94.0, 1000.0, gain_db=30.0)
    x = _calibrator(0.02, level=80.0, dur=10)
    ch = ChannelConfig(index=0, label="mic", sensor_id="mic1", calibration_id=prof.id, input_gain_db=30.0, agc="off")
    m = make_manifest(len(x), [ch])
    res = analyze(m, x[:, None].astype(np.float32), {"mic1": MIC}, {prof.id: prof}).result
    pk = res.channels[0].peaks[0]
    assert res.channels[0].calibrated and res.channels[0].levels.level_ref == "dB re 20 uPa"
    assert pk.level_db == pytest.approx(80.0, abs=0.1)
    assert res.tier == 5
    # counterexample: wrong gain -> calibration refused, relative levels
    ch2 = ch.model_copy(update={"input_gain_db": 36.0})
    res2 = analyze(m.model_copy(update={"channels": [ch2]}), x[:, None].astype(np.float32), {"mic1": MIC}, {prof.id: prof}).result
    assert not res2.channels[0].calibrated
    assert any(q.code.value == "cal_gain_mismatch" and q.severity.value == "invalid" for q in res2.channels[0].quality)


def test_fr_file_direction_response_is_negated():
    text = "* Sens Factor =-1.2dB\n20 -3.0\n1000 0.0\n10000 +2.0\n"
    pts, sens = cal.parse_fr_file(text, "response")
    assert sens == pytest.approx(-1.2)
    assert [p.correction_db for p in pts] == [3.0, -0.0, -2.0]
    pts2, _ = cal.parse_fr_file(text, "correction")
    assert pts2[2].correction_db == 2.0
    with pytest.raises(CalibrationError):
        cal.parse_fr_file("20 abc\n", "response")


def test_fr_correction_applied_and_out_of_band_nan():
    prof = cal.profile_from_datasheet(MIC, 0.01, 1.0, gain_db=0, fr_points=[FrPoint(freq_hz=100, correction_db=6.0),
                                                                            FrPoint(freq_hz=1000, correction_db=0.0)],
                                      valid_band_hz=(50, 5000))
    c = cal.fr_correction_db(prof, np.array([20.0, 100.0, 316.2278, 1000.0, 3000.0, 8000.0]))
    assert np.isnan(c[0]) and np.isnan(c[-1])
    assert c[1] == pytest.approx(6.0) and c[2] == pytest.approx(3.0, abs=0.01) and c[4] == 0.0


def test_calibration_expiry_and_sensor_mismatch():
    from datetime import timedelta

    prof = cal.profile_from_datasheet(MIC, 0.01, 1.0, gain_db=0)
    old = prof.model_copy(update={"expires_utc": utcnow() - timedelta(days=1)})
    ch = ChannelConfig(index=0, label="m", sensor_id="mic1", input_gain_db=0)
    assert not cal.evaluate(old, ch, MIC).usable
    ch2 = ch.model_copy(update={"sensor_id": "other"})
    assert not cal.evaluate(prof, ch2, MIC).usable
    assert cal.evaluate(prof, ch, MIC).usable


def test_capability_tiers():
    s = {"mic1": MIC, "ct1": CONTACT,
         "acc": SensorDescriptor(id="acc", kind=SensorKind.MEMS_ACCELEROMETER, quantity=Quantity.ACCELERATION)}
    one = [ChannelConfig(index=0, label="m", sensor_id="mic1")]
    two = one + [ChannelConfig(index=1, label="c", sensor_id="ct1")]
    assert capabilities(one, s, set()).tier == 1
    assert capabilities(two, s, set(), shared_clock=False).tier == 2
    assert capabilities(two, s, set()).tier == 4
    acc = [ChannelConfig(index=0, label="a", sensor_id="acc")]
    assert capabilities(acc, s, set()).tier == 3
    assert capabilities(one, s, {0}).tier == 5
    c = capabilities(two, s, set(), shared_clock=False)
    assert not c.synchronized_cross_channel and not c.vibration_physical


# ---------------------------------------------------------------- synchronization


def test_sync_offset_and_drift_recovered():
    ref = signals.white_noise(0.1, 30, FS, seed=1)
    other = signals.drifted(signals.delay(ref, 0.0123, FS), 40.0)  # 12.3 ms late, clock 40 ppm fast
    m, flags, o = estimate_mapping(ref, FS, other, FS, ref_id="a", other_id="b")
    # the error must lie within the uncertainty the mapping itself reports (honest sigma)
    assert abs(m.offset_s - 0.0123) <= 3 * m.residual_s + 1 / FS
    assert m.drift_ppm == pytest.approx(40.0, abs=3.0)
    assert m.eligible_max_freq_hz > 1000
    al, valid = align(o, m, FS, len(ref))
    k = slice(int(5 * FS), int(25 * FS))
    assert np.corrcoef(al[k], ref[k])[0, 1] > 0.95
    assert not valid[:10].any()


def test_sync_periodic_signal_is_ambiguous():
    ref = signals.sine(100.0, 0.5, 20, FS)
    other = signals.delay(ref, 0.003, FS)
    m, flags, _ = estimate_mapping(ref, FS, other, FS, ref_id="a", other_id="b")
    assert m.eligible_max_freq_hz == 0.0
    assert any(f.code.value == "sync_ambiguous" for f in flags)


def test_sync_clock_reset_detected():
    ref = signals.white_noise(0.1, 30, FS, seed=2)
    a = signals.delay(ref, 0.01, FS)
    b = signals.delay(ref, 0.2, FS)
    other = np.concatenate([a[: int(20 * FS)], b[int(20 * FS):]])  # timing jump at 20 s
    m, flags, _ = estimate_mapping(ref, FS, other, FS, ref_id="a", other_id="b", windows=8)
    assert m.eligible_max_freq_hz == 0.0
    assert any(f.code.value == "clock_reset" for f in flags)


def test_sync_mismatched_rates_resampled():
    ref = signals.white_noise(0.1, 20, 48000, seed=4)
    from sonicclue.dsp.resample import resample_rational

    other, _, _ = resample_rational(signals.delay(ref, 0.005, 48000), 48000, 44100)
    m, flags, o = estimate_mapping(ref, 48000, other, 44100, ref_id="a", other_id="b")
    assert any(f.code.value == "mismatched_rate" for f in flags)
    assert m.offset_s == pytest.approx(0.005, abs=1e-4)


def test_timestamp_checks():
    t = np.arange(100) * 0.01
    assert check_timestamps(t, 0.01) == []
    t2 = t.copy()
    t2[50:] -= 0.3
    assert any(f.code.value == "clock_reset" for f in check_timestamps(t2, 0.01))
    t3 = t.copy()
    t3[40] += 0.004
    assert any(f.code.value == "nonuniform_timestamps" for f in check_timestamps(t3, 0.01))
