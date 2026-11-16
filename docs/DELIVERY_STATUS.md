# Delivery coordination

## Brief and acceptance

Verify SonicClue 0.1.0 against the checked-in requirements, correct reproducible
software defects, and deliver reviewable source and portable Linux artifacts.
Base revision: `b03e1c8732f86d889ab667d188a093c9c0d1aa61`.
Build: `b03e1c8732f8-20261031T053743Z` (uncommitted source identified independently).
Source SHA-256: `d1f97260b9d4610b93f8d4fddae12040dda7cfb5134b96f6e07210b34051dff7`.
Acceptance: regressions reproduce defects then pass, full suite/contracts pass,
independent review has no remaining material findings, and frozen programs run
without source Python in minimal offline Ubuntu 22.04/Fedora 40 containers.

## Task board

All tasks share the delivery workspace. The lead owns integration; workers edit
only explicitly assigned files, and read-only review owns no shared edits.

| ID | Outcome / scope and exclusions | Owner | Dependencies | Owned files | Status | Acceptance and handoff |
|---|---|---|---|---|---|---|
| SC-ALIGN | Align every secondary stream; no hardware accuracy claim | lead | SC-REVIEW | app/service.py, tests/test_multi_updater.py | DONE | Two/three-device mappings persisted |
| SC-DROPS | Preserve trailing queue drops and requested duration | lead | SC-REVIEW | acquisition/session.py, tests/test_acquisition.py | DONE | Deterministic full/clamped dropout regressions pass |
| SC-ARCHIVE | Import no-derived exports; preserve source and scalar results | lead | SC-REVIEW | storage/archive.py, tests/test_storage.py | DONE | Both round trips pass with integrity checks retained |
| SC-REVIEW | Independent storage/updater/acquisition review | review worker | requirements | read-only | DONE | Three original findings reproduced; fixes reviewed |
| SC-LOCK | Complete runtime pins and verify release Python | lead | dependency setup | requirements.lock | DONE | Python 3.11 suite, pip check and Windows x64 resolver pass |
| SC-PROVENANCE | Identify source and installed runtime; include crypto notices | packaging worker | SC-LOCK | packaging/build.py, tools/gen_notices.py, tests/test_release_metadata.py | DONE | Source mutation/generated-file exclusions and notices tested |
| SC-NATIVE | Portable audio/graphics/data loading, preserving host settings | packaging worker | clean-image findings | packaging/sonicclue.spec, packaging/pyi_rth_portaudio.py, tests/test_frozen_audio.py | DONE | Pristine images load PortAudio and Qt; configuration regressions pass |
| SC-APPIMAGE | Relocatable GUI/CLI AppImage staging; unsigned | lead | SC-BUNDLE | packaging/build_appimage.py, tests/test_appimage.py | DONE | Build and extraction-mode launch pass; relocation/argument tests pass |
| SC-BUNDLE | Build Ubuntu 22.04/glibc 2.35 portable artifact | lead | SC-NATIVE, SC-PROVENANCE | dist/, work/delivery-build.log | DONE | Frozen version/selftest/demo/backend/GUI smoke passes |
| SC-CLEAN | Independent offline runtime-only checks; excludes manual desktop/HQ | review worker | SC-BUNDLE | work/delivery-clean-*.log | DONE | All six checks pass on both pristine distro images |
| SC-VERIFY | Integrated tests/contracts and benchmark evidence | lead | source integration | work/delivery-tests.log, research/benchmark-cloud.json | DONE | 231 tests; contract checks pass; quick cloud benchmarks recorded |
| SC-CI | Existing Linux/Windows CI through draft PR; excludes merge/release | lead | reviewed source, user authorization | .github/workflows/ci.yml | IN_PROGRESS | User approved publishing draft PR; CI execution pending |

## Architecture and decisions

Existing app/capture/clock-mapping contracts remain authoritative. No schema or
migration changes. The archive fix clears omitted array-file references only in
the exported database snapshot and checkpoints its WAL before packaging; import
integrity checks remain strict. Previously broken no-derived archives need
re-export with corrected code.

Linux packaging explicitly includes neutral graphics dispatchers and dynamic Qt
OpenGL imports. A runtime hook locates bundled PortAudio without a host linker
cache. Bundled ALSA data is used only when host data and explicit ALSA environment
settings are absent, preserving configured systems. Native data copyright is
included. No vendor graphics drivers or glibc are bundled.

AppImage build (use a verified appimagetool):

```
python packaging/build_appimage.py --bundle dist/SonicClue-0.1.0-linux-x64 --tool /path/to/appimagetool-x86_64.AppImage --out dist/SonicClue-0.1.0-x86_64.AppImage
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/SonicClue-0.1.0-x86_64.AppImage --cli selftest
```

Without `--cli`, AppImage launches the GUI. Extraction mode works without FUSE;
normal FUSE mounting has not been qualified in this container environment.

## Verification and limits

- PASS: 231 tests on Linux/Python 3.11.17, exact runtime pins plus dev tooling.
- PASS: 94 generated contract files; 47/47 examples; 12/12 numerical vectors;
  422/422 prompt checks; pip check; independent review; git diff --check.
- PASS: frozen version, numerical selftest, simulated investigation/HTML report,
  simulator listing, real PortAudio loading with zero devices, and offscreen GUI
  construction (11 screens) on both pristine Ubuntu 22.04 and Fedora 40 images.
  Tests use `--network none`, mount only the bundle, and install no packages.
- PASS: quick cloud-machine benchmarks in `specs/research/benchmark-cloud.json`.
  These are cloud results, not designated reference-machine qualification.
- Windows runtime pins resolve successfully; Windows execution remains a CI gate.
  Minimal-image locale/fontconfig warnings do not establish desktop rendering or
  accessibility qualification. Source and frozen functional checks are distinct.

Baseline regressions reproduced all original defects before fixes. Additional
clean-image checks uncovered GLib, dynamic Qt imports, PortAudio discovery and
ALSA-data issues; those are included in the final fixes and CI smoke coverage.

## Remaining external gates and next actions

The authoritative product backlog remains `specs/matrices/backlog.csv`. Hardware
qualification HQ-02/03/04/05/06, clean Windows desktop/VM install walkthroughs,
reference-machine designation, real-world investigations and screen-reader tests
still require actual devices, machines or human users. Container checks cover
Linux software portability but do not close those manual gates. Signing requires
owner credentials; the project licence and ASIO licence remain owner decisions.
Sensor bridge firmware requires board selection. Unsigned portable builds are
available; no release or deployment has been performed.

Next: inspect draft-PR Linux/Windows checks and standalone artifacts; fix any
material CI findings; then schedule manual qualifications as resources become
available. Do not infer physical diagnostic accuracy from synthetic data.

## Resource inventory and recovery

One existing managed workspace; no additional cloud instances or paid resources.
Ubuntu 22.04 builder container and disposable Ubuntu/Fedora smoke containers were
used. Remove the builder when final artifacts are verified; smoke containers
remove themselves. Local work/venv, work/release-venv, logs and delivery artifacts
are retained for reproduction. Workers are finished. Private source/verification
file delivery was explicitly authorized; no sharing changes or public release.
