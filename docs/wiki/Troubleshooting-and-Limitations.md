# Troubleshooting and Limitations

For the full symptom table, see [docs/USER_GUIDE.md](../USER_GUIDE.md). Check the repository’s latest [release notes](../RELEASE_NOTES.md), [compatibility matrix](../specs/matrices/compatibility-matrix.csv), and Actions runs for changes since the notes were written.

## Common problems

| Symptom | What to check |
|---|---|
| Audio backend unavailable | Confirm the OS audio backend is available; on Linux, install PortAudio runtime libraries. Use the simulator to explore without an input device. |
| Capture rejected for clipping | Lower the interface gain, update the recorded gain setting, and repeat the capture. |
| Comparison says not comparable | Check whether sensor, position, mounting, orientation, gain, AGC, processing, or capture quality changed. Repeat with controlled conditions. |
| Hypotheses remain undetermined | Run a recommended controlled test; frequency coincidence or coherence alone cannot prove a cause. |
| Dropouts are reported | Close competing audio applications, try a larger buffer or Windows WASAPI exclusive mode, and avoid unstable USB hubs. Keep reported gaps visible in analysis. |
| Case appears locked | Check whether the case is open in another SonicClue window. Stale locks from crashes are handled during recovery. |
| Case is marked damaged | Run integrity verification and restore from a known-good archive if needed. |

## Interpretation boundaries

- A general microphone usually yields relative acoustic levels unless valid calibration is applied.
- Contact pickups are relative-only, mount-dependent, and can respond to airborne sound.
- Calibration is valid only for the matching sensor/setup and supported band. A gain change can invalidate it.
- Independent devices do not share a clock. Alignment has uncertainty and may be rejected when ambiguous or reset.
- Diagnostic thresholds are documented as tested on synthetic/simulated cases; real-world accuracy requires external validation.
- Hardware qualification is per device and OS. The repository README states that physical devices have not yet been qualified; verify the current compatibility matrix for updates.
- Windows standalone builds are documented as unsigned in the 0.1.0 release notes. Check current release assets and signing status.

## Features that remain gated

The project documentation records ASIO support, simultaneous multi-device recording, bridge hardware/firmware, signed installation, and machine-learning diagnosis as blocked or future work. Do not treat a protocol, specification, or planned item as delivered hardware/software functionality.

## Source of truth

This wiki is a navigational guide. For implementation status, use the code on the default branch, the current backlog and matrices under `docs/specs/matrices/`, and the latest CI/release information. Where this page conflicts with those sources, update the wiki or follow the more current source.