"""Synchronization between independently clocked captures (docs/specs/07-synchronization.md).

Model: t_ref = offset_s + (1 + drift_ppm*1e-6) * n_other / fs_other.

Method for ``estimate_mapping`` (common-event or common-signal alignment):

1. If the nominal rates differ by more than 0.1%, resample ``other`` to the
   reference rate first (MISMATCHED_RATE flag; resampling is recorded).
2. Split the overlap into K windows (default 6). In each window, estimate the
   local delay by cross-correlation with ``max_lag_s`` limited search.
3. Fit offset + drift by least squares over window centres. If the drift is
   plausible, correct it and re-estimate (a second pass sharpens the
   correlation peaks). The residual RMS is the timing uncertainty sigma_t. A
   window-to-window delay step larger than max(20 x median step, 50 samples)
   indicates a clock reset or dropout (CLOCK_RESET; mapping rejected). A drift
   above 2000 ppm is implausible and is rejected (SYNC_INSUFFICIENT).
4. Ambiguity: the worst per-window correlation ambiguity ratio. Above 0.8 the
   alignment is ambiguous (periodic signals) and no synchronized analysis is
   allowed.
5. Eligibility: synchronized cross-channel analysis is allowed up to
   f_max = PHASE_BUDGET_RAD / (2*pi*sigma_t). With a 0.35 rad (20 degree)
   budget and sigma_t floored at 0.1 sample, aligned audio at 48 kHz can reach
   about 27 kHz in principle; poor alignment pulls f_max down to the band
   where phase is still trustworthy. Outside it, only independent spectral
   comparison is valid.

Channels inside one capture share one converter clock (``shared_clock``) and
are eligible without estimation. Two separate devices are *never* assumed to
be synchronized because their nominal rates match.
"""

from __future__ import annotations

import uuid

import numpy as np

from ..domain.model import ClockMapping, QualityCode, QualityFlag, Severity, utcnow
from ..dsp.cross import estimate_delay
from ..dsp.resample import correct_drift, resample_rational

PHASE_BUDGET_RAD = 0.35
AMBIGUITY_LIMIT = 0.8


def shared_clock_mapping(capture_id: str, duration_s: float, fs: float) -> ClockMapping:
    return ClockMapping(id=f"clk-{uuid.uuid4().hex[:10]}", reference_capture_id=capture_id, other_capture_id=capture_id,
                        basis="shared_clock", offset_s=0.0, drift_ppm=0.0, residual_s=0.0, ambiguity_ratio=0.0,
                        valid_to_s=duration_s, eligible_max_freq_hz=fs / 2, method="same converter clock",
                        created_utc=utcnow())


def estimate_mapping(ref: np.ndarray, fs_ref: float, other: np.ndarray, fs_other: float, *, ref_id: str, other_id: str,
                     windows: int = 6, max_lag_s: float = 0.5) -> tuple[ClockMapping, list[QualityFlag], np.ndarray]:
    """Returns (mapping, flags, other resampled to fs_ref). See module docstring."""
    flags: list[QualityFlag] = []
    o = np.asarray(other, float)
    if abs(fs_other - fs_ref) / fs_ref > 1e-3:
        o, _achieved, _edge = resample_rational(o, fs_other, fs_ref)
        flags.append(QualityFlag(code=QualityCode.MISMATCHED_RATE, severity=Severity.WARNING,
                                 message=f"rates differ ({fs_other:g} vs {fs_ref:g} Hz); other capture resampled before alignment"))
    n = min(len(ref), len(o))

    def window_delays(sig):
        win = n // windows
        cs, ds, am = [], [], []
        for k in range(windows):
            a, b = k * win, (k + 1) * win
            if b - a < int(0.5 * fs_ref):
                continue
            d, amb = estimate_delay(ref[a:b], sig[a:b], fs_ref, max_lag_s=max_lag_s)
            if d is None:
                continue
            cs.append((a + b) / 2 / fs_ref)
            ds.append(d)
            am.append(amb)
        return np.array(cs), np.array(ds), am

    c, dl, ambs = window_delays(o)
    if len(dl) < 2:
        m = ClockMapping(id=f"clk-{uuid.uuid4().hex[:10]}", reference_capture_id=ref_id, other_capture_id=other_id,
                         basis="common_event", offset_s=0.0, drift_ppm=0.0, residual_s=1.0, ambiguity_ratio=1.0,
                         valid_to_s=n / fs_ref, eligible_max_freq_hz=0.0, method="windowed cross-correlation (failed)",
                         created_utc=utcnow())
        flags.append(QualityFlag(code=QualityCode.SYNC_INSUFFICIENT, severity=Severity.INVALID,
                                 message="not enough common signal to align the captures"))
        return m, flags, o
    # Clock reset / dropout: a step between consecutive windows that is far larger
    # than the steady drift step (drift alone gives near-constant small steps).
    dd = np.abs(np.diff(dl))
    reset = len(dd) >= 2 and float(np.max(dd)) > max(20 * float(np.median(dd)), 50.0 / fs_ref)
    # y(t) = x(t - d): the other stream shows reference events d seconds late. A
    # drift makes d grow linearly: d(t) = d0 + drift*t.
    A = np.vstack([np.ones_like(c), c]).T
    coef, *_ = np.linalg.lstsq(A, dl, rcond=None)
    if not reset and abs(coef[1]) * 1e6 > 0.5 and abs(coef[1]) * 1e6 < 2000:
        # Second pass: remove the estimated drift and re-measure. Drift inside each
        # window smears the correlation peak; correcting it sharpens the estimate.
        o2 = correct_drift(o, coef[1] * 1e6)
        c2, dl2, ambs2 = window_delays(o2)
        if len(dl2) >= 2:
            coef2, *_ = np.linalg.lstsq(np.vstack([np.ones_like(c2), c2]).T, dl2, rcond=None)
            c, dl, ambs = c2, dl2, ambs2
            A = np.vstack([np.ones_like(c), c]).T
            coef = np.array([coef2[0], coef[1] + coef2[1]])
            resid_fit = dl - (coef2[0] + coef2[1] * c)
        else:
            resid_fit = dl - A @ coef
    else:
        resid_fit = dl - A @ coef
    sigma = float(np.sqrt(np.mean(resid_fit**2))) if len(dl) > 2 else 0.0
    sigma = max(sigma, 0.1 / fs_ref)
    amb = float(max(ambs))
    fmax = PHASE_BUDGET_RAD / (2 * np.pi * sigma)
    if amb > AMBIGUITY_LIMIT:
        fmax = 0.0
        flags.append(QualityFlag(code=QualityCode.SYNC_AMBIGUOUS, severity=Severity.INVALID,
                                 message=f"alignment ambiguous (correlation ratio {amb:.2f}); periodic signals give many equal lags"))
    if reset:
        fmax = 0.0
        flags.append(QualityFlag(code=QualityCode.CLOCK_RESET, severity=Severity.INVALID,
                                 message="timing jump between windows: clock reset or dropout; captures cannot be aligned as one mapping"))
    drift_ppm = float(coef[1] * 1e6)
    if abs(drift_ppm) > 2000:
        # Real converter clocks differ by tens of ppm; thousands means the "drift"
        # is a timing jump or a wrong correlation peak, not a clock rate.
        fmax = 0.0
        if not reset:
            flags.append(QualityFlag(code=QualityCode.SYNC_INSUFFICIENT, severity=Severity.INVALID,
                                     message=f"implausible clock drift ({drift_ppm:.0f} ppm): alignment rejected"))
        drift_ppm = max(-2000.0, min(2000.0, drift_ppm))
    fmax = float(min(fmax, fs_ref / 2))
    if 0 < fmax < fs_ref / 2:
        flags.append(QualityFlag(code=QualityCode.SYNC_UNVERIFIED, severity=Severity.WARNING,
                                 message=f"synchronized analysis limited to below {fmax:.0f} Hz (timing uncertainty {sigma*1e6:.1f} us)"))
    m = ClockMapping(id=f"clk-{uuid.uuid4().hex[:10]}", reference_capture_id=ref_id, other_capture_id=other_id,
                     basis="common_event", offset_s=float(coef[0]), drift_ppm=drift_ppm, residual_s=sigma,
                     ambiguity_ratio=amb, valid_to_s=n / fs_ref, eligible_max_freq_hz=fmax,
                     method=f"windowed cross-correlation, {len(dl)} windows, least-squares offset+drift",
                     created_utc=utcnow())
    return m, flags, o


def align(other_at_ref_rate: np.ndarray, mapping: ClockMapping, fs_ref: float, n_ref: int) -> tuple[np.ndarray, np.ndarray]:
    """Shift and drift-correct ``other`` onto the reference timeline. Returns
    (aligned signal of length n_ref, validity mask). Samples without data, and
    the 1% drift-correction edges, are invalid."""
    o = other_at_ref_rate
    if abs(mapping.drift_ppm) > 0.01:
        o = correct_drift(o, mapping.drift_ppm)
    exact = mapping.offset_s * fs_ref
    shift = int(np.floor(exact))
    frac = exact - shift
    if frac > 1e-6:
        # Advance by the fractional part with a frequency-domain phase shift.
        # Rounding to whole samples would decorrelate broadband content
        # (a half-sample error halves the coherence near Nyquist).
        spec = np.fft.rfft(o)
        f = np.fft.rfftfreq(len(o))
        o = np.fft.irfft(spec * np.exp(2j * np.pi * f * frac), len(o))
    out = np.zeros(n_ref)
    valid = np.zeros(n_ref, bool)
    # other[n] corresponds to ref[n - shift] when other lags by shift
    src_start = max(0, shift)
    dst_start = max(0, -shift)
    m = min(len(o) - src_start, n_ref - dst_start)
    if m > 0:
        out[dst_start : dst_start + m] = o[src_start : src_start + m]
        valid[dst_start : dst_start + m] = True
        e = int(0.01 * m)
        valid[dst_start : dst_start + e] = False
        valid[dst_start + m - e : dst_start + m] = False
    return out, valid


def check_timestamps(times_s: np.ndarray, nominal_period_s: float, tol: float = 0.05) -> list[QualityFlag]:
    """Host/bridge timestamp sanity: monotonic and roughly uniform."""
    flags = []
    if len(times_s) < 2:
        return flags
    d = np.diff(times_s)
    if np.any(d <= 0):
        flags.append(QualityFlag(code=QualityCode.CLOCK_RESET, severity=Severity.INVALID,
                                 message=f"{int(np.sum(d <= 0))} non-increasing timestamps"))
    bad = np.abs(d - nominal_period_s) > tol * nominal_period_s
    if np.any(bad & (d > 0)):
        flags.append(QualityFlag(code=QualityCode.NONUNIFORM_TIMESTAMPS, severity=Severity.WARNING,
                                 message=f"{int(np.sum(bad))} timestamp intervals deviate >{tol*100:.0f}% from nominal"))
    return flags
