"""Tonal analysis: noise floor, tone detection, tone power, Q, harmonic families.

Method (docs/specs/08-dsp-and-numerical-methods.md section 6):

1. Local noise floor: a running median of the PSD in dB over ``floor_bins``
   bins. The median ignores narrow peaks, so it tracks the broadband floor.
2. Candidates are local maxima whose prominence (PSD dB minus floor dB) is at
   least the threshold. Each is refined by parabolic interpolation of the dB
   values at bins k-1, k, k+1.
3. Tone RMS = sqrt(sum of PSD over the window main lobe * df). Because the PSD
   is density-scaled, this is window-independent (INV-004).
4. Q = f/BW(-3 dB) only when the -3 dB bandwidth exceeds twice the ENBW.
   Otherwise the peak is resolution-limited (a stable tone, or a resonance
   sharper than the analysis can resolve) and Q is reported as unavailable.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage
from scipy import signal as sps

from .spectral import MAIN_LOBE_HALF_BINS

TINY = 1e-30


def to_db(p: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(p, TINY))


def noise_floor_db(psd: np.ndarray, floor_bins: int = 61) -> np.ndarray:
    size = max(5, min(floor_bins, (len(psd) // 2) * 2 - 1))
    return ndimage.median_filter(to_db(psd), size=size, mode="nearest")


def detect_tones(f: np.ndarray, psd: np.ndarray, window: str, enbw_hz: float, prominence_db: float,
                 fmin: float, fmax: float, max_peaks: int) -> list[dict]:
    if len(f) < 8:
        return []
    df = f[1] - f[0]
    db = to_db(psd)
    floor = noise_floor_db(psd)
    half = MAIN_LOBE_HALF_BINS.get(window, 3)
    idx, _ = sps.find_peaks(db)
    cands = [k for k in idx if fmin <= f[k] <= fmax and db[k] - floor[k] >= prominence_db]
    cands.sort(key=lambda k: db[k] - floor[k], reverse=True)
    chosen: list[int] = []
    for k in cands:
        if all(abs(k - c) > 2 * half for c in chosen):
            chosen.append(k)
        if len(chosen) >= max_peaks:
            break
    out = []
    for k in sorted(chosen):
        a, b, c = db[k - 1], db[k], db[min(k + 1, len(db) - 1)]
        den = a - 2 * b + c
        delta = 0.5 * (a - c) / den if den != 0 else 0.0
        delta = float(np.clip(delta, -0.5, 0.5))
        lo, hi = max(0, k - half), min(len(psd), k + half + 1)
        power = float(np.sum(psd[lo:hi]) * df)
        out.append({
            "freq_hz": float((k + delta) * df),
            "power": power,
            "rms": float(np.sqrt(power)),
            "prominence_db": float(db[k] - floor[k]),
            "q": _q_factor(f, db, k, enbw_hz),
            "bin": int(k),
        })
    return out


def _q_factor(f: np.ndarray, db: np.ndarray, k: int, enbw_hz: float) -> float | None:
    target = db[k] - 3.0
    i = k
    while i > 0 and db[i] > target:
        i -= 1
    j = k
    while j < len(db) - 1 and db[j] > target:
        j += 1
    if i == 0 or j == len(db) - 1:
        return None

    def cross(i0, i1):
        y0, y1 = db[i0], db[i1]
        return f[i0] + (target - y0) * (f[i1] - f[i0]) / (y1 - y0) if y1 != y0 else f[i0]

    # left crossing lies between bin i (below target) and i+1 (above); right between j-1 and j
    bw = cross(j - 1, j) - cross(i, i + 1)
    if bw <= 2 * enbw_hz:
        return None
    return float(f[k] / bw)


def harmonic_families(peaks: list[dict], df: float, max_order: int = 12) -> list[dict]:
    """Group tones into families k*f0. f0 must itself be a detected tone and at
    least one higher order must be present. Tolerance is max(1.5*df, 0.5% of
    k*f0). Mains: f0 within 1% of 50 or 100 Hz (60 or 120 Hz), because
    magnetostriction and rectifier hum appear at twice the line frequency."""
    freqs = sorted(p["freq_hz"] for p in peaks)
    used: set[float] = set()
    fams = []
    for f0 in freqs:
        if f0 in used or f0 <= 0:
            continue
        orders = [1]
        members = [f0]
        for k in range(2, max_order + 1):
            tol = max(1.5 * df, 0.005 * k * f0)
            match = [g for g in freqs if g not in used and g not in members and abs(g - k * f0) <= tol]
            if match:
                orders.append(k)
                members.append(min(match, key=lambda g: abs(g - k * f0)))
        if len(orders) >= 2:
            used.update(members)
            mains = "none"
            for line in (50.0, 60.0):
                if any(abs(f0 - m * line) <= 0.01 * m * line for m in (1, 2)):
                    mains = str(int(line))
            fams.append({"f0_hz": f0, "orders": orders, "mains": mains})
    return fams
