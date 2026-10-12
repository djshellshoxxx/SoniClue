# 12 GUI and user experience

Code: `src/sonicclue/gui/` (PySide6 + pyqtgraph). Entry: `sonicclue` (GUI), `sonicclue-cli`. Tests: `tests/test_gui.py` (offscreen; drives real controls), CLI in `tests/test_workflows.py`.

## 1 Layout and style

Left navigation (11 screens; the New-investigation wizard is a dialog, making 12 screens in total) and a stacked content area. The status bar shows the current case, a Guided/Expert mode switch and messages. The Circuit Drift Labs palette: background #0d1420, panels #152033/#1c2a40, borders #2a3b55, text #e6edf3, accent #3fa7ff, ok #3fbf7f, warning #e3b341, error #f85149. High-contrast plot pens on #0b111b. No decorative animation. Fusion style for consistent DPI scaling. Minimum window 1024×680. Splitters keep the layout usable from 1366×768 to 4K (Qt high-DPI scaling is on by default in Qt 6).

Keyboard: Ctrl+1…9, Ctrl+0, Ctrl+- switch screens; Ctrl+N new investigation; **Esc stops any test signal**; F1 help. Every button and meter has an accessible name. Every plot has a table alternative (Tones, Bands, Quality flags tables; comparison tone table).

Threading: heavy work runs through `GuiContext.run` on job threads, with results delivered by a queued signal. Live views poll `CaptureSession.snapshot()` every 100 ms.

## 2 Screens

| # | Screen | Main controls | Data dependencies | Error/empty states |
|---|---|---|---|---|
| 1 | Case dashboard | New, Open, Open demo (simulated), Import/Export archive, Verify integrity, Delete; case table; current case summary | Workspace.list_cases, latest diagnosis | empty: "No investigations yet…"; damaged case shown red with error; locked shown; recovered-capture notice on open |
| 2 | New investigation wizard | title*, description, character checkboxes, receiver, when, band; equipment table (name, kind); sensors table (id, kind, model) | create_case | validation error dialog (duplicate ids, missing title) |
| 3 | Devices & sensors | backend, device, rate, exclusive; channel table (input #, label, sensor, position, location, mounting, gain, AGC, calibration); Apply; sensor editor | devices(), qualification status, case sensors/calibrations | no backend → message + simulator; invalid format → dialog; AGC not off → warning; tier/capability line |
| 4 | Calibration | profiles table; tabs: from calibrator recording, from response file, library copy; per-channel validity line | calibrations, captures | refusal reasons (no tone, low SNR, unstable, relative-only) shown verbatim |
| 5 | Live measurement | condition label, equipment states, duration, Start/Stop/Cancel, meters with clip lamps, live spectrum; test signal: device, type, freq, level, duration, Arm…, Play, STOP | base capture spec | start errors dialog; clipping lamp; dropout counter; output state label |
| 6 | Analysis | capture list; re-analyse (expert: resolution, window); Listen; plain-language summary; tabs: Spectrum (with tone markers), Waveform, Spectrogram, Coherence*, Envelope*, Tones table, Bands table*, Quality flags (*expert) | analysis, arrays | no captures → guidance text; loading via job |
| 7 | Hypotheses & evidence | Update diagnosis; conclusion banner with abstention reasons; hypothesis tree (why, + supporting, − conflicting, missing tests, rules in expert); evidence list with class and usable; next tests with reasons; Start selected next test; Add note | latest diagnosis | "No diagnosis yet…" |
| 8 | Guided tests | procedure list with description (purpose, preconditions, safety, confounds); parameter selector; Start; active run: steps with progress, instruction (expert notes), intervention form, Record with settle countdown, gate result, Pause/Resume, Cancel, Update diagnosis | procedure library, runs | gate rejection text; arm prompt for stimulus steps; resume of active run on case open |
| 9 | Before/after | A and B multi-select lists, channel, labels, band, Compare; result text with comparability issues; band delta chart (green = significant reduction, red = significant increase), tone table, previous comparisons; **Align (multi-device)** tab | captures, comparisons | overlap/selection errors; NOT COMPARABLE banner text |
| 10 | Diagnostic history | diagnoses list → detail; procedure runs (continue selected); activity log | diagnoses, runs, audit log | empty lists |
| 11 | Report builder | format (HTML/PDF/JSON/CSV), redaction checkboxes, update diagnosis first, Preview, Export… | build_report | export error dialog; open folder |
| 12 | Settings & qualification | mode, workspace, auto-analyse; analysis defaults (validated); self-test; loopback qualification (backend, output #, input #); qualification table; environment/licence info | settings, qualification matrix | invalid settings dialog |

Guided mode shows plain-language summaries ("level −35 dBFS; tones at 117 Hz… (relative level, not calibrated)"; "channels share components… related signals, not proof of a path"). Expert mode adds numbers (crest, floor, averages, df, ENBW), coherence/envelope/band tabs, rules and expert notes. Both use the same engine and data.

## 3 Feature paths and states

Each user-facing feature follows: control → validation → app method → domain/numerics → persistence → UI → export → test. The complete matrix is `matrices/feature-wiring.csv`. States per feature:

| Feature | loading | empty | invalid | cancelled | partial | failed | recovered |
|---|---|---|---|---|---|---|---|
| Create case | – (instant) | no cases → guidance | wizard validation dialog | wizard cancel → nothing stored | n/a: creation is atomic | storage error dialog | n/a |
| Live capture | "recording…" meters | no device → message | format check dialog | Cancel → discarded (confirmed) | device loss → saved as partial + flag | start error dialog / writer failure → FAILED | journal recovery on next open, notice shown |
| Analysis | job + status "Loading analysis" | no captures → text | SHORT_CAPTURE/SILENCE flags shown | job cancel on shutdown | n/a | error dialog | re-analyse (arrays missing → integrity message) |
| Guided procedure | settle countdown, progress | no active run → instructions | gate rejection → repeat | Cancel test (captures kept) | paused state | fail() with reason | active run resumed after restart |
| Comparison | job | nothing selected → error | NOT COMPARABLE banner | n/a | n/a | error dialog | n/a |
| Diagnosis | job | "No diagnosis yet" | inconclusive banner with reasons | n/a | n/a | error dialog | history keeps every snapshot |
| Report export | job | – | – | file dialog cancel | – | error dialog | – |
| Archive import | job | – | unsafe archive → SC_IMPORT_UNSAFE | dialog cancel | – | temp dir removed | – |
| Stimulus | ARMED/PLAYING label | no output device message | interlock refusal dialog | STOP/Esc | – | device loss → DISARMED | never resumes |

## 4 CLI (same services)

`sonicclue-cli [--workspace W] [--json] [--sim-speed S] <command>`: `info`, `selftest`, `devices`, `case list|new|show|verify|annotate|history`, `capture`, `import [--bridge]`, `analyze`, `compare`, `align`, `diagnose [-v]`, `procedure list|start|step|pause|resume|cancel`, `calibrate`, `report`, `archive export|import`, `stimulus --confirm`, `qualify`, `demo`. Exit codes: 0 ok, 1 validation, 2 runtime/device, 3 integrity, 130 interrupted.
