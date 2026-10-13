# 15 Security, privacy and licensing

## 1 Local-first data ownership and privacy

* No network access is performed by any SonicClue code path (verifiable: the only network-related import is `socket`, used solely for `gethostname()` in case lock files). There is no telemetry, account or cloud dependency. Optional diagnostics consist only of a user-initiated `sonicclue-cli info` / the Settings environment panel, which the user can copy.
* All data stays in the user's workspace. Cases are plain files the user owns and can archive or delete.
* Logs: the audit log stores actions and ids, never audio content. Report redaction (spec 14 section 3) removes names, locations, serials and notes from exported reports.
* Error dialogs show the error code, message and traceback text locally only. Nothing is sent anywhere.

## 2 Storage permissions

Workspace in the user's Documents folder (per-user; no administrator rights). Capture chunks are made read-only to prevent accidental modification; deletion of a whole case is an explicit, confirmed action.

## 3 Untrusted inputs

| Input | Safeguards |
|---|---|
| Case archives | spec 13 section 7 (size, count, traversal, symlink, ratio, checksum, manifest-exact, schema + DB integrity, temp-dir verify, atomic rename) |
| Audio imports | suffix allow-list, 8 GiB cap, libsndfile parsing, channel/rate sanity; original copied verbatim and never executed |
| Bridge dumps | 2 GiB cap; framing with length bound (4096), CRC, resync; malformed payloads counted, never trusted |
| Calibration files | 20 000-line cap, numeric parsing, |dB| ≤ 60, ≥ 2 points |
| Case database opened from disk | every document re-validated against its contract on load; SQL is parameterised; no `eval`/pickle (`np.load(allow_pickle=False)`) |
| Settings JSON | validated (analysis config) before use |

## 4 Supply chain

* Dependency and licence inventory: `matrices/dependency-license-inventory.csv`; exact pins: `requirements.lock`.
* SBOM: `packaging/build.py` writes `SBOM.json` (CycloneDX-style component list: name, version, licence) into every release bundle, from the frozen environment.
* Third-party notices: `THIRD_PARTY_NOTICES.md` generated from the installed package metadata (`tools/gen_notices.py`) and shipped in the bundle.
* Dependency scanning: the CI workflow runs `pip-audit` against `requirements.lock` (informational; findings reviewed before release).
* Build provenance: the bundle contains `BUILD_INFO.json` (version, build id = git SHA + UTC time, Python version, platform, lock-file hash). Release checksums: `SHA256SUMS.txt`.
* Code signing: BLOCKED (no certificate; DEC-009). Unsigned Windows binaries trigger SmartScreen warnings, and the release notes say so.
* Updates: there is no auto-update in 0.1 (DEC-018). A future updater must verify signatures before installing.

## 5 Licensing

* Project licence: **BLOCKED on owner decision** (DEC-009b). Until decided, the repository carries `LICENSE-NOTICE.md` ("All rights reserved; licence to be determined by Circuit Drift Labs").
* No GPL code is incorporated. GPL tools (Open Sound Meter, Friture, Audacity, Sonic Visualiser) were studied for features only. Proprietary distribution compatibility of dependencies: BSD/MIT/PSF/Apache/MPL (dev only).
* LGPL components: Qt/PySide6 (LGPL-3.0) and libsndfile (LGPL-2.1) are dynamically linked shared libraries in the PyInstaller **onedir** layout, so users can replace them. Notices and licence texts are shipped, and a written offer/link to the corresponding source (upstream releases) is in THIRD_PARTY_NOTICES. A one-file build is not used, because it would complicate LGPL relinking.
* PyInstaller: GPL-2.0 with a bootloader exception, so distributing the built application under any licence is permitted.
* ASIO SDK: not included (licence; DEC-003a).
