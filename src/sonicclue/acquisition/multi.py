"""Simultaneous multi-device capture (REQ-ACQ-014, TASK-031).

Coordinates several independent :class:`CaptureSession` objects, one per device.
Devices run on separate converter clocks, so the sessions are *never* assumed
synchronized: alignment is estimated afterwards from a shared acoustic or
electrical reference (``sync.estimate_mapping``). Start is all-or-nothing: if
any device fails to start, the already-started ones are cancelled and the
error is re-raised, so no half-started session is left running.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.errors import DeviceError, StateError
from ..domain.model import ClockMapping, QualityFlag
from ..sync import estimate_mapping
from .backends import AudioBackend
from .session import CaptureOutcome, CaptureSession, CaptureSink


@dataclass
class DeviceSpec:
    name: str
    backend: AudioBackend
    device: int
    samplerate: float
    channels: int
    sink: CaptureSink
    blocksize: int = 1024


class MultiCaptureSession:
    def __init__(self, specs: list[DeviceSpec], *, duration_s: float | None = None):
        if len(specs) < 2:
            raise StateError("multi-device capture needs at least two devices")
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise StateError("device names must be unique")
        self.sessions = {s.name: CaptureSession(s.backend, s.device, s.samplerate, s.channels, s.sink,
                                                duration_s=duration_s, blocksize=s.blocksize) for s in specs}
        self._started = False

    def start(self) -> None:
        if self._started:
            raise StateError("multi-device session already started")
        self._started = True
        began: list[CaptureSession] = []
        try:
            for s in self.sessions.values():
                s.start()
                began.append(s)
        except Exception as exc:  # noqa: BLE001
            for s in began:
                s.cancel()
            for s in began:
                s.wait(timeout=10)
            if isinstance(exc, DeviceError):
                raise
            raise DeviceError(f"multi-device start failed: {exc}") from exc

    def stop(self) -> None:
        for s in self.sessions.values():
            s.stop()

    def wait(self, timeout: float | None = None) -> dict[str, CaptureOutcome]:
        return {n: s.wait(timeout) for n, s in self.sessions.items()}


def align_pair(ref: np.ndarray, fs_ref: float, other: np.ndarray, fs_other: float, *, ref_id: str,
               other_id: str) -> tuple[ClockMapping, list[QualityFlag], np.ndarray]:
    """Estimate the clock mapping between two devices' recordings of a shared reference."""
    return estimate_mapping(ref, fs_ref, other, fs_other, ref_id=ref_id, other_id=other_id)
