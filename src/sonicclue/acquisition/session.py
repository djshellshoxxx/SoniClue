"""Capture session: device callback -> bounded queue -> writer thread -> sink.

State machine (docs/specs/05-acquisition.md section 5; SM-001):

    IDLE --start()--> RUNNING --stop()/duration reached--> STOPPING --> COMPLETED
                         |  device error ----------------> STOPPING --> FAILED (partial data kept)
                         +--cancel()---------------------> STOPPING --> CANCELLED (data discarded by owner)

* start() is allowed only in IDLE (otherwise SC_STATE). stop() and cancel()
  are idempotent. After a terminal state the session cannot be restarted;
  create a new one.
* Ownership: the backend thread owns the callback buffer only during the
  callback and copies the block into the queue (one allocation per block;
  Python cannot avoid this). The writer thread owns the sink, the frame
  counters and the live-monitor buffer, guarded by ``_mon_lock`` (the only
  lock; it is never held while calling the sink).
* Backpressure: the queue holds QUEUE_SECONDS of audio. If it is full, the
  callback drops the block and records (frame_index, frames). The writer
  zero-fills the dropped range and records a Gap(queue_overflow), so the
  timeline stays aligned with the converter clock and the excluded range is
  explicit.
* PortAudio input_overflow (frames lost inside the driver; the count is
  unknown) is recorded as a zero-length Gap(input_overflow) with a warning.
  Multi-capture alignment across that point is invalid.
"""

from __future__ import annotations

import enum
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

import numpy as np

from ..domain.errors import DeviceError, StateError
from ..domain.model import Gap, QualityCode, QualityFlag, Severity, utcnow
from .backends import AudioBackend

QUEUE_SECONDS = 4.0


class CaptureSink(Protocol):
    def write(self, block: np.ndarray) -> None: ...
    def close(self) -> list[dict]: ...


class SessionState(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED}


@dataclass
class LiveSnapshot:
    state: SessionState
    frames: int
    seconds: float
    peak_dbfs: list[float]
    rms_dbfs: list[float]
    recent: np.ndarray  # last ~1 s, frames x channels
    gaps: int
    clipped: list[bool]


@dataclass
class CaptureOutcome:
    state: SessionState
    frames: int
    chunks: list[dict]
    gaps: list[Gap]
    flags: list[QualityFlag]
    started_utc: datetime
    error: str | None = None


@dataclass
class _Drop:
    start: int
    frames: int


class CaptureSession:
    def __init__(self, backend: AudioBackend, device: int, samplerate: float, channels: int, sink: CaptureSink, *,
                 duration_s: float | None = None, blocksize: int = 1024, exclusive: bool = False,
                 on_state: Callable[[SessionState], None] | None = None):
        if duration_s is not None and duration_s <= 0:
            raise StateError("duration must be positive")
        self.backend, self.device, self.fs, self.nch = backend, device, float(samplerate), int(channels)
        self.sink, self.blocksize, self.exclusive = sink, blocksize, exclusive
        self.max_frames = int(round(duration_s * samplerate)) if duration_s else None
        self.on_state = on_state
        self.state = SessionState.IDLE
        maxblocks = max(4, int(QUEUE_SECONDS * samplerate / blocksize))
        self._q: queue.Queue = queue.Queue(maxsize=maxblocks)
        self._drops: deque[_Drop] = deque()
        self._stream = None
        self._writer: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._cancel = False
        self._error: str | None = None
        self._frames = 0
        self._gaps: list[Gap] = []
        self._flags: list[QualityFlag] = []
        self._mon_lock = threading.Lock()
        self._recent = np.zeros((int(samplerate), channels), np.float32)
        self._peak = np.zeros(channels)
        self._rms = np.zeros(channels)
        self._clip = np.zeros(channels, bool)
        self._clip_count = np.zeros(channels, np.int64)
        self._done = threading.Event()
        self.started_utc = utcnow()
        self._chunks: list[dict] = []

    # ---------------- lifecycle ----------------
    def _set(self, st: SessionState):
        self.state = st
        if self.on_state:
            try:
                self.on_state(st)
            except Exception:  # noqa: BLE001 - UI callbacks must not break capture
                pass

    def start(self) -> None:
        if self.state is not SessionState.IDLE:
            raise StateError(f"cannot start a session in state {self.state.value}")
        self.backend.check_input(self.device, self.fs, self.nch)
        self._stream = self.backend.open_input(self.device, self.fs, self.nch, self.blocksize, self._callback,
                                               self._on_finished, exclusive=self.exclusive)
        self.started_utc = utcnow()
        self._writer = threading.Thread(target=self._write_loop, name="capture-writer", daemon=True)
        self._set(SessionState.RUNNING)
        self._writer.start()
        try:
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._error = f"device start failed: {exc}"
            self._stop_evt.set()
            self._writer.join(timeout=10)
            raise DeviceError(self._error) from exc

    def stop(self) -> None:
        if self.state in (SessionState.IDLE,):
            self._set(SessionState.CANCELLED)
            self._done.set()
            return
        if self.state in TERMINAL or self.state is SessionState.STOPPING:
            return
        self._set(SessionState.STOPPING)
        self._stop_evt.set()

    def cancel(self) -> None:
        self._cancel = True
        self.stop()

    def wait(self, timeout: float | None = None) -> CaptureOutcome:
        if not self._done.wait(timeout):
            raise StateError("capture did not finish within timeout")
        return self.outcome()

    def outcome(self) -> CaptureOutcome:
        return CaptureOutcome(self.state, self._frames, self._chunks, list(self._gaps), list(self._flags),
                              self.started_utc, self._error)

    # ---------------- backend thread ----------------
    def _callback(self, block: np.ndarray, frame_index: int, status: set) -> None:
        if self._stop_evt.is_set():
            return
        try:
            self._q.put_nowait((frame_index, block.copy(), status))
        except queue.Full:
            self._drops.append(_Drop(frame_index, len(block)))

    def _on_finished(self, error: str | None) -> None:
        if error:
            self._error = error
        self._stop_evt.set()

    # ---------------- writer thread ----------------
    def _write_loop(self) -> None:
        expected = 0
        try:
            while True:
                try:
                    idx, block, status = self._q.get(timeout=0.1)
                except queue.Empty:
                    if self._stop_evt.is_set():
                        break
                    continue
                if idx > expected:  # dropped blocks: zero-fill to keep the timeline
                    expected += self._fill_gap(expected, idx - expected, "queue_overflow")
                    if self.max_frames is not None and expected >= self.max_frames:
                        self._frames = expected
                        self._stop_evt.set()
                        break
                if "input_overflow" in status:
                    self._gaps.append(Gap(start_frame=expected, end_frame=expected, reason="input_overflow"))
                if self.max_frames is not None:
                    block = block[: max(0, self.max_frames - expected)]
                if len(block):
                    self.sink.write(block)
                    self._monitor(block)
                expected += len(block)
                self._frames = expected
                if self.max_frames is not None and expected >= self.max_frames:
                    self._stop_evt.set()
                    break
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:  # noqa: BLE001
                    pass
            # drain blocks that arrived before the stream stopped
            while not self._q.empty() and not self._cancel:
                idx, block, status = self._q.get_nowait()
                if self.max_frames is not None:
                    block = block[: max(0, self.max_frames - expected)]
                if self.max_frames is not None and expected >= self.max_frames:
                    break
                if idx >= expected and len(block):
                    if idx > expected:
                        expected += self._fill_gap(expected, idx - expected, "queue_overflow")
                        if self.max_frames is not None:
                            block = block[: max(0, self.max_frames - expected)]
                    if len(block):
                        self.sink.write(block)
                        expected += len(block)
            self._frames = expected
        except Exception as exc:  # noqa: BLE001 - disk full, sink failure
            self._error = f"writer failed: {exc}"
        finally:
            try:
                self._chunks = self.sink.close()
            except Exception as exc:  # noqa: BLE001
                self._error = self._error or f"finalising capture failed: {exc}"
            self._finish_flags()
            if self._cancel:
                self._set(SessionState.CANCELLED)
            elif self._error:
                self._set(SessionState.FAILED)
            else:
                self._set(SessionState.COMPLETED)
            self._done.set()

    def _fill_gap(self, start: int, n: int, reason: str) -> int:
        """Zero-fill ``n`` dropped frames (clamped to the requested duration). Returns frames written."""
        if self.max_frames is not None:
            n = min(n, self.max_frames - start)
        n = max(0, min(n, int(self.fs * 3600)))
        if n:
            self.sink.write(np.zeros((n, self.nch), np.float32))
            self._gaps.append(Gap(start_frame=start, end_frame=start + n, reason=reason))
        return n

    def _monitor(self, block: np.ndarray) -> None:
        with np.errstate(divide="ignore"):
            pk = np.max(np.abs(block), axis=0)
            rms = np.sqrt(np.mean(block.astype(np.float64) ** 2, axis=0))
        clipped = np.sum(np.abs(block) >= 0.999, axis=0)
        with self._mon_lock:
            n = len(block)
            if n >= len(self._recent):
                self._recent[:] = block[-len(self._recent):]
            else:
                self._recent = np.roll(self._recent, -n, axis=0)
                self._recent[-n:] = block
            self._peak = np.maximum(self._peak * 0.9, pk)
            self._rms = rms
            self._clip_count += clipped
            self._clip |= clipped > 0

    def _finish_flags(self) -> None:
        if self._gaps:
            lost = sum(g.end_frame - g.start_frame for g in self._gaps)
            self._flags.append(QualityFlag(code=QualityCode.DROPOUT_GAP, severity=Severity.WARNING,
                                           message=f"{len(self._gaps)} dropouts ({lost} frames zero-filled and excluded from analysis)"))
        for ch in np.flatnonzero(self._clip_count):
            self._flags.append(QualityFlag(code=QualityCode.CLIPPING, severity=Severity.INVALID, channel=int(ch),
                                           message=f"{int(self._clip_count[ch])} clipped samples during capture"))
        if self._error:
            self._flags.append(QualityFlag(code=QualityCode.DEVICE_DISCONNECTED, severity=Severity.WARNING,
                                           message=f"capture ended early: {self._error}"))

    # ---------------- monitoring (any thread) ----------------
    def snapshot(self) -> LiveSnapshot:
        with self._mon_lock:
            to_db = lambda v: [float(20 * np.log10(max(x, 1e-12))) for x in v]  # noqa: E731
            return LiveSnapshot(self.state, self._frames, self._frames / self.fs, to_db(self._peak), to_db(self._rms),
                                self._recent.copy(), len(self._gaps), [bool(c) for c in self._clip])

    @property
    def dropped_blocks(self) -> int:
        return len(self._drops)


@dataclass
class TimedWait:
    """Helper for procedures: settle intervals that can be cancelled."""

    cancel: threading.Event = field(default_factory=threading.Event)

    def sleep(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.cancel.wait(min(0.1, end - time.monotonic())):
                return False
        return True
