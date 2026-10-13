# 04 Module contracts

## 1 Canonical contracts

The canonical definitions are the pydantic models in `src/sonicclue/domain/model.py`. JSON Schemas in `schemas/` are generated from them, so there is no second hand-written definition to drift. CI fails if they are stale (`tools/gen_schemas.py --check`).

| ID | Contract | Model | Schema |
|---|---|---|---|
| CON-001 | Case | `Case` | `case.schema.json` |
| CON-002 | Capture manifest | `CaptureManifest` | `capture_manifest.schema.json` |
| CON-003 | Channel descriptor | `ChannelConfig` (+ `Placement`) | `channel_config.schema.json` |
| CON-004 | Sensor descriptor | `SensorDescriptor` | `sensor_descriptor.schema.json` |
| CON-005 | Calibration profile | `CalibrationProfile` | `calibration_profile.schema.json` |
| CON-006 | Analysis configuration | `AnalysisConfig` | `analysis_config.schema.json` |
| CON-007 | Analysis result | `AnalysisResult` | `analysis_result.schema.json` |
| CON-008 | Clock mapping | `ClockMapping` | `clock_mapping.schema.json` |
| CON-009 | Quality flag | `QualityFlag` | `quality_flag.schema.json` |
| CON-010 | Procedure definition | `ProcedureDef` | `procedure_definition.schema.json` |
| CON-011 | Procedure execution state | `ProcedureRun` | `procedure_run.schema.json` |
| CON-012 | Evidence item | `EvidenceItem` | `evidence_item.schema.json` |
| CON-013 | Hypothesis result | `Hypothesis` (in `DiagnosisSnapshot`) | `hypothesis.schema.json`, `diagnosis_snapshot.schema.json` |
| CON-014 | Report | `ReportDocument` | `report.schema.json` |
| CON-015 | Portable archive manifest | `ArchiveManifest` | `archive_manifest.schema.json` |
| CON-016 | Sensor bridge messages | `BridgeHello`, `BridgeData`, `BridgeError` (binary framing in spec 06 section 6) | `bridge_*.schema.json` |
| CON-017 | Comparison result | `ComparisonResult` | `comparison_result.schema.json` |

## 2 Cross-contract conventions (ADR-0014, ADR-0015)

* **Versioning:** every top-level document has `schema_version` (semver, currently 1.0.0). Readers accept the same major version with minor <= theirs. A newer minor or major version is rejected (`SC_SCHEMA_VERSION`) rather than partially read. Older majors are migrated (spec 13 section 6). Minor versions may only add optional fields.
* **Unknown fields:** rejected (`additionalProperties: false`) in every object. This catches typos, documents from newer versions, and injected content in untrusted imports.
* **Enum evolution:** new enum values require a minor version bump. Older readers reject documents containing them (which follows from the versioning rule).
* **Null vs absent vs unavailable vs invalid:** optional fields are omitted when absent. Readers treat JSON `null` exactly like absence (pydantic `Optional`), and writers never emit `null` (`exclude_none`). A *measured* quantity that may be unavailable (not measured, not applicable) or invalid (measured, then rejected) uses `TaggedValue{status, value?, reason?}`, and a reason is required unless the status is `valid`.
* **Time:** timezone-aware UTC datetimes (RFC 3339). **Sample indices:** zero-based per capture stream. **Ranges:** half-open `[start_frame, end_frame)`.
* **Units:** SI (Hz, s, Pa, m/s^2, m/s, V). Raw samples are FS (full scale, ±1.0). Levels carry an explicit reference label (`level_ref`, e.g. "dB re 20 uPa", "dBFS"). Linear values are in `unit`.
* **Coordinates:** sensor `axis` is one of x, y, z, normal, omni or unknown. `Placement.orientation` is free text stating the right-handed frame relative to the mounting surface (e.g. "+z normal to desk").
* **Validation errors:** surfaced as `SonicClueError` subclasses with a stable `code` (section 3). Pydantic validation errors give field location and message. The CLI maps them to exit code 1.
* **Limits:** max 64 channels, 768 kHz rate, 100 000 chunks per capture, 4 h per live capture, 8 GiB per audio import, archives ≤ 8 GiB compressed / 16 GiB expanded / 50 000 entries / ratio ≤ 200, bridge payload ≤ 4096 bytes and ≤ 512 samples per packet, string fields bounded as declared in the models.

## 3 Error catalogue (stable codes)

| Code | Raised by | Meaning / user action |
|---|---|---|
| SC_VALIDATION | any | invalid input (field and reason given) |
| SC_SCHEMA_VERSION | storage, contracts | document/store from a newer SonicClue: upgrade |
| SC_STATE | sessions, procedures, output | operation not allowed in the current state |
| SC_DEVICE / SC_DEVICE_FORMAT / SC_NO_AUDIO_BACKEND / SC_NO_DEVICE | acquisition | device missing, unsupported format, PortAudio unavailable |
| SC_STORAGE / SC_CASE_EXISTS / SC_NOT_A_CASE / SC_READONLY / SC_IMMUTABLE | storage | storage errors; originals cannot be changed |
| SC_INTEGRITY | storage | checksum mismatch, damaged document, missing files |
| SC_CASE_LOCKED | storage | case open elsewhere |
| SC_IMPORT_UNSAFE | archive | archive rejected by safety checks |
| SC_IMPORT_FORMAT / SC_IMPORT_SIZE / SC_BRIDGE_NO_HELLO / SC_BRIDGE_EMPTY | importer | unsupported/oversized/incomplete import |
| SC_CALIBRATION, SC_CAL_RELATIVE_ONLY, SC_CAL_CLIPPED, SC_CAL_SHORT, SC_CAL_NO_TONE, SC_CAL_LOW_SNR, SC_CAL_UNSTABLE | sensors.calibration | calibration refused (reason) |
| SC_ANALYSIS | analysis/compare | inconsistent analysis input |
| SC_OUTPUT_SAFETY, SC_OUTPUT_NOT_ARMED | stimulus/app | output interlock refused |
| SC_UNKNOWN_PROCEDURE, SC_PROCEDURE_PARAMS | procedures | bad procedure id/parameters |
| SC_CAPTURE_EMPTY | app | capture produced no samples |
| SC_NO_CASE, SC_NOT_FOUND | app | no open case / unknown id |
| SC_CANCELLED | jobs | user cancelled |

## 4 Public module APIs

Format: purpose → API → inputs/outputs (units) → errors → threading → tests. The full reuse records are in spec 22.

* **`sonicclue.dsp.spectral`**: `window_metrics(name, n)`; `plan_segments(mask, fs, resolution_hz, overlap, min_averages, min_nperseg) -> SegmentPlan|None`; `masked_welch(x, fs, plan, window) -> (f[Hz], psd[unit^2/Hz])`; `masked_csd(x, y, ...) -> (f, Pxx, Pyy, Pxy)`; `spectrogram(...)`; `integrate_band(f, psd, lo, hi) -> unit^2`; `fractional_octave_bands(kind, fmin, fmax)`; `band_levels(...)`. Pure, thread-safe, no I/O. Tests: `test_dsp_numerics.py`.
* **`sonicclue.dsp.tonal`**: `detect_tones(...) -> [ {freq_hz, power, rms, prominence_db, q, bin} ]`; `harmonic_families(peaks, df)`; `noise_floor_db(psd)`.
* **`sonicclue.dsp.cross`**: `coherence_threshold(n, alpha)`; `coherence_and_transfer(Pxx, Pyy, Pxy) -> (coh, H1, ok_mask)`; `estimate_delay(x, y, fs, max_lag_s) -> (seconds|None, ambiguity)`; `accel_to_velocity_psd`.
* **`sonicclue.dsp.transient`**: `detect_events(x, valid, fs, frame_s, threshold_db)`; `envelope_spectrum(x, fs, band, fmax)`.
* **`sonicclue.dsp.levels`**: `screen_channel(x, fs, channel, gaps) -> Screening(valid mask, flags)`; `level_stats(x, valid) -> (ac_rms, peak, dc)`.
* **`sonicclue.dsp.stats`**: `compare_levels(a_db, b_db, sd_a, sd_b) -> (delta, u95, significant, "measured"|"estimated")`; `welch_level_sd_db(n_eff, bins)`.
* **`sonicclue.dsp.signals`**: deterministic generators (seeded).
* **`sonicclue.sensors.calibration`**: `evaluate(profile, channel, sensor) -> CalStatus`; `calibrate_from_tone(...) -> CalibrationProfile`; `profile_from_datasheet(...)`; `parse_fr_file(text, kind)`; `fr_correction_db(profile, f)`.
* **`sonicclue.sensors.capabilities.capabilities(channels, sensors, calibrated, shared_clock) -> Capabilities`**
* **`sonicclue.sensors.bridge`**: `BridgeDecoder.feed(bytes)`, `encode_*`, `assemble(messages, decoder) -> BridgeAssembly`.
* **`sonicclue.sync`**: `estimate_mapping(ref, fs_ref, other, fs_other, ref_id, other_id) -> (ClockMapping, flags, other_resampled)`; `align(...)`; `check_timestamps(...)`; `shared_clock_mapping(...)`.
* **`sonicclue.analysis.pipeline.analyze(manifest, data[frames, ch] FS, sensors, calibrations, config, cancel) -> AnalysisOutput(result, arrays)`**. Pure; cancellation between channels/pairs.
* **`sonicclue.compare.compare(case_id, group_a, group_b, channel_label, ...) -> ComparisonResult`**; `comparability.check(ma, mb, label, aa, ab)`.
* **`sonicclue.diagnostics.diagnose(DiagnosticInputs) -> DiagnosisSnapshot`** (deterministic).
* **`sonicclue.procedures`**: `library()`, `get(id)`, `start`, `current`, `acknowledge`, `record_capture`, `record_intervention`, `pause/resume/cancel/fail`, `progress`. Pure state transitions.
* **`sonicclue.stimulus.OutputController`**: `arm(...)`, `play(rec, s)`, `audition(data, fs)`, `stop()`, `wait()`; `generate(rec, fs, s)`.
* **`sonicclue.storage.store`**: `Workspace(root)`, `CaseStore(path)` with `put/get/list/delete`, `save_capture`, `load_capture_data`, `save_analysis/load_arrays`, `verify`, `recover`, `audit/audit_log`, `snapshot_db`. `storage.archive.export_case/import_case(limits)`.
* **`sonicclue.acquisition`**: `PortAudioBackend`, `SimulatedBackend`, `CaptureSession(backend, device, rate, channels, sink, duration_s)` → `start/stop/cancel/wait/snapshot`; `importer.probe/import_audio/decode_bridge_dump`.
* **`sonicclue.reporting`**: `builder.build_report(ReportInputs) -> (ReportDocument, figures)`; `render.render_html/pdf/json/csv_zip`.
* **`sonicclue.app.SonicClueApp`**: the facade used by GUI and CLI (spec 12 section 9 maps every command to these methods).
