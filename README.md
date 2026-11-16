# SonicClue

**Affordable sound and vibration cause investigation**, by Circuit Drift Labs.

SonicClue helps you find out *what* is making an unwanted noise or vibration, *how* it reaches you, and *whether a fix worked*. It does not just show frequency graphs. It guides you through controlled tests (switching equipment off and on, adding isolation, decoupling a contact sensor, disconnecting a microphone, tapping objects), checks that each comparison is valid, and keeps an evidence ledger. From that ledger it ranks competing explanations and recommends the next test that would best separate them. It says "inconclusive" when the evidence does not support a conclusion, and it never treats correlation as proof of cause.

* Local-first and offline. No account, cloud or GPU.
* Works with an ordinary microphone. Adds contact pickups, accelerometers and calibrated measurement microphones when you have them.
* Windows x64 and Linux x64 standalone builds (portable, no admin rights).

> **Status (0.1.0):** software-complete and tested on synthetic and simulated data. **No audio interface or sensor has been hardware-qualified yet.** All physical devices are listed as UNQUALIFIED. Availability of a build script or packaging configuration does not imply real-hardware qualification. See [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md).

## Quick start

```
# from a release bundle
SonicClue            # desktop app (Windows: SonicClue.exe)
sonicclue-cli demo   # run a complete SIMULATED investigation and write a report

# from source (Python 3.11+)
pip install -e .[gui,dev]
sonicclue            # GUI
sonicclue-cli --help
```

Typical workflow: **Case dashboard** → New investigation → **Devices & sensors** (describe each channel; turn AGC off) → **Guided tests** (Baseline, then the recommended tests) → **Hypotheses & evidence** → **Report builder**. Full guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Project wiki

Start with the [SonicClue Wiki](docs/wiki/Home.md) for user workflows, feature explanations, developer setup, architecture, and troubleshooting. Its [wiki index](docs/wiki/README.md) links each topic.

## Repository layout

```
src/sonicclue/      application (domain, dsp, acquisition, sensors, sync, analysis, compare, diagnostics,
                    procedures, stimulus, storage, reporting, qualification, app, cli, gui)
tests/              automated tests (numerical invariants, adversarial diagnostics, storage, workflows, GUI)
docs/specs/         specification package (requirements, architecture, contracts, schemas, audits, handoff)
docs/prompts/       specification-authoring prompt and implementation handoff
packaging/          PyInstaller spec and build script
tools/              schema/test-vector generators, benchmark, notices, prompt checker
```

## Development

```
pip install -e .[gui,dev]
QT_QPA_PLATFORM=offscreen pytest            # full suite
python tools/gen_schemas.py --check          # contracts current
python docs/specs/contracts/validate_examples.py
python tools/gen_test_vectors.py --check
python tools/benchmark.py --out docs/specs/research/benchmark-<host>.json
python packaging/build.py                    # standalone bundle for this OS
```

Architecture rules (dependency direction, Qt only in `gui`) are enforced by `tests/test_contracts_architecture.py`.

Verified on this snapshot (Linux, Python 3.13 in a scratch venv with `[gui,dev]`): `QT_QPA_PLATFORM=offscreen pytest` exits 0 (full suite passes).

## Licence

Licence to be decided by Circuit Drift Labs. See [LICENSE-NOTICE.md](LICENSE-NOTICE.md). Third-party components: `THIRD_PARTY_NOTICES.md` in every release bundle and `docs/specs/matrices/dependency-license-inventory.csv`.
