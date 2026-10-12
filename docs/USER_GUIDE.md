# SonicClue user guide

## 1 Install

**Windows x64:** unzip `SonicClue-<version>-windows-x64.zip` anywhere you can write (for example `Documents\Apps`). Run `SonicClue.exe`. No administrator rights or internet are needed. The build is not code-signed yet, so Windows SmartScreen may warn: choose *More info → Run anyway* only if the SHA-256 checksum matches `SHA256SUMS.txt`.
**Linux x64:** `tar xzf SonicClue-<version>-linux-x64.tar.gz`, then run `./SonicClue-<version>-linux-x64/SonicClue`. For audio input, your user must be able to open ALSA devices (usually the `audio` group or a desktop session with PipeWire/PulseAudio).
Microphone permission: on Windows 10/11 enable *Settings → Privacy → Microphone → Let desktop apps access your microphone*.

Your investigations are stored in `Documents/SonicClue` (change it with `--workspace` or the `SONICCLUE_WORKSPACE` environment variable). Upgrading means unzipping the new version next to the old one: both can coexist and use the same workspace. If an upgrade migrates a case, a backup `case.db.bak-…` is written first, so you can roll back by running the old version on that backup. Uninstall by deleting the program folder. Your workspace is kept unless you delete it.

## 2 Concepts

* **Case**: one investigation. Captures are never modified after recording.
* **Source / path / receiver / measurement system**: SonicClue keeps these separate. A fan can be the *source*, the desk the *path* (structure-borne) and the vocal microphone the *receiver*. A hum can also be produced by the *measurement system* (ground loop).
* **Comparable**: two recordings can only be compared if the sensor, its position, mounting and orientation, the interface gain and AGC (automatic gain control) are unchanged. SonicClue checks this and refuses invalid comparisons.
* **Support levels**: strongly supported, supported, undetermined, weakened, contradicted. These are rule outcomes, not probabilities.
* **Statement classes in reports**: MEASURED, CALCULATED, INFERRED, USER (what you entered) and UNRESOLVED.
* **Capability tier**: what your sensors can legitimately support (1 microphone only … 5 calibrated). Contact pickups give *relative* vibration only.

## 3 Step by step

1. **Case dashboard → New investigation.** Describe the problem, list candidate equipment you can safely switch off (computer, fan, air conditioner, amplifier…), and list your sensors.
2. **Devices & sensors.** Choose the interface and sample rate (48 kHz is a good default). For each input channel, set the sensor, a position id (P1, C1…), the mounting, and the interface gain you set on the hardware. Set **AGC = off** after disabling any automatic gain or "enhancements" (Windows: device properties → disable enhancements; or use WASAPI exclusive mode). Click **Apply**. The tier line shows what your setup supports.
3. **Guided tests → Baseline.** Follow the instructions. Captures that clip or are silent are rejected with a reason; fix the setting and record again.
4. **Hypotheses & evidence → Update diagnosis.** Read the conclusion banner and the reasons if it is inconclusive. Each hypothesis lists why, its supporting (+) and conflicting (-) evidence, and the missing tests.
5. Start the **recommended next test**. Typical sequence: *Equipment on/off* for each candidate → *Airborne control* (with a contact pickup) → *Isolation* or *Damping* → *Fix verification* after you apply a remedy.
6. **Before/after**: compare any captures yourself, with uncertainty and comparability checks.
7. **Report builder**: export HTML/PDF/JSON/CSV, optionally redacting names, locations, serials and notes.

## 4 Calibration (optional)

Without calibration you get relative levels (dBFS), which are enough for comparisons at fixed gain. To get SPL: record 5-10 s of a 94 dB / 1 kHz calibrator (Live screen, label "calibration"). Then in **Calibration**, choose the recording and channel and click Calibrate. Assign the profile to the channel on the Devices screen. A calibration becomes invalid if you change the interface gain (SonicClue then falls back to dBFS and says so). Measurement-mic response files can be imported. Choose whether the file lists the mic's *response* (it will be inverted) or a *correction*.

## 5 Test signals

The Live screen can play sine, sweep and noise signals. Nothing plays until you **Arm** (with confirmation) and press Play. Arming expires after 30 s, levels are capped (≤ −6 dBFS peak) and playback stops by itself. **Esc stops any test signal immediately.** Turn the amplifier down before playing.

## 6 Two devices at once

Recordings from different interfaces have different clocks. Record them at the same time, then in **Before/after → Align (multi-device)** select one capture in each list and estimate the clock mapping. SonicClue allows coherence only below the frequency the timing accuracy supports, and refuses ambiguous alignments.

## 7 Hardware qualification

**Settings & qualification → Run loopback qualification**: connect an output to an input of the same interface with a cable, turn monitors off, and run. A pass marks that device QUALIFIED for your OS. Every other device is UNQUALIFIED: it may work, but its accuracy is unverified.

## 8 Command line

`sonicclue-cli --help` lists every command. Examples:

```
sonicclue-cli case new --title "Desk hum" --equipment pc=PC:computer --sensor mic1=studio_mic
sonicclue-cli devices
sonicclue-cli procedure start --case <id> --procedure equipment_state --param target=pc
sonicclue-cli procedure step --case <id> --device 3 --ch 0:mic:mic1:P1:stand:30:off   (repeat for each step)
sonicclue-cli diagnose --case <id> -v
sonicclue-cli report --case <id> --format pdf --out report.pdf
```

## 9 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Audio backend unavailable" | PortAudio could not load (Linux: install `libportaudio2`); use the simulator to explore |
| Capture rejected: clipping | lower the interface gain; record again (remember to update the gain dB on the Devices screen) |
| "NOT COMPARABLE" | the sensor moved, mounting/gain/AGC changed, or several things changed at once; repeat under identical conditions |
| Everything "undetermined" | no controlled test yet; run the recommended on/off test |
| Dropouts reported | close other audio programs, use a larger buffer / WASAPI exclusive mode, avoid USB hubs |
| Case shown "locked" | open in another SonicClue window; close it there (stale locks from crashes clear automatically) |
| Case "damaged" | run *Verify integrity*; restore from an archive if needed |

## 10 Known limitations

See `RELEASE_NOTES.md`. In short: hardware unqualified; thresholds validated on synthetic data only; no ASIO; no simultaneous multi-device capture; analysis uses the first 10 minutes of long captures; Windows build unsigned.
