# 07 Synchronization

Code: `src/sonicclue/sync/__init__.py`; app `align_captures`; CLI `align`; GUI Before/after → "Align (multi-device)". Tests: `tests/test_calibration_sync.py` (sync), `tests/test_workflows.py::test_align_two_independent_devices_via_import`.

## 1 Principles

* Channels in one capture share one converter clock (`sync_basis = shared_clock`). Cross-channel analysis is eligible when averaging is sufficient.
* Separate devices have **independent clocks**. Equal nominal sample rates do **not** imply synchronization. They are related only through an estimated `ClockMapping` with stated uncertainty.
* When timing accuracy is insufficient, only independent spectral comparison is allowed.

## 2 Clock mapping model (CON-008)

`t_ref = offset_s + (1 + drift_ppm*1e-6) * n_other / fs_other`, valid on `[valid_from_s, valid_to_s]`. The mapping records `basis` (shared_clock, common_event, hardware_timestamp, host_timestamp), `residual_s` (1σ timing uncertainty), `ambiguity_ratio`, `eligible_max_freq_hz` and `method`.

## 3 Estimation algorithm (`estimate_mapping`)

1. If nominal rates differ by > 0.1%, resample `other` to the reference rate (polyphase; flag MISMATCHED_RATE).
2. Split the overlap into K = 6 windows (≥ 0.5 s each) and estimate each window's delay by FFT cross-correlation (search ±0.5 s), refined parabolically.
3. Clock-reset test: any window-to-window delay step > max(20 × median step, 50 samples) means a clock reset or dropout (CLOCK_RESET, mapping rejected).
4. Least-squares fit of offset + drift. If 0.5 < |drift| < 2000 ppm, correct the drift (FFT resampling) and re-estimate (second pass), because drift inside a window smears the correlation peak. Residual RMS → σ_t, floored at 0.1 sample.
5. |drift| > 2000 ppm is physically implausible for audio converters: SYNC_INSUFFICIENT, mapping rejected.
6. Ambiguity: the largest secondary correlation peak (outside ±0.5 ms) divided by the main peak. If > 0.8 (periodic signals), SYNC_AMBIGUOUS, mapping rejected.

Alignment (`align`): integer shift plus a frequency-domain fractional shift (rounding to whole samples would decorrelate broadband content), drift correction, and the outer 1% of the overlap marked invalid.

## 4 Eligibility (exact conditions)

Synchronized analysis (coherence, transfer function, delay) between two signals is allowed only if **all** hold:

| Condition | Shared clock (one capture) | Aligned captures |
|---|---|---|
| no CLOCK_RESET / SYNC_AMBIGUOUS / SYNC_INSUFFICIENT | n/a | required |
| frequency range | ≤ analysis fmax | ≤ `eligible_max_freq_hz` = 0.35 rad / (2π σ_t) (≤ 20° phase error, 1σ) |
| independent averages over the common valid data | ≥ `min_averages` (8) | ≥ 8 |
| both channels free of INVALID silence/short flags | required | required |
| coherence reported only where γ² > max(threshold(n_eff, α=0.05), 0.5) | required | required |

Otherwise the CrossChannelResult is `eligible=false` with a reason, and no coherence evidence is produced (ADV-009).

## 5 Gaps, phase uncertainty, host timestamps

Gaps are invalid for both signals (common mask). A zero-length `input_overflow` gap inside an aligned span makes the mapping suspect: the reset test usually triggers, and the user is told to re-record. Phase uncertainty at frequency f is 2πfσ_t (reported implicitly through `eligible_max_freq_hz`). Host or bridge timestamps are checked by `check_timestamps` (non-increasing → CLOCK_RESET; > 5% period deviation → NONUNIFORM_TIMESTAMPS). They are never used as the sole basis for synchronized analysis.

## 6 Measured accuracy (synthetic, build VM)

White-noise reference, 30 s, 12.3 ms offset, 40 ppm drift: offset error 2.8 µs, drift 40.3 ppm, σ_t 2.2 µs → eligible to 24 kHz (Nyquist-limited). Periodic 100 Hz sine: ambiguous → rejected. 190 ms step at 20 s: CLOCK_RESET → rejected. Unrelated recordings: rejected. Physical two-device validation is UNEXECUTED (needs hardware, spec 18 HQ-05).
