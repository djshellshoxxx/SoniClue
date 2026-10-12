# 06 Sensors and calibration

Code: `src/sonicclue/sensors/` (calibration, capabilities, bridge), contracts CON-003/004/005/016. Tests: `tests/test_calibration_sync.py`, `tests/test_acquisition.py` (bridge).

## 1 Sensor model

`SensorDescriptor{id, kind, model, serial, quantity, axis, usable_band_hz, notes}`. Kinds: measurement_mic, studio_mic, builtin_mic, contact_pickup, piezo_disc, analog_accelerometer, mems_accelerometer, line_input, other. Default quantities: microphones → sound_pressure, accelerometers → acceleration, contact/piezo/line → **relative** (enforced: these kinds cannot declare a physical quantity).

Per-capture placement lives in `ChannelConfig.placement{location, position_id, distance_m, orientation, mounting, mount_surface}` plus `input_gain_db`, `agc` (off/on/unknown) and `processing[]`. These fields drive comparability (spec 09 section 5).

New hardware is added by implementing an `AudioBackend` (spec 05) or a bridge decoder. The domain and reasoning modules never see device specifics.

## 2 Calibration conventions (DEC-007, INV-006)

* `sensitivity_fs_per_unit` = digital RMS (FS) produced by 1 unit RMS of the physical quantity at `reference_freq_hz` and `reference_gain_db`. **physical = FS / sensitivity.**
* `fr_correction[]` = dB to **add** to the measured level (true = measured + correction), interpolated linearly in dB over log-frequency. Outside `valid_band_hz` it is NaN: values there are uncorrected and flagged `CAL_OUT_OF_BAND`. Peaks carry `cal_in_band`, and bands outside the calibration band are marked invalid.
* Response files: two columns (freq Hz, dB), with headers starting `*`, `#` or `"`, and a `Sens Factor =x dB` header recognised. The user must declare the file type: **response** (sensor deviation from flat, negated on import) or **correction** (already dB to add). This removes the common sign ambiguity (tested: `test_fr_file_direction_response_is_negated`).
* Uncertainty: expanded, k=2, in dB. From a calibrator: sqrt(calibrator² + (stability/2)² + 0.05²). From a datasheet: 2 dB default (VALIDATION_REQUIRED).
* Validity (`calibration.evaluate`): sensor ids match; not expired; |channel gain - reference gain| ≤ 0.1 dB when both are known (otherwise usable with a warning "gain not recorded"). A gain mismatch is INVALID, and analysis falls back to relative dBFS with the flag shown. Recalibration triggers: gain change, sensor change, interface change (shown as a caveat in comparisons), expiry.
* Calibrator procedure (`calibrate_from_tone`): rejects a clipped recording, recordings < 2 s, no tone within ±3% of the reference frequency, SNR < 30 dB, or level instability > 0.2 dB across quarters.
* Contact pickups/piezo/line inputs: calibration attempts raise `SC_CAL_RELATIVE_ONLY`.

## 3 Physical units

Pa (dB re 20 µPa), m/s² (dB re 1 µm/s²), m/s (dB re 1 nm/s), V (dBV), FS (dBFS) per ISO 1683. Velocity from acceleration: `dsp.cross.accel_to_velocity_psd` with a 2 Hz lower limit (library function; the UI shows acceleration).

## 4 Capability tiers (provisional, not paid editions)

| Tier | Sensors | Can legitimately measure / compare / infer | Must not claim |
|---|---|---|---|
| 1 | microphone only, uncalibrated | relative dBFS levels, spectra, tones, harmonic families, transients; on/off, position, intervention comparisons at fixed gain; source hypotheses from controlled tests; recording-chain and alias tests | absolute SPL; structural vs airborne path |
| 2 | mic + contact pickup | adds relative vibration presence and location (contact survey); airborne control for the pickup; structural path *with* airborne control or isolation | vibration amplitude in physical units; path from coherence alone |
| 3 | mic + accelerometer | vibration spectra; physical units only with a valid calibration; velocity derivation | physical units without calibration |
| 4 | ≥ 2 channels on a shared clock (or a validly aligned pair) | coherence, transfer functions, delays within eligibility limits (spec 07) | causation from coherence |
| 5 | ≥ 1 channel with a valid calibration | absolute levels with stated uncertainty | accuracy beyond the calibration band or uncertainty |

The tier is computed per analysis (`AnalysisResult.tier`) and shown on the Devices and Analysis screens. Rules check concrete capabilities (eligibility flags, quantities), not the tier number.

## 5 Hardware qualification matrix

See spec 18 and `matrices/compatibility-matrix.csv`. All physical devices are currently **UNQUALIFIED**.

## 6 Sensor bridge protocol v1 (CON-016)

Needed only for digital MEMS accelerometers without an audio interface. **Firmware and board are BLOCKED** (DEC-004b) until a board is chosen. The host codec is implemented and tested.

```
frame  : 0xA5 0x5A | version u8 (=1) | type u8 | length u16 LE (<=4096) | payload | crc16 u16 LE
crc    : CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over version..payload
HELLO 1: rate f32 Hz | axes u8 (1-3) | full_scale_g f32 | model 16s | firmware 16s
DATA  2: seq u16 | sample_counter u32 | device_time_us u64 | axes u8 | n u16 (<=512) | n*axes int16 LE
ERROR 3: code u8 | message (<=64 ASCII)
```

Rules: seq +1 mod 65536 per DATA packet; `sample_counter` = previous + previous n (else lost samples become a zero-filled Gap); a decreasing counter means device reset (CLOCK_RESET, invalid); `device_time_us` increasing, with a per-packet period within ±5% of n/rate (else NONUNIFORM_TIMESTAMPS). Corrupt frames are resynchronised on the next sync word and counted. Samples are converted to FS (count/32768). A physical conversion requires a calibration profile (datasheet profile = VALIDATION_REQUIRED). Firmware acceptance tests (when unblocked): byte-exact round trip with `encode_*`; 1-hour stream with zero CRC errors over USB CDC; counter continuity across host suspend; timestamp period jitter < 1%; comparison against a reference accelerometer on a shaker at 3 frequencies (±0.5 dB).
