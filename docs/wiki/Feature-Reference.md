# Feature Reference

This page summarizes features documented for SonicClue 0.1.0. See [Release Notes](../RELEASE_NOTES.md) and the [specification package](../specs/README.md) for detailed contracts, requirements, and current validation status.

## Guided investigation

The app provides a case dashboard, device and sensor setup, guided procedures, hypothesis/evidence review, comparisons, and report building. Procedures have preconditions and acceptance gates, can be paused or resumed, and persist progress so an interrupted case can be recovered.

The release notes list 15 procedures, including:

- Baseline recording
- Equipment on/off
- Source and receiver location surveys
- Contact and vibration surveys
- Speaker buzz
- Resonance tap test
- Isolation, damping, and mounting changes
- Electrical hum / recording-chain test
- Airborne control
- Alias check
- Fix verification

Procedure definitions are declarative JSON under `src/sonicclue/procedures/definitions/`.

## Recording and import

- PortAudio capture through `sounddevice`; documented Windows backends include WASAPI shared/exclusive, MME, DirectSound, and WDM-KS. Linux uses ALSA/JACK/PipeWire through the available PortAudio setup.
- One-device capture supports 1–64 channels in float32, with bounded-queue capture and explicit accounting for gaps or driver overflows.
- Audio-file import preserves the original file byte-for-byte.
- A sensor-bridge dump importer is available for protocol version 1; bridge hardware/firmware qualification remains gated.
- Interrupted recording recovery uses a journal. Raw captured samples are not filtered or level-adjusted during acquisition.

## Analysis

Documented analysis includes:

- Welch power spectral density, with invalid/gap and clipped regions excluded from eligible segments
- Tone detection, prominence, and Q / resolution-limited reporting
- Harmonic families and 50/60 Hz mains relationships
- Transients, periodicity, spectrograms, and envelope spectra
- Fractional-octave bands based on IEC 61260-1 base-10 definitions
- Cross-channel coherence, transfer function, and delay with explicit eligibility checks
- Calibration, sensor-response correction, and capability tiers

Analysis results retain links to their source captures and algorithm versions.

## Comparisons and diagnosis

Comparisons enforce setup and data-quality checks and report deltas with 95% uncertainty, using repeatability measurements or an estimate. The documented minimum practical effect is 1 dB.

Diagnosis uses deterministic, versioned rules. It separates source, path, receiver, and measurement-system hypotheses; shows rule-backed supporting and conflicting evidence; records missing tests; and recommends tests that distinguish open hypotheses. It may abstain and report that the result is undetermined.

## Cases, integrity, and reports

Cases use SQLite documents plus chunked capture files with checksums and recovery support. Case archives are validated on import. Integrity verification can detect tampering, missing files, and invalid documents.

Reports are available in HTML, PDF, JSON, and CSV. They include methodology and relevant setup details and classify statements as MEASURED, CALCULATED, INFERRED, USER, or UNRESOLVED. Export supports redaction and report versioning.

## GUI and command line

The desktop interface provides guided and expert modes over a shared application engine. The CLI exposes workflow operations for scripting and headless use. The built-in simulator supports demos and tests; all simulated data must remain labelled SIMULATED.

## Deliberately out of scope or gated

The repository records ASIO support, simultaneous multi-device capture, bridge hardware, signed installation, machine-learning classification, and real-world diagnostic threshold validation as blocked, future, or validation-dependent work. Confirm status in the specs and release notes before planning around these features.