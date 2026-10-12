# 22 Reusable module catalog

Modules that can be used in other Circuit Drift Labs products **without** importing the SonicClue application (verified: importing `dsp` + `domain` loads no Qt, sounddevice, soundfile, sqlite3 or matplotlib; `tests/test_contracts_architecture.py::test_reusable_dsp_has_no_heavy_imports`).

Format: purpose → public API → inputs → outputs → units → dependencies → prohibited dependencies → behaviour → errors → tests → reuse example → portability limits.

| ID | Module | Purpose | Public API | In / out, units | Depends on | Prohibited | Errors | Tests | Portability |
|---|---|---|---|---|---|---|---|---|---|
| MOD-01 | `sonicclue.dsp.spectral` | masked Welch PSD/CSD, window metrics, bands, spectrogram | `plan_segments`, `masked_welch`, `masked_csd`, `window_metrics`, `integrate_band`, `fractional_octave_bands`, `band_levels`, `spectrogram` | float arrays (any unit) + fs Hz → f Hz, unit²/Hz | numpy, scipy | Qt, devices, storage | returns None for impossible plans | `test_dsp_numerics.py` | pure Python; any OS |
| MOD-02 | `sonicclue.dsp.tonal` | tone detection, Q, harmonic families | `detect_tones`, `harmonic_families`, `noise_floor_db` | PSD → tones (Hz, unit², dB) | numpy, scipy | same | – | same | any |
| MOD-03 | `sonicclue.dsp.cross` | coherence, H1, delay, significance | `coherence_and_transfer`, `coherence_threshold`, `estimate_delay`, `accel_to_velocity_psd` | spectra → γ², H1, s | numpy, scipy | same | NaN masks | same | any |
| MOD-04 | `sonicclue.dsp.transient` | events, envelope spectrum | `detect_events`, `envelope_spectrum` | samples → event times s, modulation PSD | numpy, scipy | same | – | same | any |
| MOD-05 | `sonicclue.dsp.levels` | screening and level statistics | `screen_channel`, `level_stats` | FS samples → mask + flags | numpy, domain | same | – | same | any |
| MOD-06 | `sonicclue.dsp.stats` | comparison statistics | `compare_levels`, `welch_level_sd_db` | dB lists → delta, u95 | numpy, scipy | same | – | same | any |
| MOD-07 | `sonicclue.dsp.signals` | deterministic test signals | sine, harmonics, noises, chirp, AM/FM, resonator, delay, drift, dropouts | → float arrays | numpy, scipy | same | – | used everywhere | any |
| MOD-08 | `sonicclue.domain` | contracts, units, errors | pydantic models, `units.*`, error classes | JSON ↔ models | pydantic | everything else | pydantic ValidationError, SonicClueError | contract tests | any |
| MOD-09 | `sonicclue.sync` | clock mapping and alignment | `estimate_mapping`, `align`, `check_timestamps` | two signals → ClockMapping | dsp, domain | devices, storage | flags | `test_calibration_sync.py` | any |
| MOD-10 | `sonicclue.sensors.bridge` | serial sensor-bridge codec | `BridgeDecoder.feed`, `encode_*`, `assemble` | bytes → messages/arrays | numpy, domain | – | counts errors, flags | `test_acquisition.py` | any |
| MOD-11 | `sonicclue.sensors.calibration` | calibration conventions | `calibrate_from_tone`, `evaluate`, `parse_fr_file`, `fr_correction_db`, `profile_from_datasheet` | FS samples → CalibrationProfile | dsp, domain | – | CalibrationError codes | `test_calibration_sync.py` | any |
| MOD-12 | `sonicclue.storage.writer` + `files` | journaled chunked float32 WAV writer, atomic files | `CaptureWriter`, `read_chunks`, `atomic_write_*`, `sha256_file` | blocks → files | numpy, soundfile | Qt | StorageError | `test_storage.py` | needs libsndfile |
| MOD-13 | `sonicclue.storage.archive` | safe zip import/export pattern | `export_case`, `import_case`, `ImportLimits` | | storage.store | Qt | ImportSafetyError | `test_storage.py` | any |
| MOD-14 | `sonicclue.stimulus` | interlocked test-signal output | `OutputController`, `generate` | StimulusRecord → audio | acquisition backend protocol | storage | SafetyError | `test_workflows.py` | needs a backend |
| MOD-15 | `sonicclue.acquisition.session` | bounded-queue capture with gap accounting | `CaptureSession` + `CaptureSink` protocol | device blocks → sink | numpy, domain | storage, Qt | DeviceError, StateError | `test_acquisition.py` | needs a backend |
| MOD-16 | `sonicclue.diagnostics` | rule-based evidence/hypothesis engine pattern | `diagnose(DiagnosticInputs)` | contracts → DiagnosisSnapshot | domain, procedures | storage, Qt | – | adversarial suite | SonicClue-specific rules; the pattern is reusable |

Reuse example (MOD-01 + MOD-02 in another product):

```python
import numpy as np
from sonicclue.dsp import spectral, tonal
plan = spectral.plan_segments(np.ones(len(x), bool), fs, resolution_hz=1.0, overlap=0.5, min_averages=8)
f, psd = spectral.masked_welch(x, fs, plan)
tones = tonal.detect_tones(f, psd, "hann", spectral.window_metrics("hann", plan.nperseg).enbw_hz(fs), 10, 20, fs / 2, 10)
```

Licensing for reuse inside Circuit Drift Labs follows the project licence (pending DEC-009b). The dependencies are BSD/MIT.
