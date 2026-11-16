# Developer Overview

## What it is

SonicClue (Python 3.11 or newer, package `sonicclue`, version 0.1.0) is a local, offline tool for sound and vibration cause investigation. It captures or imports audio, runs analysis, compares captures under a controlled test, and runs a deterministic diagnostic engine over an evidence ledger. It ships a PySide6 desktop GUI, a CLI (`sonicclue-cli`) and a simulator. Licence is undecided (see `LICENSE-NOTICE.md`).

## Tech stack

- Python 3.11+, packaging via `pyproject.toml` (setuptools, `src` layout)
- Core: numpy, scipy, pydantic v2 (contracts), soundfile, matplotlib, reportlab
- Audio I/O: `sounddevice` over PortAudio (ADR-0003). A simulated backend implements the same interface
- GUI (optional extra `gui`): PySide6 and pyqtgraph
- Storage: SQLite (WAL, synchronous FULL) per case, plus files for chunks and manifests
- Tests: pytest, hypothesis. Contract schemas are generated from the pydantic models
- Packaging: PyInstaller (`packaging/build.py`), onedir bundles for Windows and Linux

## Design decisions (and why)

Recorded in `docs/specs/decisions/adr/` (ADR-0001 to ADR-0009). The main ones are below.

**Layered package with one-way dependencies.** `domain` and `dsp` never import GUI, device, storage or orchestration code. `gui` and `cli` call `app`, and `app` calls the rest. `tests/test_contracts_architecture.py` enforces this, and it allows only `gui` to import PySide6 or pyqtgraph. This keeps the analysis core testable headless and reusable.

**Pydantic contracts as the single source of truth.** Every document (capture manifest, calibration profile, analysis config, diagnosis snapshot, and so on) is a pydantic model. JSON Schemas and examples are generated from it (`tools/gen_schemas.py --check` in CI). Every load re-validates, so a damaged or hand-edited database is caught.

**Evidence, not probabilities.** The diagnostic engine gives ordinal support levels (`strongly_supported`, `supported`, `undetermined`, `weakened`, `contradicted`), not probabilities. It can return an inconclusive result and suggests the next test that would separate the explanations. Correlation alone is never treated as cause.

**Controlled comparisons.** `compare` and `comparability` check that the two groups differ only in the variable under test (position, mounting, gain, AGC, capture quality). An invalid comparison is flagged, not silently analysed.

**Deterministic, versioned rules.** Diagnostic rules are fixed code, versioned by `RULESET_VERSION` in `diagnostics/engine.py` (currently 1.0.0). Each rule is tagged `R-xxx@rev`. The same evidence gives the same snapshot, and the snapshot records the ruleset version.

**Simulator as a first-class backend.** `SimulatedBackend` and `SimWorld` (in `acquisition/backends.py`) drive the same capture path as real hardware. The demo (`app/demo.py`) runs a full SIMULATED investigation and labels it as such. Simulated results are never presented as measurements.

**Honest status.** No audio interface or sensor has been hardware-qualified. Devices are listed as UNQUALIFIED in the compatibility matrix. The docs say so and the report marks simulated data.

**Local-first.** No account, cloud or GPU. Workspace defaults to `Documents/SonicClue` (or `SONICCLUE_WORKSPACE`).

## Signal and data flow

```
 device (PortAudio) or simulator ──► acquisition (session, chunks, gaps)
                                         │
                                  storage: case dir
                                  (case.db + chunk files)
                                         │
                                         ▼
                        analysis/pipeline.analyze()  ◄── dsp/* (levels, spectral,
                          (per channel, per pair)          tonal, transient, cross, stats)
                                         │
                       ┌─────────────────┼──────────────────┐
                       ▼                 ▼                  ▼
                compare/compare      sync (clock     diagnostics/engine.diagnose()
                (groups A vs B,      mapping)        (evidence ledger, rules,
                 comparability)                       conclusion, next tests)
                       └─────────────────┼──────────────────┘
                                         ▼
                              reporting/builder ──► render (HTML, PDF, JSON, CSV zip)
```

Captures are chunked and written while recording. Analysis runs in background jobs with cancellation (`app/jobs.py`). The CLI and GUI both go through `SonicClueApp` (`app/service.py`).

## Threads and jobs

- The GUI runs work through `app/jobs.py` with a `CancelToken`, checked between channels and at defined points. Shutdown cancels pending jobs and waits for running ones.
- Capture runs in a session with a backend stream. Chunks are written as they arrive.
- The storage layer takes a case lock (`case.lock`, pid, host, time). Stale locks are reclaimed.

## Where the UI fits

`gui/main.py` (`main()`) builds the window with a navigation list (dashboard, devices, calibration and others). Screens are split across `screens_case.py`, `screens_setup.py`, `screens_measure.py` and `screens_dx.py`, with shared helpers in `common.py`. The GUI goes through `SonicClueApp`. Only `gui` imports Qt, enforced by the architecture test.

See [[Developer-Code-Map]] for paths and [[Developer-Conventions]] for the rules.
