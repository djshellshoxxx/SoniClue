# 08 DSP and numerical methods

Code: `src/sonicclue/dsp/`, `src/sonicclue/analysis/pipeline.py` (ALGORITHM_VERSION 1.0.0). Tests: `tests/test_dsp_numerics.py`, reference vectors `test-vectors/vectors.json` (`tools/gen_test_vectors.py --check`), runtime `sonicclue-cli selftest`.

All modules are pure functions of their inputs: no GUI, device or database. Floating-point tolerances (below) are kept separate from physical measurement uncertainty (spec 09 section 6, spec 06 section 2).

## 1 Signal model and preprocessing

Input: float32 FS samples per channel. Screening (section 8) produces a validity mask, excluding non-finite samples, gaps and clipping ±10 ms. Calibration scales by 1/sensitivity (INV-006). DC is removed per segment (`detrend="constant"`). No other preprocessing alters data.

## 2 Algorithms

| Algorithm | Definition / convention | Assumptions | Input & sampling | Resolution / cost | Failure conditions | Reference impl. |
|---|---|---|---|---|---|---|
| Segment planning | nperseg = largest 2^k ≤ fs/resolution, halved until n_eff ≥ min_averages, never below 256 | stationarity over the capture | validity mask | O(1) | no run ≥ 256 samples → SHORT_CAPTURE (no spectra) | own (tested) |
| Welch PSD | one-sided density, unit²/Hz, `scipy.signal.welch(scaling="density")`, Hann default, 50% overlap, block-wise over valid runs, weighted pooling | wide-sense stationary | valid runs | df = fs/nperseg; O(N log nperseg) | INSUFFICIENT_AVERAGES warning | SciPy |
| Window metrics | CG = Σw/N; ENBW = N·Σw²/(Σw)² bins | periodic window | | | | Heinzel et al. |
| Noise floor | running median (61 bins) of PSD in dB | tones are narrower than 61 bins | PSD | O(N) | | own |
| Tone detection | local maxima with prominence ≥ threshold over the floor; parabolic interpolation in dB; power = Σ PSD over ±h main-lobe bins × df (h: hann 3, hamming 3, blackman-harris 5, flattop 6, boxcar 2) | tones separated by > 2h bins | PSD | | close tones merge (strongest kept) | own (tested vs closed form) |
| Q factor | f0 / BW(-3 dB) if BW > 2·ENBW, else "resolution-limited" | single isolated peak | PSD | | | own |
| Harmonic families | f0 a detected tone; orders k with \|f - k f0\| ≤ max(1.5 df, 0.5% k f0); mains if f0 within 1% of 50/100 or 60/120 Hz | | tones | | missing fundamental not inferred | own |
| Transients | 10 ms frame RMS; event if > median + max(8 dB, 6·MAD); merge gaps < 2 frames; periodic if ≥ 4 events and CV(intervals) < 0.25 | background roughly stationary | samples, mask | O(N) | | own |
| Envelope spectrum | \|Hilbert(bandpassed x)\|, mean removed, decimated, Welch, 20 s blocks averaged | modulation < fmax (200 Hz) | samples | | | SciPy |
| Spectrogram | density, Hann, hop nperseg/2 (enlarged for long signals), max-pooled to ≤ 600 frames; display only | | samples | | | own (equals SciPy when hop = nperseg/2; tested) |
| Fractional-octave bands | base-10 IEC 61260-1: third-octave fm = 1000·10^(k/10), edges fm·10^(±1/20); octave fm = 1000·10^(3k/10), edges ·10^(±3/20); fractional-bin integration | | PSD | | band < 2 bins wide → invalid | own |
| Cross-spectra | Pxy = E[conj(X)·Y] (SciPy orientation, verified in source) | shared clock or aligned | two signals, common mask | | | SciPy |
| Coherence | γ² = \|Pxy\|²/(Pxx·Pyy); bins with Pxx or Pyy < 1e-12·max masked (NaN) | | | | n_eff < 2 → threshold 1 | Bendat & Piersol |
| Coherence significance | γ²_crit = 1 - α^(1/(n_eff-1)), α = 0.05; reported only above max(γ²_crit, 0.5) | independent segments (n_eff = non-overlapping count, conservative) | | | | Bendat & Piersol |
| Transfer function | H1 = Pxy/Pxx; phase(H1) = -2πfτ when y lags x by τ | noise on output only (H1) | | | masked bins NaN | |
| Delay | FFT cross-correlation peak, parabolic refinement, search ±0.1 s (in-capture) / ±0.5 s (alignment); ambiguity = 2nd peak / main peak | broadband content | | O(N log N) | ambiguity > 0.8 → invalid | SciPy |
| Resampling | `resample_poly` with rational ratio (denominator ≤ 1000), zero-phase FIR; edge transient reported | | | | | SciPy |
| Drift correction | FFT resampling to len/(1 + ppm·1e-6); 1% edges invalid | | | | | SciPy |
| Velocity | S_v = S_a/(2πf)²; f < 2 Hz → NaN | | | | | closed form |
| Level comparison | see section 9 | | | | | own, SciPy t-dist |

## 3 Numerical invariant catalog

| ID | Statement | Test signal | Independent reference | FP tolerance | Must-fail counterexample | Test |
|---|---|---|---|---|---|---|
| INV-001 | dB references per ISO 1683; 94 dB SPL = 1.00237 Pa; power↔dB round trip; zero → floor (-300 dB), not -inf | constants | closed form | 1e-12 rel | — | `test_inv001_*`, TV-012 |
| INV-002 | sine amplitude A → RMS A/√2, peak A, DC 0 | sine | closed form | 1e-6 rel | — | `test_inv002_sine_rms` |
| INV-003 | Parseval: Σ PSD·df = var(x) for all windows; one-sided doubling excludes DC and Nyquist | white noise; 64-point random | direct DFT sum | 2% (estimator) / 1e-10 (DFT) | — | `test_inv003_*`, TV-002 |
| INV-004 | ENBW per window; tone power A²/2 recovered for all windows and bin offsets (0, ¼, ½ bin) | off-bin sines | closed form | 1% (0.04 dB) | — | `test_inv004_*`, TV-001, TV-003..007 |
| INV-005 | Pxy orientation and phase sign: y = x(t-τ) → phase -2πfτ; swapping channels flips the sign | delayed white noise | closed form | 0.05 rad | swapped-channel test must give +2πfτ | `test_inv005_*`, TV-008 |
| INV-006 | Calibration direction: physical = FS/sensitivity; 80 dB SPL tone reads 80.0 dB; response files negated | calibrator sines | closed form | 0.1 dB | gain mismatch must refuse calibration | `test_inv006_*`, `test_fr_file_direction_*` |
| INV-007 | Resampling passband gain 1 within 0.1%; edge transient reported | 1 kHz sine 44.1→48 kHz | closed form | 1e-3 | — | `test_inv007_*` |
| INV-008 | Band additivity: P[a,b) + P[b,c) = P[a,c) exactly; white-noise band power ∝ bandwidth | white noise | arithmetic | 1e-12 / 5% | — | `test_inv008_*` |
| INV-009 | Provenance: every AnalysisResult names capture id, config, algorithm version, excluded frame count | pipeline | contract | — | schema rejects missing fields | contract tests |
| INV-010 | Gap exclusion: PSD of a signal with zeroed dropouts equals the clean variance | white noise + gaps | clean variance | 3% | naive (non-excluding) analysis under-reads by > 10% | `test_inv010_*` |
| INV-011 | Masked bins are NaN, never numeric ratios; coherence threshold 1 at n = 1 | crafted spectra | definition | exact | single-segment coherence of independent noise is ~1 | `test_inv011_*`, `test_adv009_*`, TV-009..011 |
| INV-012 | Optimisations preserve results: blocked Welch equals a single call; custom spectrogram equals SciPy | white noise | SciPy | 1e-10 / 1e-9 | — | `test_blocked_welch_*`, `test_spectrogram_*` |

## 4 Edge-case behaviour

| ID | Condition | Behaviour | Flag | Test |
|---|---|---|---|---|
| EDGE-001 | silence (all zeros) | no spectra conclusions; level = floor | SILENCE (invalid) | `test_edge_screening_*` |
| EDGE-002 | constant (DC-only) signal | DC removed; treated as silence | SILENCE + DC_OFFSET | same |
| EDGE-003 | capture shorter than one 256-sample segment | no PSD/tones/bands | SHORT_CAPTURE (invalid) | `test_segment_plan_short_*` |
| EDGE-004 | extreme low amplitude (1e-6 FS) | finite results, correct tone power | LOW_SIGNAL if < -80 dBFS | `test_extreme_amplitudes_finite` |
| EDGE-005 | clipping | ±10 ms around clipped samples excluded; absolute levels marked unreliable | CLIPPING (invalid) | `test_edge_screening_*`, `test_clipped_capture_*` |
| EDGE-006 | NaN / ±inf samples | excluded from all statistics | NONFINITE (invalid) | `test_edge_screening_*` |
| EDGE-007 | non-uniform timestamps (bridge/host) | flagged; never used for sync | NONUNIFORM_TIMESTAMPS | `test_bridge_nonuniform_*`, `test_timestamp_checks` |
| EDGE-008 | missing blocks (dropouts) | zero-filled, excluded | DROPOUT_GAP | `test_queue_overflow_*`, `test_inv010_*` |
| EDGE-009 | clock reset | mapping rejected / stream flagged | CLOCK_RESET (invalid) | `test_sync_clock_reset_*`, `test_bridge_crc_*` |
| EDGE-010 | mismatched sample rates | resampled before alignment; comparison caveat | MISMATCHED_RATE | `test_sync_mismatched_*` |
| EDGE-011 | insufficient averaging | spectra computed with a warning; coherence ineligible | INSUFFICIENT_AVERAGES | `test_adv009_*` |
| EDGE-012 | frequencies outside calibration bounds | uncorrected, peaks `cal_in_band=false`, bands invalid | CAL_OUT_OF_BAND | `test_fr_correction_*` |
| EDGE-013 | tone near Nyquist | alias check recommended | ALIAS_RISK | `test_adv006_*` |

## 5 Tolerances vs physical uncertainty

Floating-point tolerances are listed per test (rtol/atol) and justified by the algorithm (estimator variance for random fixtures, machine precision for deterministic identities). Physical uncertainty is a separate field everywhere it is reported: calibration `uncertainty_db` (k=2), comparison `overall_uncertainty_db` (95%), clock mapping `residual_s`. The two are never merged.

## 6 Comparison statistics (section 9 of master prompt 4.3, "statistical repeatability")

Delta = mean(B) - mean(A) in dB. With ≥ 2 captures per side: 95% Welch-Satterthwaite t-interval on per-capture levels ("measured"). With one per side: 2·sqrt(sd_a² + sd_b²), where sd = 4.343/sqrt(n_eff·B) for a band of B effective bins, floored at 0.5 dB ("estimated"). Tone sd = max(0.1, 4.343·2·sqrt(Pn/Pt)/sqrt(n_eff)). Significant only if |delta| > max(u95, 1 dB minimum practical effect).

## 7 Computational cost (measured, spec 16)

60 s × 2 ch @ 48 kHz full analysis: 2.0 s, 305 MB peak RSS. 600 s × 2 ch: 17 s, 0.92 GB (after block-wise optimisation; previously 25 s, 3.27 GB).

## 8 Quality gating of analyses

INVALID flags exclude the affected data (mask) or analysis (no spectra for SHORT_CAPTURE/SILENCE; no calibration for CAL_GAIN_MISMATCH; AGC_ACTIVE and CLIPPING invalidate level comparisons). WARNING flags are shown and propagate to reports.
