# Developer Conventions

## Style

- Python 3.11+, `src` layout. Type hints on public functions. Pydantic models for every document that is saved or exchanged.
- Modules in `dsp/` are pure numeric code. Keep them free of I/O.
- Read the ADRs in `docs/specs/decisions/adr/` before changing a decision they cover. They explain the constraints (ADR-0003 for the audio stack, ADR-0011 for the no-ML reasoning, ADR-0012 and 0013 for the GUI, ADR-0014 for missing values, ADR-0015 for forward compatibility).
- Keep the specs in `docs/specs/` in step with the code. The spec and ADRs are the authority when they disagree with the implementation.

## Layering rules

Enforced by `tests/test_contracts_architecture.py`:

- `domain` and `dsp` do not import GUI, device, storage or orchestration code.
- `dsp` and `domain` do not import Qt, sounddevice, soundfile or the database.
- Only `gui` imports PySide6 or pyqtgraph.
- The GUI and CLI call `SonicClueApp` (`app/service.py`). They do not call `storage` or `acquisition` directly.

Breaking one of these fails the suite. Fix the import, do not add an exception.

## Data and contracts

- Every saved document is validated when it is loaded. A new field needs a model change, a regenerated schema (`tools/gen_schemas.py`) and a valid and invalid example in `docs/specs/contracts/examples/`.
- Atomic writes go through `storage/files.py`: temporary file, fsync, then `os.replace`.
- Case directories are single-writer. The case lock is `case.lock`. Do not bypass it.
- Forward compatibility (ADR-0015): a newer store version is rejected, and a migration backup is kept (`tests/test_storage.py`). A newer contract example is in `docs/specs/contracts/examples/invalid/`.

## Diagnostics rules

- Support is ordinal. Do not add a probability output.
- A new rule needs a revision tag `R-xxx@rev`. Changing a rule means bumping `RULESET_VERSION` in `diagnostics/engine.py` and updating the examples and tests.
- Correlation or a frequency match is never enough for a "cause" conclusion. Abstain when the evidence is weak. The engine can return inconclusive.
- Invalid comparisons are flagged by `compare/comparability.py`, not silently analysed.

## Honesty rules

- Simulated data is labelled SIMULATED in the case and in reports. Do not present simulator output as measurement.
- Do not claim hardware qualification. No device is qualified yet, and the compatibility matrix lists them as UNQUALIFIED.
- Reports separate measured, calculated, inferred, user-provided and unresolved statements. Keep that split when you change report content.

## Real-time and concurrency

- Capture runs through a bounded queue to a writer thread (`acquisition/session.py`). The device callback must not block on disk.
- Long work runs as jobs (`app/jobs.py`) with a `CancelToken`. Check it at the defined points.
- Shutdown cancels pending jobs and waits for running ones. Keep that behaviour.

## How to add a feature

1. Decide the layer using [[Developer-Code-Map]]. Keep the DSP free of I/O.
2. Add or change the contract in `domain/model.py` and regenerate schemas.
3. Put the maths in `dsp/` with a numeric test in `tests/test_dsp_numerics.py`.
4. Wire it through `app/service.py`. Add a CLI subcommand in `cli/main.py` if it is a user action.
5. Add a GUI screen or control under `gui/` only if it is needed.
6. Add a workflow or contract test. Run the full checks in [[Developer-Build-and-Test]].
7. Update `docs/USER_GUIDE.md` and the wiki pages.

## Known limitations

From `docs/RELEASE_NOTES.md`, `README.md` and the compatibility matrix:

- No audio interface or sensor has been hardware-qualified. Synthetic and simulated data only.
- The product licence is not decided (`LICENSE-NOTICE.md`).
- Machine learning is out of scope for now (ADR-0011).
- Windows 11 x64 is the primary target. Ubuntu 22.04 and 24.04 x86-64 are the Linux targets (ADR-0002). macOS and ARM64 are out of scope.
