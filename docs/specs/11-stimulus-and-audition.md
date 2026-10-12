# 11 Stimulus generation and audition

Code: `src/sonicclue/stimulus/__init__.py`. GUI: Live measurement → Test signal; Analysis → Listen. CLI: `stimulus`. Tests: `tests/test_workflows.py` (stimulus section), `tests/test_gui.py::test_output_escape_stops`.

## 1 Usefulness assessment

Built-in stimulus is useful for speaker buzz tests (slow sweep), resonance excitation, loopback qualification and acoustic transfer checks. It is risky (hearing, tweeters, feedback), so every path is interlocked. The decision is to include it with interlocks (SELECTED_DEFAULT).

Signals: sine, logarithmic sweep, white, pink, band-limited noise, impulse train. All are peak-normalised to the requested peak dBFS, with 50 ms raised-cosine fades.

## 2 Output state machine (SM-004)

| State | Event | Guard | Action | Next |
|---|---|---|---|---|
| DISARMED | arm(device, rate, limit, max_duration, confirmed) | confirmed = True; not (output device == active input device and not allow_same_device) | limit = min(limit, -6 dBFS); max_duration ≤ 120 s; start the arm timer | ARMED |
| DISARMED | play()/audition() | | SC_OUTPUT_SAFETY | DISARMED |
| ARMED | play(rec, duration) | armed < 30 s ago | level = min(requested, limit); duration = min(duration, max); render; open stream; start watchdog (duration + 1 s) | PLAYING |
| ARMED | arm expired | | SC_OUTPUT_SAFETY "arm again" | DISARMED |
| PLAYING | end of buffer / watchdog / device error | | mute, close stream | DISARMED |
| PLAYING | stop() / Esc | | 10 ms fade, mute, close | DISARMED |
| any | stop() | | idempotent | DISARMED |

Arming is **one-shot**: after any playback the controller is DISARMED. A new controller (after restart or reconnect) always starts DISARMED, so nothing resumes on its own. Measurement captures with a stimulus record the effective StimulusRecord in the manifest (kind, level, parameters, device), keeping measurement and audition signals separate. Audition plays a copy normalised to the limit and never modifies stored data (tested).

Feedback-loop prevention: arming the same device as the active input requires explicit confirmation ("headphones or loopback cable"). Procedure stimulus levels are capped at -12 dBFS.

## 3 Device selection and reconnection

Output device from settings or the Live screen list. If the device disappears during playback, PortAudio finishes the stream → `_mute` → DISARMED with `last_error`.
