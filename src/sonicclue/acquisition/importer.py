"""File and bridge-dump importers.

Imported audio is converted to float32 FS for analysis, and the original file
is copied byte-for-byte into the capture directory (``original.<ext>``) with
its SHA-256 recorded, so the source is preserved exactly. Integer PCM up to
24 bits converts to float32 losslessly. 32-bit integer PCM loses its lowest 8
bits in the analysis copy only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from ..domain.errors import ValidationError
from ..sensors import bridge

MAX_IMPORT_BYTES = 8 * 1024**3
SUPPORTED_SUFFIXES = {".wav", ".flac", ".aif", ".aiff", ".ogg", ".w64", ".rf64", ".caf"}


def probe(path: Path) -> dict:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValidationError(f"unsupported audio format {path.suffix}", code="SC_IMPORT_FORMAT")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValidationError("file exceeds 8 GiB import limit", code="SC_IMPORT_SIZE")
    try:
        info = sf.info(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"cannot read audio file: {exc}", code="SC_IMPORT_FORMAT") from exc
    if info.channels < 1 or info.channels > 64 or info.samplerate <= 0:
        raise ValidationError("audio file has an invalid channel count or sample rate", code="SC_IMPORT_FORMAT")
    lossy = info.format in ("OGG", "MP3") or "VORBIS" in info.subtype or "OPUS" in info.subtype
    return {"samplerate": float(info.samplerate), "channels": info.channels, "frames": info.frames,
            "format": info.format, "subtype": info.subtype, "lossy": lossy}


def import_audio(path: Path, writer, blockframes: int = 1 << 18) -> int:
    """Stream ``path`` into ``writer`` (the app layer copies and hashes the original). Returns frames."""
    path = Path(path)
    frames = 0
    with sf.SoundFile(str(path)) as f:
        while True:
            d = f.read(blockframes, dtype="float32", always_2d=True)
            if not len(d):
                break
            writer.write(d)
            frames += len(d)
    writer.close()
    return frames


def decode_bridge_dump(path: Path):
    """Decode a raw serial dump from a sensor bridge into a contiguous stream."""
    data = Path(path).read_bytes()
    if len(data) > 2 * 1024**3:
        raise ValidationError("bridge dump too large", code="SC_IMPORT_SIZE")
    dec = bridge.BridgeDecoder()
    msgs = []
    for i in range(0, len(data), 1 << 16):
        msgs += dec.feed(data[i : i + (1 << 16)])
    asm = bridge.assemble(msgs, dec)
    if asm.hello is None:
        raise ValidationError("no HELLO packet: unknown sample rate", code="SC_BRIDGE_NO_HELLO")
    if asm.samples.shape[0] == 0:
        raise ValidationError("no sample data in bridge dump", code="SC_BRIDGE_EMPTY")
    return asm


def array_writer_feed(writer, samples: np.ndarray, block: int = 1 << 16) -> int:
    for i in range(0, len(samples), block):
        writer.write(samples[i : i + block].astype(np.float32))
    writer.close()
    return len(samples)
