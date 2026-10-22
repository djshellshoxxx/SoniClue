# 20 Development roadmap

## 1 Milestones (dependency ordered)

| Milestone | Content | Status |
|---|---|---|
| M0 Contracts | domain models, units, errors, JSON Schemas, examples | DONE (tested) |
| M1 Numerics | dsp modules + invariant catalog + test vectors | DONE (tested) |
| M2 Persistence | case store, writer + journal, recovery, verify, migrations, archives | DONE (tested) |
| M3 Acquisition | PortAudio/simulated backends, capture session, importers, bridge codec | DONE (software tested; hardware UNQUALIFIED) |
| M4 Calibration & sync | calibration conventions, tiers, clock mapping, alignment | DONE (synthetic tests; hardware UNEXECUTED) |
| M5 Analysis & comparison | pipeline, comparability, uncertainty | DONE (tested) |
| M6 Diagnostics & procedures | rules, abstention, next tests, 15 procedures, executor, gates | DONE (adversarial tests) |
| M7 Stimulus | interlocked output, audition | DONE (simulated) |
| M8 Reporting | report model, HTML/PDF/JSON/CSV, redaction | DONE (tested) |
| M9 GUI & CLI | 12 screens, CLI, demo | DONE (offscreen GUI tests) |
| M10 Packaging | PyInstaller bundles, notices, SBOM, CI | Linux built and smoke-tested locally; Windows built by CI (see final report) |
| M11 Hardware qualification | HQ-01..09 | NOT STARTED (needs hardware) |
| M12 Real-world validation | ≥ 40 investigations, held-out evaluation | NOT STARTED (RQ-1) |
| M13 R2 release | signed installer, AppImage, rtmixer if profiling requires it | NOT STARTED; signing and clean-VM packaging need external setup |

## 2 Backlog (remaining work)

`matrices/backlog.csv` has the task ledger, with dependencies, owned paths and acceptance criteria. Remaining items are listed there with status; first-release items are complete except those blocked on hardware, certificates or owner decisions.

## 3 Effort assumptions

Effort sizing is omitted. The project policy is to plan concrete steps without timelines, and the owner schedules work.
