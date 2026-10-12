# 18 Hardware qualification

Code: `src/sonicclue/qualification/__init__.py` (`selftest`, `loopback_test`, `QualificationMatrix`). GUI: Settings & qualification. CLI: `selftest`, `qualify`. Matrix: workspace `qualification.json`; repository summary `matrices/compatibility-matrix.csv`.

## 1 Status

**No physical device has been qualified.** This session had no audio hardware (the build VM exposes no audio devices). All rows in the compatibility matrix are UNQUALIFIED or UNEXECUTED. Software that is *expected* to work on a device is still labelled UNQUALIFIED.

## 2 Procedures

| ID | Test | Equipment | Procedure | Pass criteria |
|---|---|---|---|---|
| HQ-01 | runtime self-test | none | `sonicclue-cli selftest` | all 5 checks pass |
| HQ-02 | loopback accuracy | interface + cable (out → in), monitors off | `sonicclue-cli qualify --output-device N --input-device M` | 0 dropouts; 1 kHz frequency error < 0.5 Hz; 10 dB level steps within ±0.5 dB; latency and noise floor recorded |
| HQ-03 | sustained capture | interface, 8 channels if available | 1-hour capture at 48 kHz on the reference machine while the GUI is open | 0 gaps; CPU recorded |
| HQ-04 | calibrator chain | measurement mic + 94 dB/1 kHz class 1 or 2 calibrator | record 10 s, calibrate; then record the calibrator at 114 dB | 114 dB reads 114.0 ± (calibrator tolerance + 0.2) dB |
| HQ-05 | two-device alignment | two interfaces, a common broadband source | simultaneous 60 s captures, `align` | σ_t reported; coherence at the common source frequencies; mapping stable across repeats (offset spread < 3σ) |
| HQ-06 | contact pickup airborne control | piezo pickup, loudspeaker, a panel | airborne_control procedure with speaker only vs panel excitation | decoupled pickup within 3 dB of mounted for airborne-only excitation; ≥ 6 dB difference for structural excitation |
| HQ-07 | accelerometer chain | IEPE accel + conditioner, or MEMS bridge (when unblocked) | handheld shaker calibrator (e.g. 10 m/s² at 159.2 Hz) | ±0.5 dB vs the calibrator |
| HQ-08 | stimulus safety | interface + speaker at low volume | arm/play/stop, unplug during playback | output stops; controller DISARMED; never resumes |
| HQ-09 | clean-machine install | fresh Windows 11 VM, no Python | unzip, run GUI, demo, report | runs offline; no admin prompt |

## 3 Initial device targets (DEC-004, VALIDATION_REQUIRED)

Class-compliant 2-channel USB interfaces (e.g. Behringer UMC202HD, Focusrite Scarlett 2i2), USB measurement microphones (e.g. miniDSP UMIK-1), XLR measurement microphones (e.g. Behringer ECM8000), piezo contact pickups, IEPE accelerometer with a USB conditioner, and the built-in laptop microphone (tier 1, expected AGC issues). Models are examples for qualification planning only; none are endorsed or qualified.
