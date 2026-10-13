"""Resampling helpers (INV-007).

``resample_rational`` uses scipy's polyphase FIR (``resample_poly``). The
filter is zero-phase (symmetric and centred), so no group delay needs
compensating. The first and last ``edge_frames`` output samples are affected
by the filter start-up transient and are returned so callers can mark them
invalid.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from scipy import signal as sps


def resample_rational(x: np.ndarray, fs_from: float, fs_to: float, max_den: int = 1000):
    ratio = Fraction(fs_to / fs_from).limit_denominator(max_den)
    up, down = ratio.numerator, ratio.denominator
    y = sps.resample_poly(x, up, down)
    # resample_poly's default Kaiser FIR half-length is 10*max(up, down) input-rate taps.
    edge = int(np.ceil(10 * max(up, down) / down))
    achieved = fs_from * up / down
    return y, achieved, edge


def correct_drift(x: np.ndarray, drift_ppm: float) -> np.ndarray:
    """Undo a clock that ran ``drift_ppm`` fast (FFT resampling to len/(1+ppm)).
    The ends are affected by circular wrap-around; callers trim 1% at each end."""
    n_new = int(round(len(x) / (1 + drift_ppm * 1e-6)))
    return sps.resample(x, n_new)
