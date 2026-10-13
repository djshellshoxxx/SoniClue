"""Cross-channel analysis: coherence, transfer function, delay, eligibility.

Conventions (INV-005, INV-011, ADV-009):

* Pxy = E[conj(X) Y]; H1 = Pxy / Pxx; phase(H1) = -2*pi*f*tau when y lags x by tau.
* gamma^2 = |Pxy|^2 / (Pxx Pyy). Bins where Pxx or Pyy is below
  ``1e-12 * max`` are masked (NaN) and never reported as numbers.
* Significance threshold for coherence under the null hypothesis of zero true
  coherence, with n independent averages: gamma^2_crit = 1 - alpha^(1/(n-1)).
  With n = 1 every bin has gamma^2 = 1 exactly, so the threshold is 1 and
  nothing can be significant. This is the "high coherence from inadequate
  averaging" counterexample.
* Delay comes from the peak of the FFT cross-correlation, refined by
  parabolic interpolation. The ambiguity ratio is the largest secondary peak
  (outside +/-0.5 ms or 5 samples of the main peak) divided by the main peak.
  A ratio above 0.8 means the delay is ambiguous: periodic signals have many
  equally good lags.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps


def coherence_threshold(n_eff: int, alpha: float) -> float:
    if n_eff < 2:
        return 1.0
    return float(1.0 - alpha ** (1.0 / (n_eff - 1)))


def coherence_and_transfer(pxx: np.ndarray, pyy: np.ndarray, pxy: np.ndarray):
    with np.errstate(divide="ignore", invalid="ignore"):
        mx = max(float(np.max(pxx)), 1e-300)
        my = max(float(np.max(pyy)), 1e-300)
        ok = (pxx > 1e-12 * mx) & (pyy > 1e-12 * my)
        coh = np.where(ok, np.abs(pxy) ** 2 / (pxx * pyy), np.nan)
        h1 = np.where(ok, pxy / pxx, np.nan + 0j)
    return np.clip(coh, 0.0, 1.0), h1, ok


def estimate_delay(x: np.ndarray, y: np.ndarray, fs: float, max_lag_s: float | None = None):
    """Delay of y relative to x in seconds (positive means y lags x), with the ambiguity ratio."""
    n = min(len(x), len(y))
    if n < 16:
        return None, 1.0
    xa = x[:n] - np.mean(x[:n])
    ya = y[:n] - np.mean(y[:n])
    if not np.any(xa) or not np.any(ya):
        return None, 1.0
    c = sps.correlate(ya, xa, mode="full", method="fft")
    lags = sps.correlation_lags(n, n, mode="full")
    if max_lag_s is not None:
        keep = np.abs(lags) <= int(max_lag_s * fs)
        c, lags = c[keep], lags[keep]
    a = np.abs(c)
    k = int(np.argmax(a))
    peak = a[k]
    if peak <= 0:
        return None, 1.0
    excl = max(5, int(0.0005 * fs))
    mask = np.ones_like(a, dtype=bool)
    mask[max(0, k - excl) : k + excl + 1] = False
    second = float(np.max(a[mask])) if mask.any() else 0.0
    delta = 0.0
    if 0 < k < len(a) - 1:
        y0, y1, y2 = a[k - 1], a[k], a[k + 1]
        den = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return float((lags[k] + delta) / fs), float(min(1.0, second / peak))


def accel_to_velocity_psd(f: np.ndarray, psd_a: np.ndarray, f_low: float = 2.0) -> np.ndarray:
    """Velocity PSD from acceleration PSD: S_v = S_a / (2*pi*f)^2. Bins below
    f_low are set to NaN, because integration amplifies low-frequency noise
    without bound."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = psd_a / (2 * np.pi * f) ** 2
    out[f < f_low] = np.nan
    return out
