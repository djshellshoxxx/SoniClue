"""Stimulus generation and audition with output safety interlocks
(docs/specs/11-stimulus-and-audition.md; SM-004).

Safety rules (all enforced in code and covered by tests/test_stimulus.py):
* Output never starts without an explicit ``arm()`` followed by ``play()``.
  Arming is one-shot: after a playback ends, stops or fails, the controller
  returns to DISARMED and must be re-armed. Nothing resumes on its own after
  a crash or device reconnection, because a new controller always starts
  DISARMED.
* ARMED expires after ``arm_timeout_s`` (default 30 s) without play.
* Level limit: the requested peak level is clamped to the armed limit, which
  is itself clamped to ABSOLUTE_MAX_DBFS (-6 dBFS peak).
* Duration limit: at most the armed ``max_duration_s`` (<= 120 s). A
  watchdog thread stops playback 1 s after the expected end even if the
  device never reports completion.
* 50 ms raised-cosine fade-in/out, and a 10 ms fade on immediate stop(), so
  there are no clicks that could damage tweeters.
* Feedback guard: arming an output on the same device as an active input
  requires ``allow_same_device=True`` (acoustic loop risk).
* Audition (playing recorded evidence) uses the same interlocks. Playback is
  peak-normalised to the limit and works on a copy; stored data is never
  modified.
"""

from __future__ import annotations

import enum
import threading
import time

import numpy as np

from ..acquisition.backends import AudioBackend
from ..domain.errors import SafetyError, StateError
from ..domain.model import StimulusRecord
from ..dsp import signals

ABSOLUTE_MAX_DBFS = -6.0
MAX_DURATION_S = 120.0
FADE_S = 0.05


class OutState(str, enum.Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    PLAYING = "playing"


def generate(rec: StimulusRecord, fs: float, duration_s: float) -> np.ndarray:
    p = rec.params
    if rec.kind == "sine":
        x = signals.sine(p.get("freq", 1000.0), 1.0, duration_s, fs)
    elif rec.kind == "sweep":
        x = signals.chirp(p.get("f0", 20.0), min(p.get("f1", 20000.0), 0.45 * fs), 1.0, duration_s, fs)
    elif rec.kind == "white":
        x = signals.white_noise(1.0, duration_s, fs, seed=int(p.get("seed", 1)))
    elif rec.kind == "pink":
        x = signals.pink_noise(1.0, duration_s, fs, seed=int(p.get("seed", 1)))
    elif rec.kind == "band_noise":
        x = signals.band_noise(1.0, p.get("f0", 100.0), p.get("f1", 1000.0), duration_s, fs, seed=int(p.get("seed", 1)))
    elif rec.kind == "impulse":
        x = signals.impulse_train(p.get("interval", 1.0), 1.0, duration_s, fs, width_s=0.0005)
    else:  # pragma: no cover - guarded by the contract Literal
        raise SafetyError(f"unknown stimulus {rec.kind}")
    peak = float(np.max(np.abs(x))) or 1.0
    x = x / peak * 10 ** (rec.level_dbfs / 20)
    n = len(x)
    nf = min(int(FADE_S * fs), n // 2)
    if nf > 0:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))
        x[:nf] *= ramp
        x[-nf:] *= ramp[::-1]
    return x.astype(np.float32)


class OutputController:
    def __init__(self, backend: AudioBackend, *, arm_timeout_s: float = 30.0):
        self.backend = backend
        self.state = OutState.DISARMED
        self.arm_timeout_s = arm_timeout_s
        self._lock = threading.Lock()
        self._buf: np.ndarray | None = None
        self._pos = 0
        self._stream = None
        self._armed_at = 0.0
        self._device = None
        self._fs = 48000.0
        self._limit = -20.0
        self._max_dur = 30.0
        self._stop_fade = 0
        self.last_error: str | None = None
        self.history: list[dict] = []
        self._watchdog: threading.Timer | None = None
        self._done = threading.Event()
        self._mute_lock = threading.RLock()

    # ---------------- arming ----------------
    def arm(self, device: int, samplerate: float, *, level_limit_dbfs: float = -20.0, max_duration_s: float = 30.0,
            active_input_device: int | None = None, allow_same_device: bool = False, confirmed: bool = False) -> None:
        with self._lock:
            if self.state is not OutState.DISARMED:
                raise StateError(f"output is {self.state.value}; disarm first")
            if not confirmed:
                raise SafetyError("arming requires explicit user confirmation")
            if active_input_device is not None and active_input_device == device and not allow_same_device:
                raise SafetyError("output device is also the active input: acoustic feedback risk. Confirm loopback explicitly.")
            self._limit = min(level_limit_dbfs, ABSOLUTE_MAX_DBFS)
            self._max_dur = min(max(0.1, max_duration_s), MAX_DURATION_S)
            self._device, self._fs = device, samplerate
            self._armed_at = time.monotonic()
            self.state = OutState.ARMED

    def disarm(self) -> None:
        self.stop()

    def _check_armed(self) -> None:
        if self.state is not OutState.ARMED:
            raise SafetyError("output is not armed")
        if time.monotonic() - self._armed_at > self.arm_timeout_s:
            self.state = OutState.DISARMED
            raise SafetyError("arming expired; arm again")

    # ---------------- playback ----------------
    def play(self, rec: StimulusRecord, duration_s: float) -> StimulusRecord:
        with self._lock:
            self._check_armed()
            dur = min(duration_s, self._max_dur)
            level = min(rec.level_dbfs, self._limit)
            eff = rec.model_copy(update={"level_dbfs": level, "output_device": str(self._device)})
            buf = generate(eff, self._fs, dur)
            self._start(buf, eff, dur)
            return eff

    def audition(self, data: np.ndarray, fs: float) -> None:
        with self._lock:
            self._check_armed()
            if abs(fs - self._fs) > 0.5:
                raise SafetyError(f"armed at {self._fs:g} Hz, recording is {fs:g} Hz")
            x = np.array(data, dtype=np.float32, copy=True).reshape(-1)[: int(self._max_dur * fs)]
            peak = float(np.max(np.abs(x))) if x.size else 0.0
            if peak > 0:
                x *= 10 ** (self._limit / 20) / peak
            nf = min(int(FADE_S * fs), len(x) // 2)
            if nf:
                ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))).astype(np.float32)
                x[:nf] *= ramp
                x[-nf:] *= ramp[::-1]
            self._start(x, StimulusRecord(kind="impulse", level_dbfs=self._limit, params={"audition": 1.0}),
                        len(x) / fs)

    def _start(self, buf: np.ndarray, rec: StimulusRecord, dur: float) -> None:
        self._buf, self._pos, self._stop_fade = buf, 0, 0
        self._finishing = False
        self._done.clear()
        self.last_error = None
        self._finishing = False
        self.state = OutState.PLAYING  # before start(): the callback must see PLAYING
        try:
            self._stream = self.backend.open_output(self._device, self._fs, 1, 1024, self._fill, self._on_finished)
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._mute(f"output failed: {exc}")
            raise SafetyError(f"cannot start output: {exc}") from exc
        self.history.append({"kind": rec.kind, "level_dbfs": rec.level_dbfs, "duration_s": dur, "t": time.time()})
        self._watchdog = threading.Timer(dur + 1.0, lambda: self._mute("watchdog stop"))
        self._watchdog.daemon = True
        self._watchdog.start()

    def _fill(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, np.float32)
        buf = self._buf
        if buf is None or self.state is not OutState.PLAYING:
            return out
        n = max(0, min(frames, len(buf) - self._pos))
        out[:n] = buf[self._pos : self._pos + n]
        if self._stop_fade:
            ramp = np.linspace(1, 0, min(self._stop_fade, frames), dtype=np.float32)
            out[: len(ramp)] *= ramp
            out[len(ramp):] = 0
            self._pos = len(buf)
        else:
            self._pos += n
        if self._pos >= len(buf) and not self._finishing:
            self._finishing = True
            threading.Thread(target=self._mute, args=(None,), daemon=True).start()
        return out

    def _on_finished(self, error: str | None) -> None:
        if error:
            self._mute(error)

    def _mute(self, error: str | None) -> None:
        """Return to the safe state: silence, close the stream, disarm."""
        with self._mute_lock:
            self._buf = None
            if self._watchdog:
                self._watchdog.cancel()
            st = self._stream
            self._stream = None
            if st is not None:
                try:
                    st.stop()
                    st.close()
                except Exception:  # noqa: BLE001
                    pass
            if error and error != "watchdog stop":
                self.last_error = error
            self.state = OutState.DISARMED
            self._done.set()

    def stop(self) -> None:
        """Immediate stop with a 10 ms fade. Idempotent; always ends DISARMED."""
        if self.state is OutState.PLAYING:
            self._stop_fade = max(1, int(0.01 * self._fs))
            self._done.wait(0.2)
        self._mute(None)

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)
