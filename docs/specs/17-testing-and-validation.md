# 17 Testing and scientific validation

## 1 Test levels and where they live

| Level | Location | Count (approx.) | Notes |
|---|---|---|---|
| Unit + numerical reference | `tests/test_dsp_numerics.py` | 44 | independent references (closed form, direct DFT); must-fail counterexamples |
| Interface contract | `tests/test_contracts_architecture.py`, `docs/specs/contracts/validate_examples.py` | 3 + 47 examples | jsonschema and pydantic cross-validation; schemas current |
| Architecture (dependency direction) | `tests/test_contracts_architecture.py` | 1 per source file (~58) | verified to fail on an injected violation |
| Property-style | parametrised windows/offsets, seeds | – | `hypothesis` available; parametrisation used where the properties are known |
| Storage round trip, recovery, integrity, archive safety | `tests/test_storage.py` | 13 | malicious archives, tampering, crash journal |
| Acquisition, failure injection, concurrency | `tests/test_acquisition.py` | 12 | device loss, queue overflow, clipping, double start/stop, bridge corruption |
| Calibration, sync | `tests/test_calibration_sync.py` | 17 | INV-006 with counterexample; offset/drift/reset/ambiguity |
| Diagnostics (adversarial) | `tests/test_diagnostics_adversarial.py` | 14 | ADV-001..010, chain test both ways, ABA instability, determinism |
| Workflows, stimulus safety, reports, CLI end to end | `tests/test_workflows.py` | 15 | demo ground truth; all report formats; CLI exit codes |
| GUI | `tests/test_gui.py` | 3 | offscreen; drives Devices → Live → Analysis → Guided → Hypotheses → Report |
| Performance | `tools/benchmark.py` | 10 metrics | spec 16 |
| Packaging + clean environment | `packaging/build.py` smoke stage | 5 commands | runs the frozen binaries with an empty HOME, no PYTHONPATH, offscreen |
| Hardware qualification | spec 18 | – | **UNEXECUTED** (no hardware available) |
| End-to-end scenario | demo (SimWorld) + CLI test + GUI test | – | simulated only |

Run everything with `QT_QPA_PLATFORM=offscreen pytest`. CI runs the suite on Ubuntu and Windows (`.github/workflows/ci.yml`).

## 2 Simulation fixtures (deterministic, seeded; `dsp/signals.py`, `acquisition/backends.SimWorld`)

| FIX | Fixture | Used by |
|---|---|---|
| FIX-01 | pure tones (bin-centred and off-bin) | INV-002/004, calibration |
| FIX-02 | harmonics (50 Hz mains, 37 Hz non-mains, fan 117 Hz) | families, mains, diagnostics |
| FIX-03 | white/pink/band noise of known variance | Parseval, bands, coherence null |
| FIX-04 | impulse train (rattle) | transients, buzz |
| FIX-05 | log chirp | stimulus, speaker buzz |
| FIX-06 | AM / FM tones | envelope spectrum, power conservation |
| FIX-07 | clipping | screening, gates, artifacts |
| FIX-08 | dropouts (zeroed blocks) | INV-010 |
| FIX-09 | clock drift (ppm) and fractional delay | sync |
| FIX-10 | sensor offsets (gain change, mount change, position change) | comparability ADV-004/005/008 |
| FIX-11 | mixed and correlated sources (two sources at one frequency) | ADV-001 |
| FIX-12 | confounded intervention (source and path) | ADV-007 |
| FIX-13 | resonance-like response (iirpeak Q = 20) | Q estimation |
| FIX-14 | delayed signals | phase sign, delay |
| FIX-15 | low-SNR observations (1e-6 FS tone; 0.05 noise calibrator) | EDGE-004, calibration rejection |
| FIX-16 | ultrasonic alias (30 kHz at 48/44.1 kHz) | ADV-006 |
| FIX-17 | SimWorld "home studio" (fan via desk, HVAC rumble, airborne pickup, isolation pads, chain hum option) | demo ground truth, GUI/CLI end-to-end |

## 3 Validation matrix

`matrices/validation-matrix.csv` lists each validation item, its gate, fixture or hardware configuration, reference method, command, expected result, tolerance, kind (software/hardware), must-fail case and status. Every major gate has at least one intentionally failing case: schema (27 invalid examples), calibration (gain mismatch, relative-only, 4 rejection types), synchronization (ambiguous, reset, unrelated), spectral normalisation (swapped orientation, naive gap inclusion, single-segment coherence), comparability (mount/AGC/position/multiple changes), diagnostic abstention (baseline only, coherence only, confounded fix), install integrity (tampered archive, checksum).

## 4 Simulated vs physical

All automated results are software or simulated. Physical claims (device accuracy, dropout-free capture, calibration with a real calibrator, two-device alignment) require the hardware procedures in spec 18 and are **UNEXECUTED**.

## 5 Datasets and rights

The only datasets are generated fixtures (no third-party audio). Their redistribution rights are unrestricted (self-generated).

## 6 Threshold tuning vs held-out validation (gate for RQ-1 / DEC-011)

Diagnostic thresholds were set from engineering reasoning, and checked against synthetic scenarios that were written *before* the thresholds were finalised (the adversarial suite). Before any real-world accuracy claim: collect ≥ 40 real investigations with ground-truth interventions; split them 50/50 into tuning and held-out sets *before* looking at results; freeze thresholds on the tuning set; report per-hypothesis-category confusion on the held-out set, including abstention rate. Held-out cases must never be used for tuning.
