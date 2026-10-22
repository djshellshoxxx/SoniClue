# 05 Acquisition

Code: `src/sonicclue/acquisition/` (backends, session, importer). Tests: `tests/test_acquisition.py`, `tests/test_storage.py` (recovery), `tests/test_gui.py` (live screen).

## 1 Backends (DEC-003, ADR-0003)

| Backend | Platforms | Host APIs | Notes | Status |
|---|---|---|---|---|
| `PortAudioBackend` (sounddevice) | Windows x64, Linux x64 | WASAPI (shared/exclusive), MME, DirectSound, WDM-KS; ALSA, JACK; PulseAudio/PipeWire through their ALSA plugins | float32 streams, `latency="high"` for robustness; exclusive mode only on WASAPI | IMPLEMENTED; physical devices UNQUALIFIED |
| `SimulatedBackend` | all | n/a | deterministic SimWorld (spec 17 section 3); speed factor 1-N; failure injection (`fail_after_frames`) | TESTED |
| ASIO | Windows | ASIO | Steinberg SDK licence restricts redistribution | BLOCKED (DEC-003a) |

Device discovery returns `DeviceDescriptor(index, name, host_api, max_input_channels, max_output_channels, default_samplerate)`. `check_input()` validates a (device, rate, channels) combination before a session starts (`SC_DEVICE_FORMAT`). Sample-rate negotiation: the user picks a rate. It is validated by PortAudio and never silently changed. A mismatch is an error, not a resample.

Scientific acquisition is independent of visualisation: live meters and the spectrum read a copy (`snapshot()`), and the stored data is exactly what the writer received. No gain, filtering, limiting, dithering or compression is applied (REQ-ACQ-010).

## 2 Capture session state machine (SM-001)

| State | Event | Guard | Action | Next |
|---|---|---|---|---|
| IDLE | start() | device format valid | open stream, start writer, start stream | RUNNING |
| IDLE | start() | invalid format | raise SC_DEVICE_FORMAT | IDLE |
| IDLE | stop()/cancel() | | nothing captured | CANCELLED |
| RUNNING | frames reach duration | | stop stream, drain, close sink | COMPLETED |
| RUNNING | stop() | | as above | STOPPING → COMPLETED |
| RUNNING | cancel() | | stop, skip drain; the owner deletes files | STOPPING → CANCELLED |
| RUNNING | device error / finished callback with error | | flag DEVICE_DISCONNECTED; keep data | STOPPING → FAILED |
| RUNNING | sink write error (disk full) | | record error | STOPPING → FAILED |
| any running | start() | | raise SC_STATE | unchanged |
| STOPPING/terminal | stop()/cancel() | | no-op (idempotent) | unchanged |
| terminal | start() | | raise SC_STATE (create a new session) | unchanged |

Timeouts: `wait(timeout)` raises SC_STATE if the session does not finish. The CLI and app use `duration*2 + 30 s`. The GUI stops a capture that overruns `3*duration + 30 s`.

## 3 Buffering, backpressure, timing integrity

* Callback: one copy of the block into a bounded `queue.Queue` sized to `QUEUE_SECONDS = 4 s`. If full, it appends `(frame_index, frames)` to a drop list. It never blocks.
* Writer thread: on a frame-index jump it zero-fills the missing frames (clamped to the requested duration) and records `Gap(queue_overflow)`. The stored timeline therefore equals the converter's sample count, and analysis excludes gaps (INV-010).
* PortAudio `input_overflow` status: frames were lost inside the driver and the count is unknown. It is recorded as a zero-length `Gap(input_overflow)` with a DROPOUT flag. Multi-capture alignment across such a point is not trusted (spec 07).
* Frame indices are counted from the stream start by the backend (sample counter, not host clock). Wall-clock time is recorded once (`created_utc`) for reference only.

## 4 Persistence, cancellation, recovery

* Sink = `storage.writer.CaptureWriter`: 10 s float32 WAV chunks, each made read-only after flush, and a SHA-256 per chunk. `journal.json` is rewritten atomically after every chunk and holds the full manifest header.
* Stop: the manifest is saved with status `complete` (or `partial` after a device failure).
* Cancel: the capture directory is deleted by `CaptureHandle.finalize` (an explicit user decision to discard).
* Crash: on the next case open, `CaseStore.recover()` rebuilds a manifest from the journal using the contiguous verified chunk prefix, flags `RECOVERED_CAPTURE` + `PARTIAL_CAPTURE`, and deletes `.part` files. At most the last unfinished 10 s chunk is lost.

## 5 Quality checks (automatic)

At capture time: clipping per channel (|x| ≥ 0.999 FS), gaps and device failure. At analysis time (`dsp.levels.screen_channel`): non-finite samples, clipping with a ±10 ms exclusion guard, near-clipping (peak ≥ -1 dBFS), silence (AC RMS < -140 dBFS), low signal (< -80 dBFS), DC offset (> 0.01 FS), short capture, insufficient averages, AGC on/unknown, calibration state, alias risk (tone > 0.45 fs). All are `QualityFlag`s with severity (info/warning/invalid). Invalid flags exclude data or analyses (spec 08 section 8).

## 6 Imports

* Audio files: WAV, FLAC, AIFF, OGG, W64, RF64, CAF via libsndfile (≤ 8 GiB, 1-64 channels). Streamed in 2^18-frame blocks to float32 chunks. The original file is copied byte-for-byte as `original.<ext>`, made read-only, and its SHA-256 recorded in the context notes. Lossy sources get an ALIAS_RISK warning (codec artifacts).
* Sensor-bridge dumps: decoded per spec 06 section 6. Lost packets become zero-filled gaps; counter resets and timestamp irregularities are flagged.

## 7 Multi-device capture

`SonicClueApp.start_multi_capture` and the CLI `capture-multi` coordinate simultaneous capture on two or more devices (TASK-031, REQ-ACQ-014). Each device retains its own capture and clock domain. At finalization SonicClue estimates each mapping against the first device using the configured shared-reference channels; it does not assume the clocks are synchronized. Correlation, signal-quality, and ambiguity gates can leave a mapping unavailable. GUI workflow remains offline alignment in Before/after → Align (multi-device).
