# 02 Research and competitive analysis

Sources are listed in `research/sources.md` (accessed 2026-10-12). Statements marked *(verified)* were checked against a primary source in this session. The others are engineering knowledge to be re-verified before any public marketing claim (RISK-012).

## 1 Comparable tools

| Tool | Model / licence | Strengths | Gaps relative to SonicClue's goal | Reuse decision |
|---|---|---|---|---|
| Room EQ Wizard (REW) | free, closed source | room/speaker measurement, RTA, spectrogram, sweeps with timing reference, calibration files | no guided cause investigation, no source/path/receiver reasoning, no evidence ledger | none (closed); calibration file format compatibility adopted (2-column freq/dB) |
| Audacity | GPL | editing, basic spectrum plot | not a measurement or diagnosis tool | none (GPL); WAV/FLAC interchange |
| Sonic Visualiser | GPL | annotation, Vamp plugin analyses | analysis viewer only | none (GPL) |
| Spek | GPL | spectrogram viewer | viewer only | none |
| ARTA | freeware/commercial, Windows | loudspeaker measurement, impedance, T/S parameters | speaker-design focus | none |
| Open Sound Meter | GPL-3.0 desktop *(verified)* | real-time dual-FFT transfer function, coherence, live sound tuning | system tuning, not cause finding | none (GPL); validates the dual-channel coherence concept |
| Friture | GPLv3+ Python/Qt *(verified)* | real-time scope, spectrum, spectrogram, octave analyzer | visualisation only | none (GPL). Its backend uses `sounddevice` + `rtmixer` (C ring buffer) *(verified)*; rtmixer is noted as a mitigation option for RISK-004 |
| Baudline | closed, now paid | spectrogram analysis | dated UI, no diagnosis | none |
| SonaVyx (browser) | free tier, claims "AI diagnostics" *(verified as a claim)* | browser RTA, transfer function, SPL | proprietary web tool; its diagnostic claims are not reviewed here | none; **SonicClue must not claim to be the only tool with diagnostics** |
| MATLAB / SciPy ecosystem | commercial / BSD | reference algorithms | general-purpose | SciPy reused (BSD) for Welch/CSD/filters/resampling |
| Condition-monitoring suites (SKF, Fluke etc.) | commercial | machinery vibration standards, route-based monitoring | expensive, hardware-bound | none; ISO 1683 references and the velocity/acceleration conventions adopted |

**Differentiation (claimable only after comparative review, RISK-012):** SonicClue's focus is the *investigation workflow*. It runs controlled on/off, isolation, damping, airborne-control, chain-noise and alias tests. It enforces comparability, keeps an evidence ledger with statement classes, uses versioned rules with explicit counterexamples, abstains when evidence is insufficient, and recommends discriminating next tests. Existing free tools provide measurement primitives. SonicClue reuses established primitives (SciPy) and adds the reasoning layer.

## 2 Acquisition and sensors (findings used in specs 05, 06)

* **PortAudio via `sounddevice`** (MIT) gives one API for WASAPI/MME/DirectSound/WDM-KS on Windows and ALSA/JACK on Linux. Its wheels bundle the PortAudio binary. WASAPI exclusive mode bypasses the Windows mixer and its "enhancements" (AGC, noise suppression). ASIO requires the Steinberg SDK, whose licence restricts redistribution, so it is deferred (DEC-003a).
* **Callback discipline:** Python callbacks hold the GIL and allocate. SonicClue mitigates this with a minimal callback (one copy into a bounded queue), large host buffers (`latency="high"`) and explicit gap accounting. `rtmixer`, as used by Friture, is the documented fallback if hardware qualification shows dropouts (RISK-004).
* **Sensors:** measurement mics with calibration files (USB measurement mics expose a sensitivity factor plus a response file); studio mics (uncalibrated, relative); piezo contact pickups (relative only; mount- and bending-dependent, and they also respond to airborne sound); IEPE accelerometers need constant-current conditioning before a line input; MEMS accelerometers need a microcontroller bridge (DEC-004b).
* **Capability tiers** (spec 06 section 4) follow directly from what each sensor class can legitimately measure.

## 3 DSP methods (findings used in spec 08)

Welch PSD (density scaling, one-sided), Hann default window, ENBW and coherent-gain bookkeeping, magnitude-squared coherence with the null-hypothesis threshold 1-alpha^(1/(n-1)), H1 transfer estimator, FFT cross-correlation delay with parabolic refinement, polyphase resampling, fractional-octave bands per IEC 61260-1 base-10, envelope spectrum via the Hilbert transform. All are standard and implemented with SciPy primitives. The invariants are verified against independent references (spec 08, tests).

Blind source separation and ML classification are **not** adopted: there is no validated dataset of labelled real-world investigations, and no calibration method for output probabilities (DEC-011). They are recorded as gated future work.

## 4 Cause investigation methods (spec 09, 10)

Controlled experiments with an A-B-A design (on/off/on), repeated captures for measured repeatability, comparability enforcement (position, mounting, gain, AGC), airborne-pickup controls for contact sensors, input-termination tests for recording-chain hum, sample-rate change tests for aliasing, tap tests for resonance, isolation/damping/mounting interventions, and location surveys. Each maps to one guided procedure and one or more rules.

## 5 Open research items

| ID | Question | Status | Exit criterion |
|---|---|---|---|
| RQ-1 | Do default thresholds (tone prominence 15 dB for evidence, 1 dB minimum effect, 6 dB airborne-control margin) hold on real cases? | VALIDATION_REQUIRED | at least 20 held-out real investigations with ground-truth interventions, evaluated per spec 17 section 6 |
| RQ-2 | Python callback dropouts on low-end Windows machines | VALIDATION_REQUIRED | 8-channel 1-hour capture on the reference machine with zero gaps |
| RQ-3 | Low-cost accelerometer bridge board selection | BLOCKED (hardware) | board chosen, firmware implementing the spec 06 section 6 protocol, bench test vs a reference accelerometer |
| RQ-4 | Measurement-mic calibration file conventions across vendors | VALIDATION_REQUIRED | three vendor files imported and verified against a calibrator |
