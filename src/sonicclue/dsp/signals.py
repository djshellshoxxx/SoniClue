"""Deterministic analytic test signals (docs/specs/17-testing-and-validation.md, FIX-*).

Every generator takes an explicit ``seed`` where randomness is involved. Same
inputs always give bit-identical output, which makes fixtures reproducible.
These signals feed the numerical reference tests, the SIMULATED acquisition
backend and the stimulus generator. Simulated data is always labelled as such
by the caller (QualityCode.SIMULATED_DATA).
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps


def time_axis(duration_s: float, fs: float) -> np.ndarray:
    n = int(round(duration_s * fs))
    return np.arange(n, dtype=np.float64) / fs


def sine(freq_hz: float, amplitude: float, duration_s: float, fs: float, phase_rad: float = 0.0) -> np.ndarray:
    """Peak amplitude ``amplitude``. RMS = amplitude/sqrt(2)."""
    t = time_axis(duration_s, fs)
    return amplitude * np.sin(2 * np.pi * freq_hz * t + phase_rad)


def harmonics(f0: float, amplitudes: list[float], duration_s: float, fs: float) -> np.ndarray:
    """Sum of k*f0 components with the given peak amplitudes (k = 1..len)."""
    t = time_axis(duration_s, fs)
    out = np.zeros_like(t)
    for k, a in enumerate(amplitudes, start=1):
        if k * f0 < fs / 2:
            out += a * np.sin(2 * np.pi * k * f0 * t + 0.3 * k)
    return out


def white_noise(rms: float, duration_s: float, fs: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(int(round(duration_s * fs))) * rms


def pink_noise(rms: float, duration_s: float, fs: float, seed: int) -> np.ndarray:
    """1/f power spectrum by spectral shaping of white noise, normalised to ``rms``."""
    n = int(round(duration_s * fs))
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / fs)
    f[0] = f[1] if n > 1 else 1.0
    spec /= np.sqrt(f)
    x = np.fft.irfft(spec, n)
    x -= x.mean()
    s = x.std()
    return x * (rms / s) if s > 0 else x


def band_noise(rms: float, f_lo: float, f_hi: float, duration_s: float, fs: float, seed: int) -> np.ndarray:
    x = white_noise(1.0, duration_s, fs, seed)
    sos = sps.butter(4, [f_lo, min(f_hi, 0.49 * fs)], btype="bandpass", fs=fs, output="sos")
    y = sps.sosfiltfilt(sos, x)
    s = y.std()
    return y * (rms / s) if s > 0 else y


def impulse_train(interval_s: float, amplitude: float, duration_s: float, fs: float, width_s: float = 0.002,
                  jitter_s: float = 0.0, seed: int = 0) -> np.ndarray:
    """Short decaying bursts (rattle model) at roughly regular intervals."""
    n = int(round(duration_s * fs))
    out = np.zeros(n)
    rng = np.random.default_rng(seed)
    w = max(1, int(width_s * fs))
    burst = amplitude * np.exp(-np.arange(8 * w) / w) * np.sin(2 * np.pi * 2500 * np.arange(8 * w) / fs)
    t = interval_s / 2
    while t < duration_s:
        i = int((t + (rng.uniform(-jitter_s, jitter_s) if jitter_s else 0)) * fs)
        if 0 <= i < n:
            m = min(len(burst), n - i)
            out[i : i + m] += burst[:m]
        t += interval_s
    return out


def chirp(f0: float, f1: float, amplitude: float, duration_s: float, fs: float) -> np.ndarray:
    t = time_axis(duration_s, fs)
    return amplitude * sps.chirp(t, f0=f0, t1=duration_s, f1=f1, method="logarithmic")


def am_tone(carrier_hz: float, mod_hz: float, depth: float, amplitude: float, duration_s: float, fs: float) -> np.ndarray:
    t = time_axis(duration_s, fs)
    return amplitude * (1 + depth * np.sin(2 * np.pi * mod_hz * t)) * np.sin(2 * np.pi * carrier_hz * t)


def fm_tone(carrier_hz: float, mod_hz: float, deviation_hz: float, amplitude: float, duration_s: float, fs: float) -> np.ndarray:
    t = time_axis(duration_s, fs)
    beta = deviation_hz / mod_hz
    return amplitude * np.sin(2 * np.pi * carrier_hz * t + beta * np.sin(2 * np.pi * mod_hz * t))


def resonator(x: np.ndarray, f_res: float, q: float, fs: float) -> np.ndarray:
    """Second-order band-pass (resonance-like response, peak gain 1 at f_res)."""
    b, a = sps.iirpeak(f_res, q, fs=fs)
    return sps.lfilter(b, a, x)


def delay(x: np.ndarray, delay_s: float, fs: float) -> np.ndarray:
    """Fractional delay via frequency-domain phase shift (circular; callers trim the edges)."""
    n = len(x)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / fs)
    return np.fft.irfft(spec * np.exp(-2j * np.pi * f * delay_s), n)


def clip(x: np.ndarray, level: float = 1.0) -> np.ndarray:
    return np.clip(x, -level, level)


def with_dropouts(x: np.ndarray, fs: float, at_s: list[float], length_s: float) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Zero out blocks. Returns the signal and the half-open frame ranges that were dropped."""
    y = x.copy()
    gaps = []
    for t in at_s:
        a = int(t * fs)
        b = min(len(y), a + int(length_s * fs))
        y[a:b] = 0.0
        gaps.append((a, b))
    return y, gaps


def drifted(x: np.ndarray, ppm: float) -> np.ndarray:
    """Resample as if recorded by a clock running ``ppm`` fast (more samples per second)."""
    n_new = int(round(len(x) * (1 + ppm * 1e-6)))
    return sps.resample(x, n_new)
