"""Disk-spooled channel source for full-length analysis (TASK-012, spec 16 section 5).

``ChannelSpool`` copies a capture into one float32 file per
channel, reading the capture in bounded blocks. The analysis pipeline then
works on the on-demand file arrays with the same code path as in-memory arrays, so the
results are identical to a non-streamed run while resident memory stays
O(block) instead of O(capture). The spool is private to one analysis run and is
deleted on exit.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..domain.errors import AnalysisError

BLOCK_FRAMES = 1 << 20
DISK_MARGIN = 1.1  # required free space as a multiple of the spool size

class FileArray:
    """1-D float32 array stored in a file and read/written on demand (``pread``-style),
    so only the requested block is ever resident. Supports ``len``, ``shape``,
    slice get/set and 1-/2-D integer-array gets (the covering range is read once).
    It deliberately has no ``__array__``: whole-array numpy calls fail loudly
    instead of silently loading the capture."""

    dtype = np.dtype(np.float32)

    def __init__(self, path: Path, n: int):
        self.n = n
        self.shape = (n,)
        self._fh = open(path, "w+b")
        self._fh.truncate(n * 4)

    def __len__(self) -> int:
        return self.n

    def _read(self, a: int, b: int) -> np.ndarray:
        out = np.empty(b - a, np.float32)
        self._fh.seek(a * 4)
        if b > a and self._fh.readinto(memoryview(out).cast("B")) != (b - a) * 4:
            raise AnalysisError("analysis spool truncated")
        return out

    def __getitem__(self, key) -> np.ndarray:
        if isinstance(key, slice):
            a, b, step = key.indices(self.n)
            if step != 1:
                raise IndexError("FileArray supports unit-step slices only")
            return self._read(a, max(a, b))
        idx = np.asarray(key)
        if idx.size == 0:
            return np.empty(idx.shape, np.float32)
        lo, hi = int(idx.min()), int(idx.max()) + 1
        if lo < 0 or hi > self.n:
            raise IndexError("index outside spool")
        return self._read(lo, hi)[idx - lo]

    def __setitem__(self, key, value) -> None:
        if not isinstance(key, slice):
            raise IndexError("FileArray supports slice assignment only")
        a, b, step = key.indices(self.n)
        v = np.broadcast_to(np.asarray(value, np.float32), (max(a, b) - a,))
        self._fh.seek(a * 4)
        self._fh.write(np.ascontiguousarray(v).tobytes())

    def close(self) -> None:
        self._fh.close()


Loader = Callable[[int, int], np.ndarray]  # (start, stop) -> float32 (frames, channels)


class ChannelSpool:
    """Context manager exposing ``shape`` and ``column(i)`` like a 2-D array."""

    def __init__(self, loader: Loader, frames: int, channels: int, workdir: Path | None = None):
        self.shape = (frames, channels)
        self._loader = loader
        self._workdir = workdir
        self._dir: Path | None = None
        self._maps: list[FileArray] = []

    def __enter__(self) -> ChannelSpool:
        frames, nch = self.shape
        base = Path(self._workdir) if self._workdir else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        need = frames * nch * 4
        free = shutil.disk_usage(base).free
        if free < need * DISK_MARGIN:
            raise AnalysisError(f"not enough free disk space for analysis spool: need {need / 1e9:.2f} GB, have {free / 1e9:.2f} GB")
        self._dir = Path(tempfile.mkdtemp(prefix=".sc-spool-", dir=base))
        try:
            self._maps = [FileArray(self._dir / f"ch{c}.f32", frames) for c in range(nch)]
            for a in range(0, frames, BLOCK_FRAMES):
                b = min(frames, a + BLOCK_FRAMES)
                blk = self._loader(a, b)
                if blk.shape != (b - a, nch):
                    raise AnalysisError(f"capture block {a}:{b} has shape {blk.shape}, expected {(b - a, nch)}")
                for c in range(nch):
                    self._maps[c][a:b] = blk[:, c]
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def column(self, col: int) -> np.ndarray:
        """Writable, privately owned 1-D float32 file-backed array for channel ``col``."""
        return self._maps[col]

    def __exit__(self, *exc) -> None:
        for m in self._maps:
            m.close()
        self._maps = []
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None
