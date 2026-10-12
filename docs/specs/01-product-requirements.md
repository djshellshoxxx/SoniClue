# 01 Product requirements

Release targets: **R1** = first usable release (0.1.x, microphone-only value plus everything implemented here); **R2** = next release (hardware-qualified, installer, signing); **F** = future (gated by research/validation).
Every requirement has a verification method in `matrices/requirement-coverage.csv`.

## 1 Purpose and principles

SonicClue helps users find, understand and reduce unwanted acoustic noise and mechanical vibration. It does this through guided, evidence-driven investigation: measuring, comparing controlled conditions, and reasoning explicitly about **excitation source**, **transmission path**, **receiver** and **measurement system**. It must allow inconclusive results and must never present correlation as proof of causation.

| ID | Requirement | Release |
|---|---|---|
| REQ-PRN-001 | The system SHALL distinguish source, path, receiver and measurement-system explanations in its hypotheses. | R1 |
| REQ-PRN-002 | The system SHALL be able to abstain ("inconclusive") and SHALL state why. | R1 |
| REQ-PRN-003 | The system SHALL NOT treat coherence, frequency coincidence or level correlation as proof of cause. | R1 |
| REQ-PRN-004 | The system SHALL operate fully offline with no account, cloud service or GPU. | R1 |
| REQ-PRN-005 | The system SHALL keep measurement uncertainty separate from diagnostic evidence strength. | R1 |
| REQ-PRN-006 | Simulated data SHALL be labelled SIMULATED wherever it is shown or exported. | R1 |

## 2 Core workflow (master prompt section 5)

| ID | Requirement | Release |
|---|---|---|
| REQ-WF-001 | Users SHALL create a diagnostic case with title, problem description, character tags, receiver, optional band of interest, candidate equipment and sensors. | R1 |
| REQ-WF-002 | Users SHALL select input devices and describe each channel (sensor, position, location, mounting, gain, AGC state, calibration). | R1 |
| REQ-WF-003 | Users SHALL record baseline measurements (guided procedure with acceptance gates). | R1 |
| REQ-WF-004 | Every capture SHALL be screened automatically for clipping, silence, low signal, DC offset, non-finite values, dropouts and short duration. | R1 |
| REQ-WF-005 | Captures SHALL be analysed for levels, spectra, tones, harmonic families, transients, band levels and cross-channel relations. | R1 |
| REQ-WF-006 | The system SHALL generate candidate hypotheses from case equipment and evidence. | R1 |
| REQ-WF-007 | The system SHALL recommend and explain next tests, ranked by how well they separate open hypotheses. | R1 |
| REQ-WF-008 | Users SHALL perform guided controlled measurements with pause, resume, cancel and crash-safe persistence. | R1 |
| REQ-WF-009 | The system SHALL compare capture groups with comparability checks and uncertainty. | R1 |
| REQ-WF-010 | Hypothesis rankings SHALL update when evidence changes, and history SHALL be retained. | R1 |
| REQ-WF-011 | For every hypothesis the system SHALL show supporting evidence, conflicting evidence, missing tests and rule provenance. | R1 |
| REQ-WF-012 | The system SHALL verify proposed improvements with repeated before/after measurements (fix verification). | R1 |
| REQ-WF-013 | The system SHALL generate evidence-based reports (HTML, PDF, JSON, CSV). | R1 |
| REQ-WF-014 | Measurements and project history SHALL be preserved immutably with an audit log. | R1 |

## 3 Acquisition

| ID | Requirement | Release |
|---|---|---|
| REQ-ACQ-001 | Device discovery SHALL list input/output devices with host API, channel counts and default rate. | R1 |
| REQ-ACQ-002 | Capture SHALL support 1-64 channels from one device at 8-192 kHz in float32. | R1 |
| REQ-ACQ-003 | WASAPI exclusive mode SHOULD be selectable on Windows. | R1 |
| REQ-ACQ-004 | The device callback SHALL do bounded work only; samples SHALL pass through a bounded queue to a writer thread. | R1 |
| REQ-ACQ-005 | Queue overflow SHALL become an explicit zero-filled, flagged gap that preserves the sample timeline. | R1 |
| REQ-ACQ-006 | Driver input overflow SHALL be recorded. | R1 |
| REQ-ACQ-007 | Device disconnection SHALL end the capture as *partial*, keeping data written so far. | R1 |
| REQ-ACQ-008 | Cancel SHALL discard; stop SHALL keep; both SHALL be idempotent. | R1 |
| REQ-ACQ-009 | Interrupted captures SHALL be recovered from a journal on next open. | R1 |
| REQ-ACQ-010 | Raw samples SHALL be stored unmodified (no gain, filtering, limiting, compression or dither). | R1 |
| REQ-ACQ-011 | Live monitoring SHALL show per-channel peak meters, clip indicators and a live spectrum without blocking capture. | R1 |
| REQ-ACQ-012 | Audio files (WAV/FLAC/AIFF/...) SHALL be importable, with the original preserved byte-for-byte. | R1 |
| REQ-ACQ-013 | ASIO SHOULD be supported when licensing allows. | F (BLOCKED: DEC-003a) |
| REQ-ACQ-014 | Simultaneous multi-device capture SHOULD be supported. | F |
| REQ-ACQ-015 | A built-in simulator SHALL exist for demonstration, training and end-to-end tests. | R1 |

## 4 Sensors, calibration, synchronization

| ID | Requirement | Release |
|---|---|---|
| REQ-SEN-001 | Sensors SHALL be described by kind, model, serial, physical quantity, axis and usable band. | R1 |
| REQ-SEN-002 | Contact pickups and piezo discs SHALL be relative-only and SHALL NOT be calibrated to physical units. | R1 |
| REQ-SEN-003 | Capability tiers 1-5 SHALL be computed and shown, and analyses SHALL respect them. | R1 |
| REQ-CAL-001 | Calibration from a reference calibrator recording SHALL be supported (SPL or acceleration). | R1 |
| REQ-CAL-002 | Calibration files (frequency response) SHALL import with an explicit correction direction. | R1 |
| REQ-CAL-003 | Calibration validity SHALL be checked (sensor, gain, expiry, frequency band) and invalid calibration SHALL fall back to relative levels with a flag. | R1 |
| REQ-CAL-004 | Calibration uncertainty SHALL be recorded (k=2) and reported. | R1 |
| REQ-SYN-001 | Channels of one capture SHALL be treated as shared-clock. | R1 |
| REQ-SYN-002 | Independently clocked captures SHALL be aligned only through an estimated clock mapping with stated uncertainty. | R1 |
| REQ-SYN-003 | Synchronized analysis SHALL be limited to the band the timing uncertainty supports, and disabled when alignment is ambiguous or a clock reset is detected. | R1 |
| REQ-SEN-004 | A sensor-bridge protocol and host decoder SHALL be defined. Bridge firmware/hardware is gated (DEC-004b). | R1 (protocol) / F (hardware) |

## 5 Signal processing

| ID | Requirement | Release |
|---|---|---|
| REQ-DSP-001 | PSD SHALL be one-sided density with Parseval consistency and an explicit DC/Nyquist convention. | R1 |
| REQ-DSP-002 | Segments touching invalid data SHALL be excluded rather than zero-filled. | R1 |
| REQ-DSP-003 | Tone detection SHALL report frequency, level, prominence, and Q (or resolution-limited). | R1 |
| REQ-DSP-004 | Harmonic families and mains relation (50/60 Hz) SHALL be identified. | R1 |
| REQ-DSP-005 | Transient events and periodicity SHALL be detected. | R1 |
| REQ-DSP-006 | Coherence, transfer function and delay SHALL be computed with explicit orientation, invalid-bin masks and eligibility. | R1 |
| REQ-DSP-007 | Fractional-octave band levels SHALL follow base-10 IEC 61260-1 band definitions. | R1 |
| REQ-DSP-008 | Spectrograms and envelope (modulation) spectra SHALL be available. | R1 |
| REQ-DSP-009 | All numerical modules SHALL run headless and be tested against independent references. | R1 |
| REQ-DSP-010 | Acceleration to velocity conversion SHALL be provided with a low-frequency limit. | R1 (library) |
| REQ-DSP-011 | Blind source separation / ML classification MAY be added only with validated datasets. | F (BLOCKED: DEC-011) |

## 6 Comparison and diagnosis

| ID | Requirement | Release |
|---|---|---|
| REQ-CMP-001 | Comparisons SHALL check comparability (sensor, position, mounting, orientation, gain, AGC, processing, quality, simulated/physical). | R1 |
| REQ-CMP-002 | Deltas SHALL carry 95% uncertainty (measured repeatability or estimated) and a minimum practical effect. | R1 |
| REQ-CMP-003 | Band and tone deltas SHALL be reported. | R1 |
| REQ-DX-001 | Rules SHALL be deterministic, versioned and recorded per hypothesis. | R1 |
| REQ-DX-002 | Support SHALL be ordinal. Percentages and probabilities SHALL NOT be shown without a validated model. | R1 |
| REQ-DX-003 | Each rule SHALL define evidence, assumptions, confounders, counterexamples, contradiction, abstention and next test. | R1 |
| REQ-DX-004 | The ten adversarial cases ADV-001..010 SHALL have passing tests. | R1 |
| REQ-DX-005 | Next-test recommendations SHALL explain which hypotheses they separate and SHALL respect hardware prerequisites. | R1 |
| REQ-DX-006 | Report and UI cause text SHALL come only from rule-backed templates. | R1 |

## 7 Procedures and stimulus

| ID | Requirement | Release |
|---|---|---|
| REQ-PROC-001 | The 13 procedures required by the master prompt, plus airborne control and alias check, SHALL exist as declarative definitions. | R1 |
| REQ-PROC-002 | Each procedure SHALL define preconditions, sensors, instructions, settling, duration, repeats, gates, confounds, safety, success and evidence output. | R1 |
| REQ-PROC-003 | Failed gates SHALL reject the capture (kept for traceability) and repeat the step. | R1 |
| REQ-STIM-001 | Output SHALL require explicit arming plus confirmation, and arming SHALL be one-shot and expiring. | R1 |
| REQ-STIM-002 | Output SHALL enforce level limits (<= -6 dBFS peak), duration limits, fades, immediate stop and a watchdog. | R1 |
| REQ-STIM-003 | Output SHALL NOT start or resume automatically (including after a crash or reconnect). | R1 |
| REQ-STIM-004 | A feedback guard SHALL require explicit confirmation when the output and input devices are the same. | R1 |
| REQ-STIM-005 | Audition SHALL play copies of evidence under the same interlocks. | R1 |

## 8 UI, storage, reporting, security, performance, release

| ID | Requirement | Release |
|---|---|---|
| REQ-UI-001 | The GUI SHALL provide the 12 screens of the master prompt (section 13). | R1 |
| REQ-UI-002 | Guided and expert modes SHALL share one engine. | R1 |
| REQ-UI-003 | Long operations SHALL run off the GUI thread. | R1 |
| REQ-UI-004 | Keyboard navigation and accessible names SHALL be provided, and every plot SHALL have a table alternative. | R1 |
| REQ-UI-005 | A CLI SHALL expose every workflow step. | R1 |
| REQ-UI-006 | The UI SHALL follow the Circuit Drift Labs visual language (dark blue/charcoal, restrained accents). | R1 |
| REQ-STO-001 | Cases SHALL be stored in a portable directory with SQLite documents and immutable chunked captures with checksums. | R1 |
| REQ-STO-002 | Writes SHALL be atomic or journaled. Cases SHALL be locked against concurrent writers. | R1 |
| REQ-STO-003 | Derived results SHALL reference source captures and algorithm versions. | R1 |
| REQ-STO-004 | Schema migrations SHALL back up the database first. Newer stores SHALL be rejected. | R1 |
| REQ-STO-005 | Portable archives SHALL import safely (size, traversal, symlink, ratio, checksum, schema). | R1 |
| REQ-STO-006 | Integrity verification SHALL detect tampering, missing files and invalid documents. | R1 |
| REQ-REP-001 | Reports SHALL distinguish measured, calculated, inferred, user-asserted and unresolved statements. | R1 |
| REQ-REP-002 | Reports SHALL include methodology, sensors/calibration, limitations, competing hypotheses, interventions, comparisons and reproduction instructions. | R1 |
| REQ-REP-003 | Export redaction (names, locations, serials, notes) and report versioning SHALL be supported. | R1 |
| REQ-SEC-001 | No network access SHALL be required or performed by default. Logs SHALL contain no audio content. | R1 |
| REQ-SEC-002 | A dependency/licence inventory and third-party notices SHALL ship with releases. | R1 |
| REQ-SEC-003 | Release artifacts SHALL have SHA-256 checksums. | R1 |
| REQ-PERF-001 | Analysis of 60 s of 2-channel 48 kHz audio SHALL complete within 10 s on reference hardware. | R1 (VALIDATION_REQUIRED: reference machine) |
| REQ-PERF-002 | Capture SHALL sustain 8 channels at 48 kHz without dropouts on reference hardware. | R1 (VALIDATION_REQUIRED) |
| REQ-PERF-003 | Idle GUI memory SHALL stay below 400 MB. | R1 |
| REQ-PKG-001 | A dependency-bundled Windows x64 standalone package SHALL be produced (portable ZIP, per-user, offline). | R1 |
| REQ-PKG-002 | A Linux x64 standalone package SHALL be produced. | R1 |
| REQ-PKG-003 | A signed Windows installer SHOULD be produced. | R2 (BLOCKED: certificate, DEC-009) |
| REQ-QA-001 | Hardware qualification (loopback) SHALL be available, and untested devices SHALL be labelled UNQUALIFIED. | R1 |
| REQ-QA-002 | A runtime numerical self-test SHALL be available. | R1 |
