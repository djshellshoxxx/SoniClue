"""Spectral estimation: windows, segment planning, masked Welch PSD,
spectrogram and fractional-octave band integration.

Conventions (docs/specs/08-dsp-and-numerical-methods.md sections 3-5):

* PSD is one-sided spectral density in unit^2/Hz (``scipy.signal.welch`` with
  ``scaling="density"``). Every bin except DC and, for even nperseg, Nyquist
  is doubled, so that ``sum(psd) * df == mean square`` of the detrended signal
  (Parseval, INV-002, INV-003).
* Window metrics: coherent gain CG = sum(w)/N. ENBW in bins = N*sum(w^2)/sum(w)^2,
  and enbw_hz = fs*sum(w^2)/sum(w)^2 (INV-004). Density scaling makes integrated
  power window-independent; ENBW is reported because it sets the effective
  resolution and the tone-integration width.
* Segments touching invalid samples (gaps, clipping, non-finite values) are
  excluded rather than zero-filled (INV-010). Each contiguous valid run is
  Welch-averaged on its own and the runs are pooled, weighted by segment count.
* Independent-average count ``n_eff`` is the number of *non-overlapping*
  segments that fit in the valid runs. It is a conservative figure used for
  coherence thresholds and level uncertainty; overlapped segments are not
  fully independent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

# Half-width (in bins) of each window's main lobe as used for tone power
# integration. Chosen so that a sine anywhere between bins keeps >99.5% of its
# power inside the integration span (checked by tests/test_dsp_numerics.py).
MAIN_LOBE_HALF_BINS = {"hann": 3, "hamming": 3, "blackmanharris": 5, "flattop": 6, "boxcar": 2}


@dataclass(frozen=True)
class WindowMetrics:
    name: str
    n: int
    coherent_gain: float
    enbw_bins: float

    def enbw_hz(self, fs: float) -> float:
        return self.enbw_bins * fs / self.n


def window_metrics(name: str, n: int) -> WindowMetrics:
    w = sps.get_window(name, n, fftbins=True)
    cg = float(w.sum() / n)
    enbw = float(n * np.sum(w * w) / (w.sum() ** 2))
    return WindowMetrics(name, n, cg, enbw)


def valid_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) runs where mask is True."""
    if mask.size == 0:
        return []
    m = np.concatenate([[False], mask.astype(bool), [False]])
    d = np.diff(m.astype(np.int8))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


@dataclass(frozen=True)
class SegmentPlan:
    nperseg: int
    noverlap: int
    n_segments: int  # overlapped segments actually averaged
    n_eff: int  # non-overlapping segment count (independence-conservative)
    runs: tuple[tuple[int, int], ...]
    sufficient: bool  # n_eff >= min_averages


def _count(runs, nperseg, step):
    k = sum(1 + (b - a - nperseg) // step for a, b in runs if b - a >= nperseg)
    k_eff = sum((b - a) // nperseg for a, b in runs if b - a >= nperseg)
    return k, k_eff


def plan_segments(mask: np.ndarray, fs: float, resolution_hz: float, overlap: float, min_averages: int,
                  min_nperseg: int = 256) -> SegmentPlan | None:
    """Pick nperseg as the largest power of two <= fs/resolution, halving it until
    the valid data gives ``min_averages`` independent segments, but never going
    below ``min_nperseg``. Returns None if no valid run can hold even one
    ``min_nperseg`` segment (EDGE-003 short capture)."""
    runs = valid_runs(mask)
    nperseg = 2 ** int(math.floor(math.log2(max(fs / resolution_hz, 2))))
    nperseg = max(nperseg, min_nperseg)
    while True:
        step = max(1, nperseg - int(round(nperseg * overlap)))
        k, k_eff = _count(runs, nperseg, step)
        if (k_eff >= min_averages or nperseg <= min_nperseg) and k >= 1:
            break
        if nperseg <= min_nperseg:
            return None
        nperseg //= 2
    noverlap = nperseg - step
    return SegmentPlan(nperseg, noverlap, k, k_eff, tuple((a, b) for a, b in runs if b - a >= nperseg),
                       k_eff >= min_averages)


BLOCK_SEGMENTS = 64  # segments per Welch call: bounds memory to O(64 * nperseg) per channel


def _blocks(plan: SegmentPlan):
    """Yield (start, end, k) sample blocks covering each run's segments in groups of
    BLOCK_SEGMENTS. Averaging per block, weighted by k, equals one Welch over the
    run, because the Welch average is linear in the segment periodograms."""
    step = plan.nperseg - plan.noverlap
    for a, b in plan.runs:
        k_run = 1 + (b - a - plan.nperseg) // step
        done = 0
        while done < k_run:
            k = min(BLOCK_SEGMENTS, k_run - done)
            s = a + done * step
            yield s, s + plan.nperseg + (k - 1) * step, k
            done += k


def masked_welch(x: np.ndarray, fs: float, plan: SegmentPlan, window: str = "hann") -> tuple[np.ndarray, np.ndarray]:
    """One-sided density PSD pooled over valid runs. Returns (freqs, psd)."""
    acc = None
    total = 0
    f = None
    for s, e, k in _blocks(plan):
        f, p = sps.welch(np.asarray(x[s:e], dtype=np.float64), fs=fs, window=window, nperseg=plan.nperseg,
                         noverlap=plan.noverlap, detrend="constant", scaling="density", average="mean")
        acc = p * k if acc is None else acc + p * k
        total += k
    assert acc is not None, "plan has no runs"
    return f, acc / total


def masked_csd(x: np.ndarray, y: np.ndarray, fs: float, plan: SegmentPlan, window: str = "hann"):
    """Pooled auto- and cross-spectra (one-sided density).

    Orientation (INV-005): Pxy = E[conj(X) * Y], the scipy convention, so
    H1 = Pxy/Pxx and y(t) = x(t - tau) gives phase(H1) = -2*pi*f*tau."""
    acc = None
    total = 0
    f = None
    kw = dict(fs=fs, window=window, nperseg=plan.nperseg, noverlap=plan.noverlap, detrend="constant", scaling="density")
    for s, e, k in _blocks(plan):
        xs, ys = np.asarray(x[s:e], dtype=np.float64), np.asarray(y[s:e], dtype=np.float64)
        f, pxx = sps.welch(xs, **kw)
        _, pyy = sps.welch(ys, **kw)
        _, pxy = sps.csd(xs, ys, **kw)
        part = np.stack([pxx.astype(complex), pyy.astype(complex), pxy])
        acc = part * k if acc is None else acc + part * k
        total += k
    assert acc is not None
    acc /= total
    return f, acc[0].real, acc[1].real, acc[2]


def spectrogram(x: np.ndarray, fs: float, nperseg: int, window: str = "hann", max_frames: int = 600,
                fmax: float | None = None):
    """Density spectrogram (unit^2/Hz, one-sided, constant-detrended frames).

    The frame hop is nperseg/2, enlarged for long signals so at most
    4*max_frames frames are computed (bounded memory and time). The frames are
    then max-pooled to <= max_frames, so short events stay visible. When the
    hop exceeds nperseg (very long captures), samples between frames are not
    displayed; this is a display product, never used for evidence. Returns
    (f, t, Sxx[f, t]); t is the frame-centre time."""
    n = len(x)
    nperseg = int(min(nperseg, max(16, n)))
    if n < 16:
        return np.zeros(0), np.zeros(0), np.zeros((0, 0))
    hop = max(nperseg // 2, int(math.ceil((n - nperseg) / max(1, 4 * max_frames))))
    starts = np.arange(0, n - nperseg + 1, hop)
    w = sps.get_window(window, nperseg, fftbins=True)
    scale = 1.0 / (fs * np.sum(w * w))
    f = np.fft.rfftfreq(nperseg, 1 / fs)
    keep = f <= fmax if fmax is not None else np.ones_like(f, bool)
    cols = []
    idx = np.arange(nperseg)
    for i in range(0, len(starts), 256):
        fr = np.asarray(x[starts[i : i + 256, None] + idx], dtype=np.float64)
        fr = (fr - fr.mean(axis=1, keepdims=True)) * w
        s = (np.abs(np.fft.rfft(fr, axis=1)) ** 2) * scale
        s[:, 1 : (nperseg + 1) // 2] *= 2.0  # one-sided: double all but DC (and Nyquist for even nperseg)
        cols.append(s[:, keep].T)
    sxx = np.concatenate(cols, axis=1)
    t = (starts + nperseg / 2) / fs
    if sxx.shape[1] > max_frames:
        g = int(math.ceil(sxx.shape[1] / max_frames))
        m = sxx.shape[1] // g
        sxx = sxx[:, : m * g].reshape(sxx.shape[0], m, g).max(axis=2)
        t = t[: m * g].reshape(m, g).mean(axis=1)
    return f[keep], t, sxx


def integrate_band(f: np.ndarray, psd: np.ndarray, lo: float, hi: float) -> float:
    """Power (unit^2) in [lo, hi) with fractional-bin weighting (INV-008).

    Bin k covers [f_k - df/2, f_k + df/2], clipped at 0 Hz and at Nyquist, so
    adjacent bands sum exactly to the band over their union."""
    if len(f) < 2 or hi <= lo:
        return 0.0
    df = f[1] - f[0]
    left = np.maximum(f - df / 2, 0.0)
    right = np.minimum(f + df / 2, f[-1])
    overlap = np.clip(np.minimum(right, hi) - np.maximum(left, lo), 0.0, None)
    return float(np.sum(psd * overlap))


def fractional_octave_bands(kind: str, fmin: float, fmax: float) -> list[tuple[float, float, float]]:
    """Base-10 IEC 61260-1 bands as (low, centre, high) inside [fmin, fmax].
    Third-octave: fm = 1000*10^(k/10). Octave: fm = 1000*10^(3k/10).
    Edges are fm*10^(+/-1/20) and fm*10^(+/-3/20) respectively."""
    step, half = (1, 1 / 20) if kind == "third_octave" else (3, 3 / 20)
    out = []
    for k in range(-30, 15, step):
        fm = 1000.0 * 10 ** (k / 10)
        lo, hi = fm * 10 ** (-half), fm * 10 ** half
        if lo >= fmin and hi <= fmax:
            out.append((lo, fm, hi))
    return out


def band_levels(f: np.ndarray, psd: np.ndarray, kind: str, fmin: float, fmax: float) -> list[tuple[float, float, float, float, bool]]:
    """Returns (low, centre, high, power, valid) for each band. A band is invalid
    when it is narrower than two PSD bins (resolution-limited)."""
    if len(f) < 2:
        return []
    df = f[1] - f[0]
    res = []
    for lo, fm, hi in fractional_octave_bands(kind, max(fmin, df), fmax):
        p = integrate_band(f, psd, lo, hi)
        res.append((lo, fm, hi, p, (hi - lo) >= 2 * df))
    return res
