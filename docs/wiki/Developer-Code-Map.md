# Developer Code Map

Paths are relative to the repo root. `src/sonicclue` is the package. Line numbers are approximate. Search for the symbol if one is off.

## Directory tree

```
soniclue/
├── pyproject.toml               package metadata (0.1.0), extras gui and dev, console scripts
├── requirements.lock            exact dependency pins
├── src/sonicclue/
│   ├── __init__.py              __version__ and BUILD_ID (BUILD_ID comes from _build.py in release builds)
│   ├── __main__.py              python -m sonicclue
│   ├── domain/                  pydantic contracts (model.py), error types, units. No I/O
│   ├── dsp/                     pure numeric code: levels, spectral, tonal, transient, cross (coherence, transfer), resample, stats, signals
│   ├── acquisition/             backends.py (PortAudio and simulator), session.py (device callback, queue, writer thread, state machine), importer.py (WAV and bridge dump import, keeps original bytes and SHA-256)
│   ├── sensors/                 capabilities.py, calibration.py (CalStatus, calibration profiles), bridge.py (sensor bridge protocol v1 over USB serial)
│   ├── sync/                    estimate_mapping(): clock offset and drift between independently clocked captures
│   ├── analysis/                pipeline.py (analyze(), tone_level_at(), band_power()), spool.py (ChannelSpool: per-channel float32 files for full-length analysis)
│   ├── compare/                 comparability.py (validity checks), compare.py (groups A vs B)
│   ├── diagnostics/             engine.py (diagnose(), rules, RULESET_VERSION), next_tests.py (suggested next tests)
│   ├── procedures/              guided test definitions (definitions/procedures.json, 15 procedures)
│   ├── stimulus/                stimulus generation and audition, with output safety interlocks (SM-004)
│   ├── storage/                 store.py (CaseStore, Workspace, case.db), files.py (atomic writes, hashing), archive.py (.scarchive zip export and safe import), writer.py (chunked, journaled capture writer), migrations.py
│   ├── reporting/               builder.py (build_report), render.py (HTML, PDF, JSON, CSV zip)
│   ├── qualification/           hardware loopback qualification
│   ├── app/                     service.py (SonicClueApp facade, CaptureSpec, CaptureHandle), jobs.py (background jobs, cancel), demo.py (simulated investigation)
│   ├── cli/main.py              sonicclue-cli (argparse subcommands)
│   └── gui/                     main.py (window), screens_*.py (screens), common.py (shared widgets)
├── tests/                       pytest suite (about 114 test functions), conftest.py, GUI tests in test_gui.py
├── tools/
│   ├── gen_schemas.py           JSON Schemas and examples from the pydantic models (--check in CI)
│   ├── gen_test_vectors.py      DSP test vectors (--check in CI)
│   ├── check_prompt_embedding.py  checks the prompt embedding
│   ├── benchmark.py             performance benchmark
│   └── gen_notices.py           third-party notices
├── packaging/
│   ├── build.py                 PyInstaller onedir build with smoke test and docs
│   ├── sonicclue.spec           PyInstaller spec
│   ├── entry_cli.py, entry_gui.py   bundle entry points
├── docs/
│   ├── USER_GUIDE.md, RELEASE_NOTES.md, CONTINUATION.md
│   ├── specs/                   specification package (requirements, architecture, module contracts, ADRs, schemas, contracts examples, matrices)
│   ├── prompts/                 specification authoring prompt and implementation handoff
│   └── wiki/                    the wiki pages
└── .github/workflows/ci.yml     tests on ubuntu-22.04 and windows-latest, then the bundle build
```

## Key symbols

| Symbol (file:approx line) | Purpose |
|---|---|
| `class Document`, `CaptureManifest`, `CalibrationProfile`, `ClockMapping`, `AnalysisConfig` (`domain/model.py:50`, `298`, `346`, `390`, `417`) | core contracts |
| `SensorKind`, `SensorDescriptor`, `ChannelConfig` (`model.py:149`, `183`, `224`) | sensors and channels |
| `SupportLevel`, `SUPPORT_ORDER` (`model.py:704`, `712`) | ordinal support levels |
| `analyze()` (`analysis/pipeline.py:66`) | the analysis entry point |
| `tone_level_at()`, `band_power()` (`pipeline.py:291`, `307`) | point queries on analysis arrays |
| `diagnose()` (`diagnostics/engine.py:683`) | the diagnostic entry point. Returns a `DiagnosisSnapshot` |
| `_rules()` (`engine.py:458`) | the rule set |
| `_conclude()` (`engine.py:663`) | conclusion and abstention |
| `RULESET_VERSION` (`engine.py:53`) | ruleset version |
| `compare()` (`compare/compare.py:50`) | A vs B comparison. `Item` at `:37` |
| `SonicClueApp` (`app/service.py:153`) | facade for the GUI and CLI: cases, equipment, captures, analysis, compare, reports |
| `SonicClueApp.start_capture()` (`service.py:298`), `capture_blocking()` (`:347`) | capture |
| `SonicClueApp.analyze()` (`service.py:429`) | analysis |
| `CaptureSpec` (`service.py:86`), `CaptureHandle` (`service.py:98`) | capture arguments and handle |
| `default_workspace()` (`service.py:76`) | workspace path (`SONICCLUE_WORKSPACE` overrides) |
| `CaseStore` (`storage/store.py:119`), `Workspace` (`store.py:444`) | per-case SQLite and workspace |
| `PortAudioBackend` (`acquisition/backends.py:64`), `SimulatedBackend` (`:254`), `SimWorld` (`:135`) | audio backends |
| `CancelToken` and job runner (`app/jobs.py`) | background jobs |
| `run_demo()` (`app/demo.py:37`) | simulated investigation |
| `build_report()` (`reporting/builder.py:88`) | report document |
| `render_html`, `render_pdf`, `render_json`, `render_csv_zip` (`reporting/render.py:52`, `85`, `121`, `125`) | report outputs |
| `main()` (`cli/main.py`, argparse at about line 420) | CLI |
| `main()` (`gui/main.py:119` area) | GUI window |

## Where do I find X / to change X, edit Y

| I want to... | Edit |
|---|---|
| add a field to a document | `domain/model.py` (pydantic model), then `python tools/gen_schemas.py` to refresh the schemas and examples, and `python docs/specs/contracts/validate_examples.py` |
| change how a channel is recorded | `acquisition/backends.py` (device side), `acquisition/session.py` (chunks, gaps) |
| change the simulator | `acquisition/backends.py` (`SimWorld`, `_SimStream`), `app/demo.py` |
| change an analysis measure | `dsp/*.py` for the maths, `analysis/pipeline.py` for how it is wired and stored |
| change coherence or transfer | `dsp/cross.py` |
| change comparison validity rules | `compare/comparability.py` |
| change a diagnostic rule | `diagnostics/engine.py` (`_rules`, `_extract_*`), bump the rule revision and `RULESET_VERSION` |
| change next-test suggestions | `diagnostics/next_tests.py` |
| add or change a guided procedure | `procedures/definitions/procedures.json` |
| change storage layout or add a migration | `storage/store.py`, `storage/migrations.py` |
| change report content | `reporting/builder.py`. Layout and format in `reporting/render.py` |
| add a CLI command | `cli/main.py` (add a `sub.add_parser`) |
| add a GUI screen | new `gui/screens_*.py` (or an existing one), registered in `gui/main.py` navigation |
| change a workflow the app runs | `app/service.py` (the facade is the only API the GUI and CLI should call) |
| change packaging | `packaging/build.py`, `packaging/sonicclue.spec` |
| change the bundled notices | `tools/gen_notices.py` |
| change the architecture rule set | `tests/test_contracts_architecture.py`, and the ADRs in `docs/specs/decisions/adr/` |

## Gotchas for navigation

- `docs/specs/` is the authority on behaviour. When code and spec disagree, the spec and ADRs say what was intended.
- `dsp/` must not import Qt, sounddevice, soundfile or the database. A test enforces this.
- The GUI and CLI should go through `SonicClueApp`, not into `storage` or `acquisition` directly.
