# SonicClue 0.1.0 release notes

**Release type:** software-complete, **hardware-unqualified** (DEC-010). Date 2026-10-12.

## What is included

* Guided cause investigation: 15 declarative procedures (baseline, equipment on/off, source and receiver location surveys, contact and vibration surveys, speaker buzz, resonance tap test, isolation, damping, mounting change, electrical-hum/recording-chain test, airborne control, alias check, fix verification) with acceptance gates, pause/resume/cancel and crash-safe state.
* Measurement: PortAudio capture (WASAPI shared/exclusive, MME, DirectSound, WDM-KS; ALSA/JACK/PipeWire via ALSA), 1-64 channels, bounded-queue capture with explicit gap accounting, lossless float32 chunked storage with checksums, crash recovery, file import with byte-exact originals, sensor-bridge dump import (protocol v1).
* Analysis: Welch PSD with gap/clip exclusion, tones with Q, harmonic families with mains detection, transients and periodicity, spectrograms, envelope spectra, fractional-octave bands (IEC 61260-1 base 10), coherence/transfer function/delay with eligibility rules, calibration (calibrator or response file) with validity checks and uncertainty, capability tiers 1-5.
* Comparisons with comparability enforcement (position, mounting, gain, AGC, processing, quality) and 95% uncertainty (measured or estimated repeatability) with a 1 dB minimum effect.
* Two-device clock alignment (offset + drift + timing uncertainty; ambiguous and reset cases rejected).
* Explainable diagnosis: deterministic versioned rules, ordinal support levels (no percentages), source/path/receiver/measurement-system separation, abstention, next-test recommendations explaining which hypotheses they separate.
* Interlocked test-signal output (explicit arming, confirmation, level and duration limits, fades, watchdog, one-shot, Esc stop) and audition.
* Reports in HTML, PDF, JSON and CSV, with statement classes (measured/calculated/inferred/user/unresolved), redaction and versioning. Portable case archives with safe import.
* Desktop GUI (12 screens, guided and expert modes, Circuit Drift Labs theme) and a complete CLI. Built-in simulator and simulated demo (always labelled SIMULATED).

## Validation actually performed

* 181 automated tests pass on Linux (build VM, Python 3.11): numerical invariants against independent references, adversarial diagnostic cases ADV-001..010, storage/recovery/archive attacks, acquisition failure injection, calibration and synchronization, stimulus interlocks, reports, CLI end to end, and offscreen GUI flows.
* Contract checks: 20 generated schemas current; 47/47 examples behave as declared (jsonschema and pydantic); 12/12 numerical reference vectors within tolerance.
* Linux x64 standalone bundle built (`SonicClue-0.1.0-linux-x64.tar.gz`, 168 MB, SHA-256 `3a502fcac7a46186de3710038485525c154759322b3a7042ba925f56aef6faf3`, build id `39134931f9a3-20261012T053834Z`, built from the working tree before commit) and smoke-tested in a clean environment: version, self-test, simulated demo with report, device listing, GUI construction of all screens.
* Windows x64 bundle: built and smoke-tested by the CI workflow (`.github/workflows/ci.yml`). See the repository Actions run for status; it was not built on a local Windows machine.
* Performance measured on the build VM only (spec 16). Reference-hardware measurements are pending.

## Hardware qualification status

**No audio interface, microphone, contact pickup or accelerometer has been qualified.** The build environment had no audio devices. All physical devices are UNQUALIFIED. Use **Settings → Run loopback qualification** to qualify your own interface.

## Known limitations

* Diagnostic thresholds were validated on synthetic and simulated scenarios only. Real-world accuracy has not been measured.
* No ASIO (licence). No simultaneous multi-device capture (use offline alignment). No MEMS bridge firmware (protocol only).
* Analysis covers the first 600 s of a capture by default (setting `max_analysis_seconds`); streamed full-length analysis is planned.
* Windows builds are unsigned (SmartScreen warning). Licence not yet decided (see LICENSE-NOTICE.md).
* Python audio callbacks may drop blocks on very slow machines. Any drop is recorded as a gap and never hidden.
* Screen-reader accessibility has not been tested.
