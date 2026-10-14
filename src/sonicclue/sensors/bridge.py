"""Sensor bridge protocol v1 (CON-016; docs/specs/06-sensors-and-calibration.md section 6).

A small microcontroller bridge (for example a MEMS accelerometer on an SPI/I2C
bus) streams binary packets over a USB serial port. This module is the
host-side codec. It is fully testable without hardware. The firmware itself
is out of scope until a bridge board is selected (decision DEC-004b, BLOCKED).

Frame layout (little-endian):

    0xA5 0x5A | version:u8 | type:u8 | length:u16 | payload[length] | crc16:u16

* CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over version..payload.
* type 1 HELLO: rate:f32, axes:u8, full_scale_g:f32, model:16s, firmware:16s
* type 2 DATA:  seq:u16, sample_counter:u32, device_time_us:u64, axes:u8, n:u16, n*axes*int16
* type 3 ERROR: code:u8, message (<=64 bytes ASCII)
* length <= 4096. Anything longer is treated as corruption and resynchronised.

Integrity rules:
* seq increments by 1 mod 65536 per DATA packet. A jump means lost packets,
  which become a Gap of the lost sample count when it can be inferred from
  sample_counter.
* sample_counter must equal the previous counter plus the previous n. A
  decrease means a device reset (CLOCK_RESET).
* device_time_us must increase. A per-packet period deviating more than 5%
  from n/rate flags NONUNIFORM_TIMESTAMPS.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from ..domain.model import BridgeData, BridgeError, BridgeHello, QualityCode, QualityFlag, Severity

SYNC = b"\xa5\x5a"
VERSION = 1
MAX_PAYLOAD = 4096
T_HELLO, T_DATA, T_ERROR = 1, 2, 3


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _frame(ptype: int, payload: bytes) -> bytes:
    body = struct.pack("<BBH", VERSION, ptype, len(payload)) + payload
    return SYNC + body + struct.pack("<H", crc16_ccitt(body))


def encode_hello(m: BridgeHello) -> bytes:
    return _frame(T_HELLO, struct.pack("<fBf16s16s", m.sample_rate_hz, m.axes, m.full_scale_g,
                                       m.device_model.encode()[:16], m.firmware_version.encode()[:16]))


def encode_data(m: BridgeData) -> bytes:
    flat = np.asarray(m.samples, dtype="<i2").reshape(-1)
    return _frame(T_DATA, struct.pack("<HIQBH", m.seq, m.sample_counter, m.device_time_us, m.axes, len(m.samples)) + flat.tobytes())


def encode_error(m: BridgeError) -> bytes:
    return _frame(T_ERROR, struct.pack("<B", m.code) + m.message.encode()[:64])


@dataclass
class BridgeDecoder:
    """Streaming decoder. Feed arbitrary byte chunks; complete messages come back."""

    buf: bytearray = field(default_factory=bytearray)
    crc_errors: int = 0
    resyncs: int = 0

    def feed(self, data: bytes) -> list[BridgeHello | BridgeData | BridgeError]:
        self.buf.extend(data)
        out = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                if len(self.buf) > 1:
                    self.buf[:] = self.buf[-1:]
                break
            if i > 0:
                self.resyncs += 1
                del self.buf[:i]
            if len(self.buf) < 6:
                break
            ver, ptype, length = struct.unpack_from("<BBH", self.buf, 2)
            if ver != VERSION or length > MAX_PAYLOAD or ptype not in (T_HELLO, T_DATA, T_ERROR):
                self.resyncs += 1
                del self.buf[:2]
                continue
            total = 2 + 4 + length + 2
            if len(self.buf) < total:
                break
            body = bytes(self.buf[2 : 6 + length])
            (crc,) = struct.unpack_from("<H", self.buf, 6 + length)
            if crc != crc16_ccitt(body):
                self.crc_errors += 1
                del self.buf[:2]
                continue
            del self.buf[:total]
            msg = self._decode(ptype, body[4:])
            if msg is not None:
                out.append(msg)
        return out

    def _decode(self, ptype: int, p: bytes):
        try:
            if ptype == T_HELLO:
                rate, axes, fsg, model, fw = struct.unpack("<fBf16s16s", p)
                return BridgeHello(protocol_version=VERSION, sample_rate_hz=rate, axes=axes, full_scale_g=fsg,
                                   device_model=model.rstrip(b"\0").decode(errors="replace"),
                                   firmware_version=fw.rstrip(b"\0").decode(errors="replace"))
            if ptype == T_DATA:
                seq, ctr, tus, axes, n = struct.unpack_from("<HIQBH", p)
                raw = np.frombuffer(p, dtype="<i2", offset=17, count=n * axes).reshape(n, axes)
                return BridgeData(seq=seq, sample_counter=ctr, device_time_us=tus, axes=axes, samples=raw.tolist())
            code = p[0]
            return BridgeError(code=code, message=p[1:65].decode(errors="replace"))
        except (struct.error, ValueError):
            self.crc_errors += 1
            return None


MAX_ZERO_FILL = 50_000_000  # total frames of lost-packet zero fill per dump (bounds memory on crafted input)


@dataclass
class BridgeAssembly:
    hello: BridgeHello | None
    samples: np.ndarray  # frames x axes, FS units (count/32768)
    gaps: list[tuple[int, int]]
    flags: list[QualityFlag]
    device_errors: list[str]


def assemble(messages: list, decoder: BridgeDecoder | None = None) -> BridgeAssembly:
    """Turn decoded messages into one contiguous stream. Lost packets become
    zero-filled gaps (marked invalid), so the sample index stays aligned with
    the device sample counter."""
    hello = next((m for m in messages if isinstance(m, BridgeHello)), None)
    data = [m for m in messages if isinstance(m, BridgeData)]
    errs = [m.message for m in messages if isinstance(m, BridgeError)]
    flags: list[QualityFlag] = []
    if not data:
        return BridgeAssembly(hello, np.zeros((0, hello.axes if hello else 1), np.float32), [], flags, errs)
    axes = data[0].axes
    blocks, gaps = [], []
    pos = 0
    prev = None
    rate = hello.sample_rate_hz if hello else None
    nonuniform = 0
    zero_total = 0
    for d in data:
        if d.axes != axes:
            flags.append(QualityFlag(code=QualityCode.DROPOUT_GAP, severity=Severity.WARNING,
                                     message=f"packet with {d.axes} axes (expected {axes}) discarded"))
            continue
        n = len(d.samples)
        if prev is not None:
            expected_ctr = (prev.sample_counter + len(prev.samples)) % 2**32
            if d.sample_counter < prev.sample_counter and (prev.sample_counter - d.sample_counter) < 2**31:
                flags.append(QualityFlag(code=QualityCode.CLOCK_RESET, severity=Severity.INVALID, start_frame=pos,
                                         message=f"bridge sample counter reset at frame {pos} (device restarted)"))
            elif d.sample_counter != expected_ctr:
                lost = (d.sample_counter - expected_ctr) % 2**32
                if 0 < lost < 10_000_000 and zero_total + lost <= MAX_ZERO_FILL:
                    zero_total += lost
                    blocks.append(np.zeros((lost, axes), np.float32))
                    gaps.append((pos, pos + lost))
                    pos += lost
            if rate and d.device_time_us > prev.device_time_us:
                period = (d.device_time_us - prev.device_time_us) * 1e-6
                nominal = len(prev.samples) / rate
                if nominal > 0 and abs(period - nominal) / nominal > 0.05:
                    nonuniform += 1
        blocks.append(np.asarray(d.samples, np.float32) / 32768.0)
        pos += n
        prev = d
    if gaps:
        flags.append(QualityFlag(code=QualityCode.DROPOUT_GAP, severity=Severity.WARNING,
                                 message=f"{len(gaps)} lost bridge packet runs ({sum(b - a for a, b in gaps)} samples) marked as gaps"))
    if nonuniform:
        flags.append(QualityFlag(code=QualityCode.NONUNIFORM_TIMESTAMPS, severity=Severity.WARNING,
                                 message=f"{nonuniform} packets with device-time period >5% from nominal"))
    if decoder and decoder.crc_errors:
        flags.append(QualityFlag(code=QualityCode.DROPOUT_GAP, severity=Severity.WARNING,
                                 message=f"{decoder.crc_errors} corrupted bridge packets discarded"))
    return BridgeAssembly(hello, np.concatenate(blocks), gaps, flags, errs)
