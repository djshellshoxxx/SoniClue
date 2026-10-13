# 19 Build and release

## 1 Package decision (DEC-009)

* **Windows x64:** portable ZIP `SonicClue-<ver>-windows-x64.zip` (SELECTED_DEFAULT). It installs per user with no administrator rights and works offline. It is side-by-side capable because versions live in separate folders. An Inno Setup per-user installer is R2, together with code signing (BLOCKED: no certificate).
* **Linux x64:** `SonicClue-<ver>-linux-x64.tar.gz` (glibc of the build host: Ubuntu 24.04 → glibc 2.39; build on Ubuntu 22.04 in CI for glibc 2.35 compatibility). AppImage is backlog (TASK-015).
* Both bundles contain `SonicClue[.exe]` (GUI, windowed) and `sonicclue-cli[.exe]` (console), the runtime (CPython, Qt, PortAudio, libsndfile, NumPy/SciPy), `README.md`, `USER_GUIDE.md`, `RELEASE_NOTES.md`, `LICENSE-NOTICE.md`, `THIRD_PARTY_NOTICES.md`, `SBOM.json` and `BUILD_INFO.json` (version, build id = git SHA + UTC time, Python, lock-file hash).

## 2 Reproducible build

```
python -m pip install -r requirements.lock      # exact pins
python -m pip install -e . pyinstaller==6.22.3
python packaging/build.py                       # → dist/SonicClue-<ver>-<os>-x64.(zip|tar.gz) + SHA256SUMS.txt
```

`build.py` runs PyInstaller with `packaging/sonicclue.spec` (onedir), then smoke-tests the frozen binaries in a clean environment: empty HOME/USERPROFILE, a temporary workspace, no PYTHONPATH and a minimal PATH. It runs `--version`, `selftest`, `demo --scale 0.3` (simulated), `devices --backend simulated` and `SonicClue --smoke-test` (builds all 11 screens offscreen). The archive is written only if all of them pass. CI (`.github/workflows/ci.yml`) builds on `windows-latest` and `ubuntu-22.04` and uploads the archives and checksums as artifacts. Tagging `v*` attaches them to a draft GitHub release.

## 3 Install, upgrade, rollback, uninstall

| Topic | Behaviour |
|---|---|
| Standard-user install | unzip/untar anywhere writable; nothing written outside the folder and the workspace |
| Offline | all dependencies bundled; no network at install or run |
| Device permissions | Windows microphone privacy switch; Linux ALSA/PipeWire access (audio group or a desktop session); bridge serial access (dialout group) when used |
| Required runtimes/drivers | none beyond the OS audio stack; class-compliant USB interfaces need no driver; vendor ASIO drivers are not used |
| First launch | creates `Documents/SonicClue/` (cases, settings, qualification, calibrations); opens the dashboard; offers the simulated demo |
| Missing devices | the GUI falls back to the simulator with a message; the CLI returns SC_NO_DEVICE / SC_NO_AUDIO_BACKEND |
| Upgrade | unzip the new version beside the old one; the same workspace is reused; store migrations back up `case.db` first |
| Rollback | run the previous version; a migrated case can be restored from `case.db.bak-v<N>-<t>` |
| Side-by-side | supported (separate folders); the same case cannot be open in two instances (case lock) |
| Uninstall | delete the program folder; the workspace is preserved unless the user deletes it |
| Interrupted install | an incomplete unzip is detected by checksum mismatch or a failing smoke run; re-extract; no registry or system state to repair |
| User data preservation | the workspace is never touched by install/upgrade/uninstall |

## 4 Release checklist

1. Full test suite green on Windows and Linux CI. 2. `gen_schemas --check`, `validate_examples`, `gen_test_vectors --check` green. 3. Benchmarks recorded for the machine used. 4. `build.py` green on both OSs (smoke stage). 5. Clean-machine test HQ-09. 6. Release notes updated with qualification status (UNQUALIFIED unless HQ tests pass). 7. SHA256SUMS published with the artifacts.

## 5 Release notes policy

Release descriptions state completed features, known limitations and **hardware qualification status**. "Hardware-qualified" may only be claimed for devices with a passing HQ-02 (and HQ-04/07 for calibrated claims) recorded in the compatibility matrix.
