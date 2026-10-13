# 03 System architecture

## 1 Selected stack (ADR-0003, ADR-0012, ADR-0013)

| Concern | Choice | Status | Rejected alternatives (reason) |
|---|---|---|---|
| Language | Python 3.11+ (CPython) | SELECTED_DEFAULT | C++/Qt (slower to build; numerical reuse harder); Rust (ecosystem for DSP + GUI less mature); Electron/TS (heavy runtime; numerical stack weak) |
| Numerics | NumPy 2.x, SciPy 1.13+ (BSD) | SELECTED_DEFAULT | custom FFT/Welch (no justification; established methods reused) |
| Audio I/O | PortAudio via `sounddevice` (MIT) | SELECTED_DEFAULT | pyaudio (unmaintained); rtaudio (no maintained Python binding); native WASAPI module (cost; not justified by profiling) |
| Audio files | libsndfile via `soundfile` (BSD / LGPL lib) | SELECTED_DEFAULT | stdlib `wave` (no float32/FLAC) |
| Contracts | pydantic v2 (MIT), JSON Schema 2020-12 generated | SELECTED_DEFAULT | hand-written schemas (duplicate definitions drift) |
| Storage | SQLite (stdlib) + chunked WAV + npz | SELECTED_DEFAULT | HDF5 (heavier dependency, less transparent); pure JSON files (no transactions) |
| GUI | PySide6 (LGPLv3) + pyqtgraph (MIT) | SELECTED_DEFAULT | PyQt (GPL/commercial); Tk (insufficient for plots/accessibility); web UI (offline packaging, device access) |
| Report figures/PDF | matplotlib (PSF-style) + reportlab (BSD) | SELECTED_DEFAULT | Qt printing (couples reports to GUI; reports must render headless) |
| Packaging | PyInstaller onedir (GPL with bootloader exception) | SELECTED_DEFAULT | Nuitka (longer builds); MSIX (signing required) |

No native extension is written by the project. Profiling (spec 16) showed no hotspot that justifies one. The one demonstrated bottleneck, memory in long analyses, was fixed algorithmically.

## 2 Modules and dependency direction

```
                 +-----------+      +-----------+
                 |    gui    |      |    cli    |        presentation (PySide6 only in gui)
                 +-----+-----+      +-----+-----+
                       \\                 /
                        v               v
                     +---------------------+
                     |  app (services,     |        orchestration, jobs, settings, demo
                     |  jobs, demo)        |
                     +----------+----------+
        +-----------+-----------+-----------+------------+-------------+-------------+
        v           v           v           v            v             v             v
  acquisition   storage    procedures  diagnostics   reporting     stimulus    qualification
  (backends,    (store,    (library,   (engine,      (builder,     (generator, (selftest,
   session,      writer,    executor)   next_tests)   render)       output SM)  loopback)
   importer)     archive)       |           |            |             |
        |           |           |           v            |             |
        |           |           |        compare ---------+             |
        |           |           |           |                          |
        |           |           |        analysis (pipeline)            |
        |           |           |           |                          |
        |           |           |   sensors (calibration, capabilities, bridge)   sync
        |           |           |           |                          |
        +-----------+-----------+-----------+-----------+--------------+
                                            v
                                          dsp  (pure numpy/scipy)
                                            |
                                            v
                                         domain (contracts, units, errors)
```

The rules are enforced by `tests/test_contracts_architecture.py` (AST import scan, one test per source file):
* `domain` imports nothing from SonicClue. `dsp` imports only `domain`.
* Only `gui` may import PySide6/pyqtgraph. Only `acquisition` (and the app's environment report) may import sounddevice.
* `storage` never imports acquisition, analysis, diagnostics or reporting. `acquisition` never imports storage. The app wires a `CaptureWriter` into a `CaptureSession` through the `CaptureSink` protocol (dependency injection).
* `app` may not import `cli` or `gui`. `cli` may not import `gui`.
* A separate test asserts that importing `dsp` + `domain` loads neither Qt, sounddevice, soundfile, sqlite3 nor matplotlib (reusability).

## 3 Data flow (capture to report)

```
device -> CaptureSession(callback -> bounded queue -> writer thread) -> CaptureWriter(chunk WAV + journal)
       -> CaptureManifest (validated) -> CaseStore(case.db, immutable)
       -> analysis.pipeline(manifest, samples, sensors, calibrations) -> AnalysisResult + arrays.npz
       -> compare(group A, group B) -> ComparisonResult (comparability + uncertainty)
       -> procedures run state (gates) -> diagnostics.diagnose(case, captures, comparisons, runs) -> DiagnosisSnapshot
       -> reporting.build_report -> ReportDocument -> HTML/PDF/JSON/CSV
```

Every derived document names its inputs (capture ids, comparison ids, run ids) and the algorithm or ruleset version.

## 4 Process and thread model

| Thread | Owner | Work | Must not |
|---|---|---|---|
| GUI (Qt main) | gui | widgets, timers (100-200 ms polling of live snapshots) | analysis, file I/O beyond small reads, waits on devices |
| PortAudio callback | acquisition backend | copy one block into the queue, or record a drop | block, wait on locks held elsewhere, touch storage |
| capture-writer | CaptureSession | drain queue, zero-fill gaps, write chunks, journal, live meters | call back into the GUI |
| sc-job x2 | app.jobs | analysis, compare, diagnose, reports, archive, demo, verify, self-test | touch Qt objects (results return via a queued signal) |
| output watchdog | stimulus | stop playback at deadline | resume output |

Lock inventory and ordering: `CaptureSession._mon_lock` (live meters only, never held during sink I/O); `CaptureWriter._lock` (buffer); `CaseStore._wlock` (SQLite write transactions, RLock); `OutputController._lock` (arming/play), with `_mute_lock` (RLock) taken inside it. There is no lock nesting across subsystems, except `OutputController._lock` → `_mute_lock`.

## 5 Lifecycle and shutdown order (SM-005)

GUI close: (1) if recording, ask, then stop and finalize (data kept); (2) `output.stop()` (muted, disarmed); (3) `jobs.shutdown(wait=True)` (pending jobs cancelled, running ones reach a cancellation point); (4) close the case (SQLite connections closed, lock file removed). A crash at any point leaves journals and the lock. The next open reclaims a stale lock (dead PID on the same host, or older than 12 h) and recovers interrupted captures.

## 6 Resource ownership (RES-*)

| ID | Resource | Created by | Owned by | Accessed by | Transfer | Closed by | On failure |
|---|---|---|---|---|---|---|---|
| RES-01 | device input stream | `CaptureSession.start` | session | backend thread | none | writer thread at loop exit | FAILED state; partial data kept |
| RES-02 | callback block buffer | PortAudio | backend | callback only | copied into the queue | PortAudio | n/a |
| RES-03 | capture queue | session | session | callback (put), writer (get) | blocks move to the writer | GC with the session | overflow → gap |
| RES-04 | writer thread | session | session | | | joins on terminal state | error → FAILED |
| RES-05 | chunk files | `CaptureWriter` | capture dir | writer; later read-only | read-only after chunk flush | writer `close()` | `.part` files removed on recovery |
| RES-06 | SQLite connections | `CaseStore._conn` (per thread) | store | owning thread | none | `store.close()` | transaction rollback |
| RES-07 | case lock file | `CaseStore.__init__` | store | | | `store.close()` | stale lock reclaimed |
| RES-08 | analysis arrays | pipeline | AnalysisOutput → store | job thread | saved to npz | GC | job error → shown, nothing persisted |
| RES-09 | temp export files | archive/report | function scope | | atomic rename | `finally`/TemporaryDirectory | removed |
| RES-10 | output stream | `OutputController._start` | controller | PortAudio | | `_mute` | muted + disarmed |
| RES-11 | UI subscriptions (Qt signals) | screens | GuiContext | GUI thread | | widget destruction | n/a |
| RES-12 | bridge serial data | user dump file | importer | job thread | decoded to arrays | function scope | decode errors counted and flagged |
