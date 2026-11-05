# Developer Build and Test

## Toolchain

- Python 3.11 or newer (CI uses 3.11)
- Linux: system libraries for PortAudio, libsndfile and the Qt offscreen or EGL stack. CI installs them with `apt-get` (`libportaudio2`, `libsndfile1`, `libegl1`, `libgl1`, `libxkbcommon-x11-0`, `libxcb-*`)
- Windows: standard Python install. PortAudio and libsndfile come with the wheels
- Locked dependencies in `requirements.lock`. Ranges in `pyproject.toml`

## Setup

```
pip install -e .[gui,dev]
```

`gui` adds PySide6 and pyqtgraph. `dev` adds pytest, hypothesis, jsonschema and pyinstaller.

## Run

```
sonicclue            # GUI (gui-scripts entry point)
sonicclue-cli --help
sonicclue-cli demo   # full SIMULATED investigation, writes a report
python -m sonicclue  # same package, as a module
```

`SONICCLUE_WORKSPACE` changes where cases are stored (default `Documents/SonicClue`).

## Checks

Run these before a PR. They match CI.

```
python tools/gen_schemas.py --check          # schemas match the models
python docs/specs/contracts/validate_examples.py
python tools/gen_test_vectors.py --check     # DSP test vectors reproduce
python tools/check_prompt_embedding.py
QT_QPA_PLATFORM=offscreen pytest             # full suite
```

To refresh generated files after changing a model:

```
python tools/gen_schemas.py
python tools/gen_test_vectors.py
```

Optional benchmark:

```
python tools/benchmark.py --out docs/specs/research/benchmark-<host>.json
```

## Tests

The pytest suite (about 114 test functions) covers numerical invariants, adversarial diagnostics, storage, acquisition, analysis, workflows, calibration and sync, the contracts and architecture rules, and the GUI. The architecture test fails if a layer imports something it should not. `tests/test_contracts_architecture.py` also checks that only `gui` imports Qt.

## Packaging

```
python packaging/build.py              # standalone bundle for this OS
python packaging/build.py --skip-smoke # skip the clean-environment smoke test
```

The build writes the version ID, runs PyInstaller in onedir mode, adds the docs, notices and SBOM, and writes `BUILD_INFO`. It then runs a smoke test in a clean environment. `packaging/sonicclue.spec` is the PyInstaller spec, and `entry_cli.py` and `entry_gui.py` are the bundle entry points.

## CI (`.github/workflows/ci.yml`)

- Triggers: push to `main`, pushes to `claude/**` branches, version tags `v*`, pull requests, manual dispatch
- Matrix: `ubuntu-22.04` and `windows-latest`, Python 3.11, `QT_QPA_PLATFORM=offscreen`
- Steps: install, contracts and test vectors, the test suite, a dependency audit on Linux (`pip-audit`, informational), then `packaging/build.py`
- The bundle is uploaded as an artifact per OS

## Release

1. Update the version in `pyproject.toml` and `__version__` in `src/sonicclue/__init__.py`.
2. Update `docs/RELEASE_NOTES.md`.
3. Tag `v<version>`. CI builds the bundles.
4. Check the compatibility matrix in `docs/specs/matrices/`. Do not claim hardware qualification unless the qualification run was done.

## Troubleshooting builds

- Qt errors in headless runs: set `QT_QPA_PLATFORM=offscreen`.
- `sounddevice` cannot find PortAudio on Linux: install `libportaudio2`.
- Schema check fails: a model changed. Run `python tools/gen_schemas.py` and commit the output.
