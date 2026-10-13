"""Chunked, journaled capture writer (implements acquisition.CaptureSink).

Layout: ``captures/<capture_id>/chunk_00000.wav ...`` as float32 WAV (RF64
when a chunk would exceed 4 GiB; in practice chunks are CHUNK_SECONDS long).
After each completed chunk, ``journal.json`` is atomically rewritten with the
chunk list (file, start_frame, frames, sha256) and the capture header. If the
process dies, ``CaseStore.recover()`` rebuilds a manifest with status
"recovered" from the journal. At most the last unfinished chunk is lost.

Original samples are written exactly as received from the converter (float32).
No gain, filtering, limiting, dithering or compression is applied.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from ..domain.errors import StateError, StorageError
from .files import atomic_write_text, make_readonly, sha256_file

CHUNK_SECONDS = 10.0


class CaptureWriter:
    def __init__(self, capture_dir: Path, capture_id: str, sample_rate: float, channels: int, header: dict,
                 chunk_seconds: float = CHUNK_SECONDS):
        self.dir = Path(capture_dir)
        self.dir.mkdir(parents=True, exist_ok=False)
        self.capture_id = capture_id
        self.fs = sample_rate
        self.nch = channels
        self.header = header
        self.chunk_frames = max(1024, int(round(chunk_seconds * sample_rate)))
        self._buf: list[np.ndarray] = []
        self._buffered = 0
        self.frames_written = 0
        self.chunks: list[dict] = []
        self._closed = False
        self._lock = threading.Lock()
        self._journal()

    def write(self, block: np.ndarray) -> None:
        """Append frames (shape frames x channels, float32 FS). Called from the writer thread only."""
        if self._closed:
            raise StateError("writer is closed")
        if block.ndim != 2 or block.shape[1] != self.nch:
            raise StorageError(f"block shape {block.shape} does not match {self.nch} channels")
        with self._lock:
            self._buf.append(np.asarray(block, dtype=np.float32))
            self._buffered += block.shape[0]
            while self._buffered >= self.chunk_frames:
                self._flush(self.chunk_frames)

    def _flush(self, nframes: int) -> None:
        data = np.concatenate(self._buf) if len(self._buf) > 1 else self._buf[0]
        out, rest = data[:nframes], data[nframes:]
        self._buf = [rest] if len(rest) else []
        self._buffered = len(rest)
        name = f"chunk_{len(self.chunks):05d}.wav"
        path = self.dir / name
        tmp = self.dir / (name + ".part")
        fmt = "RF64" if out.nbytes > 3.9e9 else "WAV"
        sf.write(str(tmp), out, int(round(self.fs)), subtype="FLOAT", format=fmt)
        tmp.replace(path)
        make_readonly(path)
        self.chunks.append({"file": name, "start_frame": self.frames_written, "frames": int(len(out)), "sha256": sha256_file(path)})
        self.frames_written += len(out)
        self._journal()

    def _journal(self) -> None:
        atomic_write_text(self.dir / "journal.json", json.dumps({"capture_id": self.capture_id, "sample_rate_hz": self.fs,
                                                                 "channels": self.nch, "header": self.header,
                                                                 "chunks": self.chunks}, indent=1))

    def close(self) -> list[dict]:
        """Flush remaining frames and return the chunk list. Idempotent."""
        with self._lock:
            if not self._closed:
                if self._buffered:
                    self._flush(self._buffered)
                self._closed = True
        return list(self.chunks)


def read_chunks(capture_dir: Path, chunks: list, start: int = 0, stop: int | None = None, verify: bool = False) -> np.ndarray:
    """Read frames [start, stop) across chunk files as float32 (frames, channels)."""
    parts = []
    for c in chunks:
        cs, cf = c.start_frame, c.frames
        ce = cs + cf
        if stop is not None and cs >= stop:
            break
        if ce <= start:
            continue
        path = Path(capture_dir) / c.file
        if verify and sha256_file(path) != c.sha256:
            from ..domain.errors import IntegrityError

            raise IntegrityError(f"chunk {c.file} checksum mismatch")
        a = max(0, start - cs)
        b = cf if stop is None else min(cf, stop - cs)
        d, _ = sf.read(str(path), start=a, stop=b, dtype="float32", always_2d=True)
        parts.append(d)
    if not parts:
        return np.zeros((0, 1), np.float32)
    return np.concatenate(parts)
