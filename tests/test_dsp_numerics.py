"""Numerical invariant tests (docs/specs/08 + numerical invariant catalog INV-001..INV-011).

References are independent of the code under test: closed-form results,
direct DFT summation, or explicit loops. Never the same scipy call.
"""

import math

import numpy as np
import pytest

from sonicclue.domain import units
from sonicclue.domain.units import Quantity
from sonicclue.dsp import cross, levels, signals, spectral, stats, tonal, transient
from sonicclue.dsp.resample import resample_rational

FS = 48000.0


def _plan(n, res=1.0, overlap=0.5, mina=8, fs=FS):
    return spectral.plan_segments(np.ones(n, bool), fs, res, overlap, mina)


# INV-001 units & dB references
def test_inv001_db_references_and_roundtrip():
    assert units.amplitude_db(20e-6, Quantity.SOUND_PRESSURE) == pytest.approx(0.0)
    assert units.amplitude_db(1.0, Quantity.SOUND_PRESSURE) == pytest.approx(93.979, abs=1e-3)
    assert units.spl_db_to_pa(94.0) == pytest.approx(1.00237, rel=1e-4)
    for q in Quantity:
        p = units.db_to_power(57.3, q)
        assert units.power_db(p, q) == pytest.approx(57.3)
    assert units.amplitude_db(0.0, Quantity.RELATIVE) == units.DB_FLOOR  # EDGE-001 silence -> floor, not -inf


# INV-002 RMS of sine, INV-003 Parseval with density PSD
@pytest.mark.parametrize("window", ["hann", "hamming", "blackmanharris", "flattop", "boxcar"])
def test_inv003_parseval_white_noise(window):
    x = signals.white_noise(0.1, 20.0, FS, seed=1)
    plan = _plan(len(x))
    f, p = spectral.masked_welch(x, FS, plan, window)
    df = f[1] - f[0]
    assert np.sum(p) * df == pytest.approx(np.var(x), rel=0.02)


def test_inv002_sine_rms():
    x = signals.sine(1000, 0.5, 2.0, FS)
    rms, peak, dc = levels.level_stats(x, np.ones(len(x), bool))
    assert rms == pytest.approx(0.5 / math.sqrt(2), rel=1e-6)
    assert peak == pytest.approx(0.5, rel=1e-4)
    assert abs(dc) < 1e-9


# INV-003b one-sided treatment: DC and Nyquist are not doubled (independent DFT reference)
def test_inv003_one_sided_dc_nyquist_against_direct_dft():
    n = 64
    rng = np.random.default_rng(3)
    x = rng.standard_normal(n) + 0.7
    w = np.ones(n)
    # direct DFT, single segment, boxcar, no detrend
    k = np.arange(n)
    X = np.array([np.sum(x * w * np.exp(-2j * np.pi * m * k / n)) for m in range(n // 2 + 1)])
    ref = np.abs(X) ** 2 / (FS * np.sum(w**2))
    ref[1:-1] *= 2
    from scipy import signal as sps  # only to read the implementation result with identical params
    f, p = sps.welch(x, fs=FS, window="boxcar", nperseg=n, noverlap=0, detrend=False, scaling="density")
    np.testing.assert_allclose(p, ref, rtol=1e-10)
    assert p[0] == pytest.approx(ref[0])  # DC not doubled
    assert p[-1] == pytest.approx(ref[-1])  # Nyquist not doubled


# INV-004 window metrics and tone power independent of window and bin offset
@pytest.mark.parametrize("window,enbw", [("hann", 1.5), ("hamming", 1.3628), ("boxcar", 1.0), ("blackmanharris", 2.0044), ("flattop", 3.7702)])
def test_inv004_enbw(window, enbw):
    m = spectral.window_metrics(window, 4096)
    assert m.enbw_bins == pytest.approx(enbw, rel=2e-3)


@pytest.mark.parametrize("window", ["hann", "hamming", "blackmanharris", "flattop"])
@pytest.mark.parametrize("offset", [0.0, 0.25, 0.5])
def test_inv004_tone_power_recovers_a2_over_2(window, offset):
    plan = _plan(int(FS * 10))
    df = FS / plan.nperseg
    f0 = (1000 // df + offset) * df
    a = 0.3
    x = signals.sine(f0, a, 10.0, FS) + signals.white_noise(1e-5, 10.0, FS, seed=2)
    f, p = spectral.masked_welch(x, FS, plan, window)
    wm = spectral.window_metrics(window, plan.nperseg)
    tones = tonal.detect_tones(f, p, window, wm.enbw_hz(FS), 10, 20, 20000, 5)
    assert len(tones) == 1
    t = tones[0]
    assert t["freq_hz"] == pytest.approx(f0, abs=0.35 * df)
    assert t["power"] == pytest.approx(a * a / 2, rel=0.01)  # 0.04 dB


# INV-005 cross-spectrum orientation and phase sign
def test_inv005_phase_sign_of_delay():
    x = signals.white_noise(0.1, 10.0, FS, seed=4)
    tau = 0.0005
    y = signals.delay(x, tau, FS)
    plan = _plan(len(x), res=10.0)
    f, pxx, pyy, pxy = spectral.masked_csd(x, y, FS, plan)
    coh, h1, ok = cross.coherence_and_transfer(pxx, pyy, pxy)
    band = (f > 100) & (f < 800)
    expected = -2 * np.pi * f[band] * tau
    got = np.unwrap(np.angle(h1[band]))
    np.testing.assert_allclose(got, expected, atol=0.05)
    assert np.nanmedian(np.abs(h1[band])) == pytest.approx(1.0, rel=0.02)
    d, amb = cross.estimate_delay(x, y, FS)
    assert d == pytest.approx(tau, abs=1 / FS / 4)
    assert amb < 0.5


def test_inv005_counterexample_wrong_orientation_detected():
    """Swapping x and y must flip the phase sign: this test fails if orientation is broken."""
    x = signals.white_noise(0.1, 5.0, FS, seed=5)
    y = signals.delay(x, 0.001, FS)
    plan = _plan(len(x), res=10.0)
    f, pyy, pxx, pyx = spectral.masked_csd(y, x, FS, plan)
    _, h, _ = cross.coherence_and_transfer(pyy, pxx, pyx)
    k = np.argmin(np.abs(f - 200))
    assert np.angle(h[k]) == pytest.approx(+2 * np.pi * 200 * 0.001, abs=0.05)


# INV-007 resampling gain and boundary
def test_inv007_resample_passband_gain_and_edges():
    x = signals.sine(1000, 0.5, 2.0, 44100)
    y, fs2, edge = resample_rational(x, 44100, 48000)
    assert fs2 == pytest.approx(48000)
    core = y[edge * 2 : -edge * 2]
    assert np.std(core) * math.sqrt(2) == pytest.approx(0.5, rel=1e-3)
    assert edge > 0


# INV-008 band integration: adjacent bands sum to union, fractional bins
def test_inv008_band_additivity_and_white_noise_density():
    x = signals.white_noise(0.05, 20.0, FS, seed=6)
    plan = _plan(len(x))
    f, p = spectral.masked_welch(x, FS, plan)
    a = spectral.integrate_band(f, p, 100.3, 250.7)
    b = spectral.integrate_band(f, p, 250.7, 777.7)
    u = spectral.integrate_band(f, p, 100.3, 777.7)
    assert a + b == pytest.approx(u, rel=1e-12)
    # white noise density = var/(fs/2): band power proportional to bandwidth
    assert u == pytest.approx(np.var(x) * (777.7 - 100.3) / (FS / 2), rel=0.05)


def test_band_centres_iec_base10():
    bands = spectral.fractional_octave_bands("third_octave", 20, 20000)
    centres = [round(c, 1) for _, c, _ in bands]
    assert 1000.0 in centres and 125.9 in centres  # exact base-10 values (nominal 125)
    oct_ = spectral.fractional_octave_bands("octave", 20, 20000)
    assert any(abs(c - 1000) < 1e-9 for _, c, _ in oct_)


# INV-010 missing-data exclusion: a gap of zeros must not bias the PSD
def test_inv010_gap_exclusion_vs_naive():
    x = signals.white_noise(0.1, 20.0, FS, seed=7)
    y, gaps = signals.with_dropouts(x, FS, [5.0, 12.0], 2.0)
    mask = np.ones(len(y), bool)
    for a, b in gaps:
        mask[a:b] = False
    plan = spectral.plan_segments(mask, FS, 1.0, 0.5, 8)
    f, p = spectral.masked_welch(y, FS, plan)
    df = f[1] - f[0]
    assert np.sum(p) * df == pytest.approx(np.var(x), rel=0.03)
    # counterexample: naive analysis including zeros under-reads by ~20% (4 s of 20 s)
    plan_naive = _plan(len(y))
    _, pn = spectral.masked_welch(y, FS, plan_naive)
    assert np.sum(pn) * df < 0.9 * np.var(x)


# INV-011 denominator masks
def test_inv011_masked_bins_are_nan_not_numbers():
    pxx = np.array([1.0, 0.0, 1.0])
    pyy = np.array([1.0, 1.0, 0.0])
    pxy = np.array([0.5 + 0j, 0j, 0j])
    coh, h1, ok = cross.coherence_and_transfer(pxx, pyy, pxy)
    assert ok.tolist() == [True, False, False]
    assert np.isnan(coh[1]) and np.isnan(coh[2]) and np.isnan(h1[1])


# ADV-009: coherence with insufficient averaging
def test_adv009_single_segment_coherence_is_one_and_threshold_is_one():
    x = signals.white_noise(1, 1.0, FS, seed=8)
    y = signals.white_noise(1, 1.0, FS, seed=9)  # independent!
    n = len(x)
    plan = spectral.SegmentPlan(n, 0, 1, 1, ((0, n),), False)
    f, pxx, pyy, pxy = spectral.masked_csd(x, y, FS, plan, "hann")
    coh, _, _ = cross.coherence_and_transfer(pxx, pyy, pxy)
    assert np.nanmin(coh[1:-1]) > 0.999  # spurious "perfect" coherence
    assert cross.coherence_threshold(1, 0.05) == 1.0  # ...so nothing may be declared significant
    # with proper averaging independent noise falls below threshold
    x2 = signals.white_noise(1, 30.0, FS, seed=8)
    y2 = signals.white_noise(1, 30.0, FS, seed=9)
    plan2 = _plan(len(x2), res=10.0)
    f, pxx, pyy, pxy = spectral.masked_csd(x2, y2, FS, plan2)
    coh2, _, _ = cross.coherence_and_transfer(pxx, pyy, pxy)
    thr = cross.coherence_threshold(plan2.n_eff, 0.05)
    assert np.nanmean(coh2 > thr) < 0.08  # ~alpha false-positive rate


def test_segment_plan_short_capture_and_insufficient():
    assert spectral.plan_segments(np.ones(100, bool), FS, 1.0, 0.5, 8) is None  # EDGE-003
    p = spectral.plan_segments(np.ones(3000, bool), FS, 1.0, 0.5, 8)
    assert p is not None and p.nperseg == 256 and p.sufficient is True
    p2 = spectral.plan_segments(np.ones(600, bool), FS, 1.0, 0.5, 8)
    assert p2 is not None and p2.sufficient is False  # EDGE-012


# EDGE cases on raw screening
def test_edge_screening_silence_constant_nan_clipping():
    n = 48000
    s = levels.screen_channel(np.zeros(n), FS, 0)
    assert any(f.code.value == "silence" for f in s.flags)
    s = levels.screen_channel(np.full(n, 0.3), FS, 0)  # constant
    codes = {f.code.value for f in s.flags}
    assert {"silence", "dc_offset"} <= codes
    x = signals.white_noise(0.1, 1.0, FS, seed=1)
    x[100:110] = np.nan
    x[5000] = np.inf
    s = levels.screen_channel(x, FS, 0)
    assert s.nonfinite_samples == 11 and not s.valid[105] and not s.valid[5000]
    y = signals.sine(100, 1.5, 1.0, FS)  # heavy clipping after clip()
    s = levels.screen_channel(signals.clip(y), FS, 0)
    assert s.clipped_samples > 0 and s.valid.mean() < 0.5
    assert any(f.code.value == "clipping" and f.severity.value == "invalid" for f in s.flags)


def test_extreme_amplitudes_finite():
    tiny = signals.sine(1000, 1e-6, 2.0, FS)
    plan = _plan(len(tiny))
    f, p = spectral.masked_welch(tiny, FS, plan)
    assert np.all(np.isfinite(p))
    t = tonal.detect_tones(f, p, "hann", 1.5 * FS / plan.nperseg, 10, 20, 20000, 3)
    assert t and t[0]["power"] == pytest.approx(0.5e-12, rel=0.02)


# Harmonics and mains
def test_harmonic_family_and_mains():
    x = signals.harmonics(50.0, [0.1, 0.05, 0.03, 0.02], 10.0, FS) + signals.white_noise(1e-4, 10.0, FS, seed=3)
    plan = _plan(len(x), res=0.5)
    f, p = spectral.masked_welch(x, FS, plan)
    wm = spectral.window_metrics("hann", plan.nperseg)
    tones = tonal.detect_tones(f, p, "hann", wm.enbw_hz(FS), 10, 20, 2000, 20)
    fams = tonal.harmonic_families(tones, f[1] - f[0])
    assert fams and fams[0]["f0_hz"] == pytest.approx(50, abs=0.2) and fams[0]["mains"] == "50"
    assert fams[0]["orders"][:4] == [1, 2, 3, 4]


def test_non_mains_family_not_flagged_mains():
    x = signals.harmonics(37.0, [0.1, 0.05, 0.03], 10.0, FS) + signals.white_noise(1e-4, 10.0, FS, seed=3)
    plan = _plan(len(x), res=0.5)
    f, p = spectral.masked_welch(x, FS, plan)
    tones = tonal.detect_tones(f, p, "hann", 1.5 * FS / plan.nperseg, 10, 20, 2000, 20)
    fams = tonal.harmonic_families(tones, f[1] - f[0])
    assert fams and fams[0]["mains"] == "none"


def test_resonance_q_measurable_vs_tone_resolution_limited():
    x = signals.white_noise(0.1, 30.0, FS, seed=11)
    r = signals.resonator(x, 400.0, 20.0, FS)
    plan = _plan(len(r), res=1.0)
    f, p = spectral.masked_welch(r, FS, plan)
    wm = spectral.window_metrics("hann", plan.nperseg)
    t = tonal.detect_tones(f, p, "hann", wm.enbw_hz(FS), 6, 50, 5000, 3)
    assert t and t[0]["q"] == pytest.approx(20, rel=0.25)
    s = signals.sine(400, 0.1, 30.0, FS) + signals.white_noise(1e-4, 30.0, FS, seed=1)
    _, ps = spectral.masked_welch(s, FS, plan)
    ts = tonal.detect_tones(f, ps, "hann", wm.enbw_hz(FS), 6, 50, 5000, 3)
    assert ts and ts[0]["q"] is None  # pure tone: resolution-limited


# stats
def test_compare_levels_measured_and_min_effect():
    d, u, sig, kind = stats.compare_levels([60.0, 60.2, 59.9], [54.0, 54.3, 53.8], 0.3, 0.3)
    assert kind == "measured" and sig and d == pytest.approx(-6.0, abs=0.1)
    d, u, sig, kind = stats.compare_levels([60.0, 60.05], [59.6, 59.65], 0.01, 0.01)
    assert not sig  # statistically tight but below 1 dB practical minimum
    d, u, sig, kind = stats.compare_levels([60.0], [57.0], 0.4, 0.4)
    assert kind == "estimated" and sig


# Optimisation equivalence: blocked processing must not change results
def test_blocked_welch_equals_single_call():
    from scipy import signal as sps

    x = signals.white_noise(0.1, 30.0, FS, seed=21)
    plan = spectral.plan_segments(np.ones(len(x), bool), FS, 10.0, 0.5, 8)
    assert plan.n_segments > spectral.BLOCK_SEGMENTS  # exercises several blocks
    f, p = spectral.masked_welch(x, FS, plan)
    step = plan.nperseg - plan.noverlap
    end = plan.nperseg + (plan.n_segments - 1) * step
    f2, p2 = sps.welch(x[:end], fs=FS, nperseg=plan.nperseg, noverlap=plan.noverlap, detrend="constant", scaling="density")
    np.testing.assert_allclose(p, p2, rtol=1e-10)


def test_spectrogram_matches_scipy_reference():
    from scipy import signal as sps

    x = signals.white_noise(0.1, 2.0, FS, seed=22) + signals.sine(3000, 0.2, 2.0, FS)
    f, t, s = spectral.spectrogram(x, FS, 1024, max_frames=100000)
    f2, t2, s2 = sps.spectrogram(x, fs=FS, window="hann", nperseg=1024, noverlap=512, detrend="constant", scaling="density", mode="psd")
    np.testing.assert_allclose(f, f2)
    np.testing.assert_allclose(t, t2)
    np.testing.assert_allclose(s, s2, rtol=1e-9, atol=1e-18)


def test_envelope_spectrum_finds_modulation_rate():
    x = signals.am_tone(2000.0, 7.0, 0.8, 0.3, 60.0, FS) + signals.white_noise(1e-3, 60.0, FS, seed=4)
    f, p = transient.envelope_spectrum(x, FS, band=(1500, 2500), fmax=50)
    k = np.argmax(p[f > 1])
    assert f[f > 1][k] == pytest.approx(7.0, abs=0.3)


def test_fm_tone_spreads_energy_but_total_power_conserved():
    x = signals.fm_tone(1000.0, 5.0, 40.0, 0.4, 20.0, FS)
    plan = _plan(len(x))
    f, p = spectral.masked_welch(x, FS, plan)
    assert np.sum(p) * (f[1] - f[0]) == pytest.approx(0.4**2 / 2, rel=0.01)
    assert spectral.integrate_band(f, p, 950, 1050) == pytest.approx(0.08, rel=0.02)
