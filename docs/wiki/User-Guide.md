# User Guide

## Install and launch

Use the Windows x64 or Linux x64 standalone bundle from the repository’s Releases page. The bundles are portable and are intended to run without administrator rights or an internet connection. Read the release notes and verify the downloaded file against the published SHA-256 checksum.

For development installs, see the [Developer Guide](Developer-Guide.md). The full, detailed product instructions are in [docs/USER_GUIDE.md](../USER_GUIDE.md).

Cases are stored in the SonicClue workspace (by default, Documents/SonicClue). The workspace can be selected with the `--workspace` option or `SONICCLUE_WORKSPACE` environment variable. Removing the program directory does not remove the workspace.

## Recommended investigation flow

1. **Create a case.** Describe the noise or vibration, the receiver/location where it is noticed, and candidate equipment that could be tested.
2. **Describe devices and sensors.** For every channel, record the sensor, position, mounting, orientation, gain, AGC state, and calibration profile if available. Disable automatic gain and audio enhancements where possible.
3. **Record a baseline.** Follow the guided procedure. SonicClue screens captures for problems such as clipping, silence, invalid samples, and dropouts; rejected captures remain traceable with a rejection reason.
4. **Run controlled tests.** Follow recommended procedures, changing one relevant condition at a time. Examples include switching candidate equipment off and on, moving the receiver, using an airborne control for a contact pickup, or changing isolation/damping.
5. **Review hypotheses and evidence.** Inspect supporting and conflicting evidence, missing tests, rule explanations, and the recommended next test. An inconclusive result means more discriminating evidence is needed.
6. **Compare and verify.** Keep setup conditions consistent. Repeat measurements when possible, then use fix verification to compare before and after an intervention.
7. **Export a report.** Choose HTML, PDF, JSON, or CSV. Redact names, locations, serial numbers, and notes when appropriate.

## Important concepts

### Source, path, receiver, measurement system

These are separate explanations. For example, a fan may be the excitation source, a desk may carry structure-borne vibration, and a microphone may be the receiver. A ground loop or gain change can create an apparent signal in the measurement system itself.

### Comparability

SonicClue checks whether two captures can be compared. Sensor type, location, mounting, orientation, interface gain, AGC, processing, and capture quality matter. If conditions differ, repeat the test with a consistent setup rather than interpreting the numerical difference as a physical change.

### Support levels and uncertainty

Support levels are deterministic rule outcomes, not percentages or probabilities. Measurement uncertainty describes the precision of a measured difference; it is separate from the strength of a causal explanation.

### Capability tiers

The app reports what the configured sensors can support. A general microphone can support relative acoustic analysis. Contact pickups usually provide relative vibration only and can also respond to airborne sound. Calibrated sensors can support physical units within their valid band and setup.

## Calibration and alignment

Without valid calibration, levels are relative (such as dBFS). A suitable reference calibrator or response file can support calibrated units when the profile matches the sensor and gain. If calibration is invalid, SonicClue flags the issue and falls back to relative levels.

Independent devices have independent clocks. Recordings from them must be aligned with an estimated clock mapping before synchronized analysis; ambiguous mappings or detected clock resets are rejected, and timing uncertainty limits the eligible frequency range.

## Test-signal output

Signal output and audition are interlocked. The user must explicitly arm and confirm playback. The documented safeguards include expiring one-shot arming, level and duration limits, fades, a watchdog, and immediate stop. Output does not automatically start or resume after reconnect or a crash. Turn amplifiers down before testing and use the on-screen controls.

## CLI examples

```sh
sonicclue-cli --help
sonicclue-cli devices
sonicclue-cli demo
```

A simulated demo is useful for learning the workflow; its measurements and conclusions are simulated, not evidence about a physical room or device. The complete CLI workflow examples are in [docs/USER_GUIDE.md](../USER_GUIDE.md).