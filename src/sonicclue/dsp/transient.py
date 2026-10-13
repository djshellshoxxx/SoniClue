"""Transient and event detection, plus the envelope (modulation) spectrum.

Events: short-time RMS in frames of ``frame_s``. Background is the median of
the frame levels in dB and spread is the MAD in dB. A frame is part of an
event when it exceeds the background by max(threshold_db, 6*MAD). Frames
closer than two frames apart are merged. Events count as periodic when there
are at least 4 of them and the interval coefficient of variation is below 0.25
(the rattle signature used by DIAG rules).
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps


def detect_events(x: np.ndarray, valid: np.ndarray, fs: float, frame_s: float, threshold_db: float) -> dict:
    n = int(max(1, round(frame_s * fs)))
    m = len(x) // n
    empty = {"times": [], "max_excess_db": 0.0, "periodic": False, "median_interval_s": None}
    if m < 8:
        return empty
    vr = valid[: m * n].reshape(m, n).all(axis=1)
    rms = np.empty(m)
    step = max(1, (1 << 21) // n)  # frames per chunk: bounded temporaries
    for i in range(0, m, step):
        xr = np.asarray(x[i * n : min(m, i + step) * n], dtype=np.float64).reshape(-1, n)
        rms[i : i + len(xr)] = xr.std(axis=1)
    db = 20 * np.log10(np.maximum(rms, 1e-12))
    if vr.sum() < 8:
        return empty
    bg = float(np.median(db[vr]))
    mad = float(np.median(np.abs(db[vr] - bg)))
    thr = bg + max(threshold_db, 6 * mad)
    hot = (db > thr) & vr
    times = []
    i = 0
    while i < m:
        if hot[i]:
            j = i
            while j + 1 < m and (hot[j + 1] or (j + 2 < m and hot[j + 2])):
                j += 1
            seg = db[i : j + 1]
            times.append(float((i + int(np.argmax(seg))) * n / fs))
            i = j + 1
        else:
            i += 1
    excess = float(np.max(db[vr]) - bg)
    med = None
    periodic = False
    if len(times) >= 2:
        iv = np.diff(times)
        med = float(np.median(iv))
        if len(times) >= 4 and np.mean(iv) > 0:
            periodic = bool(np.std(iv) / np.mean(iv) < 0.25)
    return {"times": times, "max_excess_db": excess, "periodic": periodic, "median_interval_s": med}


def envelope_spectrum(x: np.ndarray, fs: float, band: tuple[float, float] | None = None, fmax: float = 200.0,
                      block_s: float = 20.0):
    """PSD of the Hilbert envelope (optionally after band-pass filtering).
    Peaks show modulation rates such as fan blade-pass, rattle repetition or
    beating. Computed block-wise (``block_s`` blocks, PSDs averaged by length),
    so memory stays bounded for long captures. Returns (f, psd) up to ``fmax``."""
    if len(x) < 64:
        return np.zeros(0), np.zeros(0)
    q = int(max(1, fs // (4 * fmax)))
    fs2 = fs / q
    blk = int(block_s * fs)
    nps = int(min(2 ** int(np.log2(max(16, fs2 * 4))), max(16, blk // q)))
    sos = None
    if band:
        lo, hi = band[0], min(band[1], 0.45 * fs)
        if lo < hi:
            sos = sps.butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    acc, wsum, f = None, 0, None
    for s in range(0, len(x), blk):
        y = np.asarray(x[s : s + blk], dtype=np.float64)
        if len(y) < max(64, blk // 4) and acc is not None:
            break
        y = y - y.mean()
        if sos is not None and len(y) > 50:
            y = sps.sosfiltfilt(sos, y)
        env = np.abs(sps.hilbert(y))
        env -= env.mean()
        if q > 1:
            env = sps.decimate(env, q, ftype="fir", zero_phase=True) if len(env) > 30 * q else env[::q]
        if len(env) < 16:
            continue
        f, p = sps.welch(env, fs=fs2, nperseg=min(nps, len(env)), scaling="density")
        if acc is not None and len(p) != len(acc):
            continue
        acc = p * len(y) if acc is None else acc + p * len(y)
        wsum += len(y)
    if acc is None:
        return np.zeros(0), np.zeros(0)
    keep = f <= fmax
    return f[keep], (acc / wsum)[keep]
