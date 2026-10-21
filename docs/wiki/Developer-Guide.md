# Developer Guide

## Environment

SonicClue targets Python 3.11 or newer. From the repository root:

```sh
python -m pip install -e ".[gui,dev]"
```

Linux audio support may require system PortAudio and libsndfile packages. The project’s CI workflow is the source of truth for OS-specific build dependencies.

## Run the app

```sh
sonicclue                 # GUI
sonicclue-cli --help      # CLI
sonicclue-cli demo        # labelled simulated workflow
```

## Verification

Run the automated suite and generated-contract checks before proposing a change:

```sh
QT_QPA_PLATFORM=offscreen pytest
python tools/gen_schemas.py --check
python docs/specs/contracts/validate_examples.py
python tools/gen_test_vectors.py --check
python tools/check_prompt_embedding.py
```

The GUI tests use the offscreen Qt platform. Tests marked `hardware` require physical audio equipment and should not run in CI; they do not substitute for qualification on the target interface.

Build a standalone bundle for the current operating system with:

```sh
python packaging/build.py
```

## Repository map

- `src/sonicclue/domain/`: contracts, units, errors
- `src/sonicclue/dsp/`: reusable numerical routines
- `src/sonicclue/analysis/`, `compare/`, `diagnostics/`: analysis, comparisons, and rule-based reasoning
- `src/sonicclue/acquisition/`, `sensors/`, `sync/`: capture, sensor/calibration support, alignment
- `src/sonicclue/procedures/`, `stimulus/`: guided tests and interlocked output
- `src/sonicclue/storage/`, `reporting/`: cases, archives, report generation
- `src/sonicclue/app/`: orchestration, jobs, settings, demo
- `src/sonicclue/gui/`, `cli/`: user interfaces
- `tests/`: unit, numerical, integration, storage, workflow, and GUI checks
- `docs/specs/`: normative requirements, contracts, architecture, validation records, and backlog

## Engineering constraints

The architecture test enforces the dependency direction described in [System Architecture](../specs/03-system-architecture.md). In particular, keep Qt imports in `gui`, keep DSP and domain importable without GUI/audio/storage dependencies, and use application orchestration to connect the UI to services.

When changing a shared contract, update the canonical model, schema version as required, generated schemas, valid/invalid examples, migrations, and the corresponding spec. Do not edit generated schemas by hand.

Numerical changes need independent-reference or invariant tests and must-fail edge cases. Diagnostic-rule changes need adversarial tests that assert what the app must not conclude. Keep diagnosis ordinal and explainable; do not introduce unvalidated probabilities.

Preserve captured source data. Derived records should retain input IDs and algorithm/rule versions. Add meaningful tests for error, partial, cancelled, recovered, and invalid-data states as applicable. Record architecture or product decisions in the ADR register.

## Development references

Start with [specification README](../specs/README.md), [implementation handoff](../specs/25-implementation-handoff.md), [development backlog](../specs/matrices/backlog.csv), and [feature-wiring matrix](../specs/matrices/feature-wiring.csv). Check [CONTINUATION.md](../CONTINUATION.md) and GitHub Actions for the latest working status; the static release notes may lag newer commits.