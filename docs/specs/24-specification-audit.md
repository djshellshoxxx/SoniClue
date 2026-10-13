# 24 Specification audit

Audit date 2026-10-12, performed by the coordinator session that also wrote the code. **Independence limitation (RISK-014):** no separate reviewing agent was available in this environment, so the audits below are self-audits backed by automated tests and counterexamples. An independent review of specs 08 and 09 is backlog TASK-042.

Finding format: ID → severity → affected requirement → evidence → impact → correction → verification.

## 1 Audits performed

| # | Audit | Method | Result |
|---|---|---|---|
| 1 | Product completeness | master prompt §5-§20 checklist against `requirement-coverage.csv` | all R1 requirements implemented; hardware-dependent items UNEXECUTED; ASIO/ML/signing/licence BLOCKED |
| 2 | Scientific correctness | invariant catalog, independent references, counterexamples | F-17 fixed; INV-001..012 pass |
| 3 | Numerical methods and units | dB references, PSD scaling, calibration direction tests | pass |
| 4 | Sensor accuracy and calibration | calibrator rejection paths, relative-only enforcement, gain validity | pass (software); HQ-04/07 UNEXECUTED |
| 5 | Timing and synchronization | offset/drift/reset/ambiguity/unrelated tests | F-02, F-03 fixed |
| 6 | Diagnostic reasoning validity | ADV-001..010, demo ground truth | F-04, F-05, F-06, F-07, F-08 fixed |
| 7 | Modular architecture | AST dependency test (fails on injected violation); reusable-import test | F-16 fixed |
| 8 | Public interface completeness | 20 schemas, 47 examples, two validators | pass |
| 9 | State machines and concurrency | SM-001/003/004 transition tests; double start/stop; overflow; device loss | F-01 fixed |
| 10 | Data integrity | immutability, checksums, recovery, migration backup, damaged documents | pass |
| 11 | GUI/backend connectivity | feature-wiring matrix; offscreen GUI flow test | F-10, F-11, F-12 fixed |
| 12 | Security and privacy | untrusted-input table; archive attack fixtures; network import review | F-13 fixed |
| 13 | Licensing | dependency inventory from installed metadata; LGPL strategy | open: licence decision (BLOCKED) |
| 14 | Performance feasibility | benchmarks + profiling | F-09 fixed; reference hardware pending |
| 15 | Testing completeness | requirement → test mapping; must-fail per gate | pass; hardware tests UNEXECUTED |
| 16 | Build and deployment readiness | frozen-bundle smoke in a clean environment | Linux pass; F-15 fixed; Windows via CI |
| 17 | Development dependency ordering | milestone/backlog graph | pass |
| 18 | Multi-agent integration readiness | ownership map, contract owner, handoff | pass |

## 2 Findings corrected in this session

| ID | Sev | Req | Evidence | Impact | Correction | Verification |
|---|---|---|---|---|---|---|
| F-01 | High | REQ-ACQ-005 | `test_queue_overflow_*`: 108 544 frames for a 96 000-frame capture | captures longer than requested; timeline wrong | gap fill clamped to the duration in loop and drain | test passes |
| F-02 | High | REQ-SYN-003 | clock-reset fixture: MAD-based test missed the step; implausible drift crashed validation | false synchronization or crash | step detection on window-to-window deltas; drift > 2000 ppm → rejected with a flag | `test_sync_clock_reset_detected` |
| F-03 | Med | REQ-SYN-002 | aligned white-noise correlation 0.50 (half-sample rounding) | coherence underestimated after alignment | fractional-delay alignment; second drift-corrected pass (σ 62 → 2.2 µs) | `test_sync_offset_and_drift_recovered` (corr > 0.95) |
| F-04 | High | REQ-PRN-003 | demo: AC got a *strongly supported* structural path from fan-tone evidence | wrong mechanism attributed | frequency linkage of path evidence to the source's on/off frequencies | demo test asserts AC structural undetermined |
| F-05 | Med | REQ-DX-003 | AC *weakened*: quiet contact channel contradicted the mic effect | a real source down-ranked | contradiction only when no channel of the run shows an effect | demo test |
| F-06 | Med | REQ-DX-005 | PC on/off recommended to "test the AC"; completed tests re-recommended | misleading recommendations | indirect predictions; repeat down-weighting | demo next tests |
| F-07 | Low | REQ-PRN-003 | γ² = 0.06 listed as coherent (n = 58) | noise presented as shared excitation | practical minimum γ² 0.5 | demo evidence review |
| F-08 | Med | REQ-DX-001 | one experiment on two channels counted as two confirmations | inflated strength | independence per run; strong requires 2 runs, or measured repeatability plus a passed ABA check | adversarial + demo tests |
| F-09 | High | REQ-PERF-001 | 600 s × 2 ch analysis peaked at 3.27 GB | out-of-memory on 4 GB machines | block-wise kernels, float32 buffers, chunked passes, 600 s default cap | 0.93 GB; equivalence tests |
| F-10 | Med | REQ-SYN-002 | sync module had no UI/CLI path | backend feature inaccessible | `align_captures`, CLI `align`, GUI Align tab | `test_align_two_independent_devices_via_import` |
| F-11 | Med | REQ-ACQ-012 | no GUI audio import | feature only in CLI | Analysis → Import audio file | wiring matrix |
| F-12 | Low | REQ-REP-002 | clock mappings absent from reports | incomplete methodology | added to Comparisons section | test asserts "Clock mapping" in HTML |
| F-13 | High | REQ-STO-001 | SQLite URI built from raw paths ('#' truncates) | cases unopenable in some Windows profiles | percent-encoded URIs | `test_paths_with_spaces_and_hash` |
| F-14 | Low | REQ-ACQ-015 | demo isolation pads never applied (state overwritten) | demo under-reported isolation effect | SimWorld `pc_isolated` attribute | demo test |
| F-15 | Low | REQ-PKG-002 | bundle included GTK/pandas/lxml (426 MB unpacked) | size | excludes in the spec | rebuild size (final report) |
| F-16 | Med | arch | importer imported `storage` (forbidden direction) | coupling | copy/hash moved to the app | architecture test |
| F-17 | Low | REQ-DSP-003 | dead expression in the Q bandwidth computation | maintainability | rewritten with a comment | Q tests |

## 3 Open findings (accepted or blocked)

| ID | Sev | Description | Disposition |
|---|---|---|---|
| O-01 | High | no hardware qualification | BLOCKED (RISK-001; TASK-022..025) |
| O-02 | High | thresholds validated on synthetic data only | VALIDATION_REQUIRED (TASK-040) |
| O-03 | Med | self-audit only | TASK-042 |
| O-04 | Med | Windows bundle verified only through CI | see final report; TASK-020 |
| O-05 | Med | analysis limited to the first 600 s by default | TASK-012 |
| O-06 | Low | no screen-reader test | TASK-043 |
| O-07 | Med | Python callback allocation on slow machines | RISK-004, TASK-021 |
| O-08 | Low | very long spectrograms skip samples between frames (display only) | documented in spec 08 |

## 4 Scenario walkthroughs

| Scenario | Path | Expected | Verified by | Status |
|---|---|---|---|---|
| Microphone-only | wizard → devices (mic) → baseline → on/off → diagnose | tier 1; relative levels; source supported/strong; no path claims | GUI test, CLI test, adversarial on/off test | PASS (simulated) |
| Calibrated acquisition | calibrator capture → calibrate → assign → analyse | tier 5; dB SPL with uncertainty; gain change → fallback + flag | `test_inv006_*` | PASS (synthetic); HQ-04 UNEXECUTED |
| Contact sensors | mic + pickup → coherence → airborne control → isolation | coherence alone undetermined; airborne control + isolation → structural strong | ADV-003 test, demo | PASS (simulated) |
| Accelerometers | accel channel, calibration in m/s² | tier 3/5; physical only when calibrated | tier test, bridge import test | PASS (software); HQ-07 UNEXECUTED |
| Synchronized capture | two imports → align | mapping with σ; eligibility; ambiguous/unrelated rejected | align test | PASS (synthetic); HQ-05 UNEXECUTED |
| Failed capture | device loss / overflow / cancel | partial kept + flags / gaps / discard | acquisition tests | PASS |
| Invalid calibration | gain mismatch / expired / wrong sensor / relative-only | relative fallback with flags; refusal | calibration tests | PASS |
| Conflicting hypotheses | two sources, residual, unstable ABA | multiple explanations; additional source; run evidence invalidated | ADV-001, instability test, demo | PASS |
| Damaged case files | tampered chunk, broken document, stale lock, crash | detected / unreadable shown / reclaimed / recovered | storage tests | PASS |
| Offline installation | frozen bundle, empty HOME, no network | runs; self-test; demo; GUI | build smoke (Linux) | PASS (Linux); Windows CI |
| Report exports | HTML/PDF/JSON/CSV, redaction | classes visible; redacted; versioned | report test | PASS |

## 5 Readiness

* Specification complete for R1 scope: **yes**, except items explicitly BLOCKED (licence, signing, ASIO, bridge hardware, ML) and hardware validation (UNEXECUTED).
* No material contradictions remain between specs and code. Contracts are single-sourced and generated.
* Implementation readiness for the next session: see `25-implementation-handoff.md`. Remaining work is hardware qualification, real-world validation, streamed long analysis, signing/licence (owner) and R2 items.
