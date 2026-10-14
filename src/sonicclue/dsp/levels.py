"""Time-domain levels and raw-signal quality screening (EDGE-001..EDGE-006).

Screening runs on the *raw FS samples*, before any calibration, because
clipping and silence are properties of the converter, not of the physical
quantity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..domain.model import QualityCode, QualityFlag, Severity

CLIP_LEVEL = 0.999  # |x| >= this counts as clipped (float32 FS)
NEAR_CLIP_LEVEL = 0.89  # about -1 dBFS peak
SILENCE_RMS = 1e-7  # -140 dBFS: digital silence or muted input
LOW_SIGNAL_RMS = 1e-4  # -80 dBFS
DC_OFFSET_LIMIT = 0.01
CLIP_GUARD_S = 0.010  # samples within this distance of clipping are excluded from spectra


@dataclass
class Screening:
    valid: np.ndarray  # bool mask of samples usable for spectral analysis
    flags: list[QualityFlag] = field(default_factory=list)
    clipped_samples: int = 0
    nonfinite_samples: int = 0


CHUNK = 1 << 21  # samples per pass in chunked reductions (bounded temporaries for long captures)


def _masked_moments(x: np.ndarray, valid: np.ndarray) -> tuple[int, float, float, float]:
    """(count, mean, std, peak |x - mean|) over valid samples, computed in chunks
    (two passes) so no full-length float64 temporaries are created."""
    n_ok, s1 = 0, 0.0
    for i in range(0, len(x), CHUNK):
        v = np.asarray(x[i : i + CHUNK], dtype=np.float64)[valid[i : i + CHUNK]]
        n_ok += v.size
        s1 += float(v.sum())
    if n_ok == 0:
        return 0, 0.0, 0.0, 0.0
    mean = s1 / n_ok
    s2, pk = 0.0, 0.0
    for i in range(0, len(x), CHUNK):
        v = np.asarray(x[i : i + CHUNK], dtype=np.float64)[valid[i : i + CHUNK]] - mean
        if v.size:
            s2 += float(np.dot(v, v))
            pk = max(pk, float(np.max(np.abs(v))))
    return n_ok, mean, math.sqrt(s2 / n_ok), pk


def screen_channel(x: np.ndarray, fs: float, channel: int, gaps: list[tuple[int, int]] = ()) -> Screening:
    n = len(x)
    valid = np.empty(n, bool)
    for i in range(0, n, CHUNK):
        valid[i : i + CHUNK] = np.isfinite(np.asarray(x[i : i + CHUNK]))
    flags: list[QualityFlag] = []
    nf = int(n - np.count_nonzero(valid))
    if nf:
        flags.append(QualityFlag(code=QualityCode.NONFINITE, severity=Severity.INVALID, channel=channel,
                                 message=f"{nf} non-finite samples (NaN/inf) excluded"))
    for a, b in gaps:
        valid[a:b] = False
    guard = max(1, int(CLIP_GUARD_S * fs))
    nclip, first, last = 0, 0, 0
    for i in range(0, n, CHUNK):
        c = np.asarray(x[i : i + CHUNK])
        with np.errstate(invalid="ignore"):
            hit = np.flatnonzero(np.abs(c) >= CLIP_LEVEL) + i
        if not hit.size:
            continue
        if not nclip:
            first = int(hit[0])
        last = int(hit[-1])
        nclip += int(hit.size)
        # exclude [idx-guard, idx+guard] around each clipped sample: merge overlapping
        # intervals within the chunk, then clear them (memory bounded by the chunk)
        lo, hi = np.clip(hit - guard, 0, n), np.clip(hit + guard + 1, 0, n)
        brk = np.flatnonzero(lo[1:] > hi[:-1]) + 1
        for u, v in zip(lo[np.r_[0, brk]], hi[np.r_[brk - 1, len(hit) - 1]]):
            valid[u:v] = False
    if nclip:
        flags.append(QualityFlag(code=QualityCode.CLIPPING, severity=Severity.INVALID, channel=channel,
                                 start_frame=first, end_frame=last + 1,
                                 message=f"{nclip} clipped samples; surrounding {CLIP_GUARD_S*1000:.0f} ms excluded from spectra, "
                                         "absolute levels and harmonic content are unreliable"))
    cnt, mean, ac_rms, _pk = _masked_moments(x, valid)
    peak = 0.0
    for i in range(0, n, CHUNK):
        v = np.asarray(x[i : i + CHUNK])[valid[i : i + CHUNK]]
        if v.size:
            peak = max(peak, float(np.max(np.abs(v))))
    if not nclip and peak >= NEAR_CLIP_LEVEL:
        flags.append(QualityFlag(code=QualityCode.NEAR_CLIPPING, severity=Severity.WARNING, channel=channel,
                                 message=f"peak {20*math.log10(peak):.1f} dBFS is close to full scale; reduce gain"))
    if cnt:
        if ac_rms < SILENCE_RMS:
            flags.append(QualityFlag(code=QualityCode.SILENCE, severity=Severity.INVALID, channel=channel,
                                     message="no AC signal (digital silence, muted input or constant value)"))
        elif ac_rms < LOW_SIGNAL_RMS:
            flags.append(QualityFlag(code=QualityCode.LOW_SIGNAL, severity=Severity.WARNING, channel=channel,
                                     message=f"very low signal ({20*math.log10(ac_rms):.0f} dBFS RMS); converter noise may dominate"))
        if abs(mean) > DC_OFFSET_LIMIT:
            flags.append(QualityFlag(code=QualityCode.DC_OFFSET, severity=Severity.WARNING, channel=channel,
                                     message=f"DC offset {mean:+.3f} FS (removed before spectral analysis)"))
    return Screening(valid=valid, flags=flags, clipped_samples=nclip, nonfinite_samples=nf)


def level_stats(x: np.ndarray, valid: np.ndarray) -> tuple[float, float, float]:
    """(ac_rms, peak, dc) over valid samples. The RMS excludes DC: a DC offset
    is a converter property, not sound or vibration."""
    _cnt, mean, std, pk = _masked_moments(x, valid)
    return std, pk, mean
