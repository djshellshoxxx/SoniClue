"""Acquisition: session state machine, failure paths, backpressure, importers, bridge protocol."""

import threading
import time

import numpy as np
import pytest
import soundfile as sf

from sonicclue.acquisition.backends import SimulatedBackend, SimWorld
from sonicclue.acquisition.session import CaptureSession, SessionState
from sonicclue.domain.errors import StateError, ValidationError
from sonicclue.domain.model import BridgeData, BridgeError, BridgeHello
from sonicclue.sensors import bridge


class MemSink:
    def __init__(self, slow=0.0):
        self.blocks = []
        self.closed = 0
        self.slow = slow

    def write(self, b):
        if self.slow:
            time.sleep(self.slow)
        self.blocks.append(b.copy())

    def close(self):
        self.closed += 1
        return []

    @property
    def data(self):
        return np.concatenate(self.blocks) if self.blocks else np.zeros((0, 1))


def test_exact_duration_and_double_start_stop():
    be = SimulatedBackend(SimWorld(), speed=100)
    sink = MemSink()
    s = CaptureSession(be, 0, 48000, 2, sink, duration_s=1.0, blocksize=1000)
    s.start()
    with pytest.raises(StateError):
        s.start()
    oc = s.wait(10)
    assert oc.state is SessionState.COMPLETED and oc.frames == 48000 and len(sink.data) == 48000
    s.stop()
    s.stop()  # idempotent
    assert sink.closed == 1


def test_cancel_reports_cancelled():
    s = CaptureSession(SimulatedBackend(speed=1), 0, 48000, 1, MemSink(), duration_s=30)
    s.start()
    time.sleep(0.2)
    s.cancel()
    assert s.wait(5).state is SessionState.CANCELLED


def test_device_disconnect_keeps_partial_data():
    be = SimulatedBackend(speed=100, fail_after_frames=20000)
    sink = MemSink()
    s = CaptureSession(be, 0, 48000, 1, sink, duration_s=5, blocksize=1000)
    s.start()
    oc = s.wait(10)
    assert oc.state is SessionState.FAILED and 19000 <= oc.frames <= 21000
    assert any(f.code.value == "device_disconnected" for f in oc.flags)


def test_queue_overflow_becomes_zero_filled_gap():
    """A slow sink must not silently lose data: dropped blocks become explicit gaps."""
    import sonicclue.acquisition.session as sess_mod

    old = sess_mod.QUEUE_SECONDS
    sess_mod.QUEUE_SECONDS = 0.05
    try:
        be = SimulatedBackend(speed=0)  # unthrottled producer
        sink = MemSink(slow=0.01)
        s = CaptureSession(be, 0, 48000, 1, sink, duration_s=2.0, blocksize=1024)
        s.start()
        oc = s.wait(30)
    finally:
        sess_mod.QUEUE_SECONDS = old
    assert oc.gaps, "expected recorded gaps"
    assert all(g.reason == "queue_overflow" for g in oc.gaps)
    total = len(sink.data)
    assert total == oc.frames == 96000  # timeline preserved despite drops
    g = oc.gaps[0]
    assert np.all(sink.data[g.start_frame : g.end_frame] == 0)
    assert any(f.code.value == "dropout_gap" for f in oc.flags)


def test_clipping_flagged_during_capture():
    w = SimWorld()
    w.chain_hum = False

    class Loud(SimulatedBackend):
        pass

    be = SimulatedBackend(w, speed=100)
    orig = w.render
    w.render = lambda fs, ch, n, start: np.clip(orig(fs, ch, n, start) * 1000, -1, 1).astype(np.float32)
    sink = MemSink()
    s = CaptureSession(be, 0, 48000, 1, sink, duration_s=0.5)
    s.start()
    oc = s.wait(10)
    assert any(f.code.value == "clipping" for f in oc.flags)


def test_invalid_device_format_rejected():
    s = CaptureSession(SimulatedBackend(), 0, 48000, 8, MemSink(), duration_s=1)
    from sonicclue.domain.errors import DeviceError

    with pytest.raises(DeviceError):
        s.start()
    assert s.state is SessionState.IDLE


def test_import_wav_preserves_original_and_values(app, tmp_path):
    app.create_case("imp")
    x = (np.sin(np.arange(48000) * 0.1) * 0.5).astype(np.float32)
    p = tmp_path / "in.wav"
    sf.write(p, np.stack([x, -x], 1), 48000, subtype="PCM_24")
    m = app.import_audio(p)
    assert m.source == "import" and m.frames == 48000 and len(m.channels) == 2
    back = app.capture_data(m.id)
    ref, _ = sf.read(p, dtype="float32")
    np.testing.assert_array_equal(back, ref)
    orig = app.store.capture_dir(m.id) / "original.wav"
    assert orig.read_bytes() == p.read_bytes()
    assert "sha256" in m.context.notes
    with pytest.raises(ValidationError):
        app.import_audio(tmp_path / "x.mp4")


def _hello():
    return BridgeHello(protocol_version=1, device_model="ADXL-test", firmware_version="0.1", sample_rate_hz=1000.0, axes=3, full_scale_g=4.0)


def _pkt(seq, ctr, n=50, t_us=None):
    s = [[(i + ctr) % 100, 2, 3] for i in range(n)]
    return BridgeData(seq=seq, sample_counter=ctr, device_time_us=t_us if t_us is not None else ctr * 1000, axes=3, samples=s)


def test_bridge_roundtrip_streaming_and_resync():
    stream = bridge.encode_hello(_hello()) + b"\x00garbage\xa5" + b"".join(bridge.encode_data(_pkt(i, i * 50)) for i in range(10))
    stream += bridge.encode_error(BridgeError(code=7, message="overrun"))
    dec = bridge.BridgeDecoder()
    msgs = []
    for i in range(0, len(stream), 7):  # arbitrary fragmentation
        msgs += dec.feed(stream[i : i + 7])
    assert isinstance(msgs[0], BridgeHello) and msgs[0].device_model == "ADXL-test"
    data = [m for m in msgs if isinstance(m, BridgeData)]
    assert len(data) == 10 and data[3].samples[0][0] == 50 * 3 % 100
    asm = bridge.assemble(msgs, dec)
    assert asm.samples.shape == (500, 3) and asm.gaps == [] and asm.device_errors == ["overrun"]


def test_bridge_crc_lost_packets_and_reset():
    pk = [bridge.encode_data(_pkt(i, i * 50)) for i in range(6)]
    corrupt = bytearray(pk[2])
    corrupt[12] ^= 0xFF
    stream = bridge.encode_hello(_hello()) + pk[0] + pk[1] + bytes(corrupt) + pk[3] + pk[5]
    stream += bridge.encode_data(_pkt(6, 10))  # counter went backwards: device reset
    dec = bridge.BridgeDecoder()
    msgs = dec.feed(stream)
    assert dec.crc_errors == 1
    asm = bridge.assemble(msgs, dec)
    assert asm.gaps[0] == (100, 150)  # lost packet 2 (corrupt) -> zero-filled gap
    assert asm.gaps[1] == (200, 250)  # lost packet 4
    codes = {f.code.value for f in asm.flags}
    assert {"clock_reset", "dropout_gap"} <= codes


def test_bridge_nonuniform_timestamps():
    msgs = [_hello()] + [_pkt(i, i * 50, t_us=i * 50_000 + (20_000 if i == 3 else 0)) for i in range(6)]
    asm = bridge.assemble(msgs)
    assert any(f.code.value == "nonuniform_timestamps" for f in asm.flags)


def test_bridge_import_through_app(app, tmp_path):
    from sonicclue.domain.model import SensorDescriptor, SensorKind
    from sonicclue.domain.units import Quantity

    app.create_case("br", sensors=[SensorDescriptor(id="acc", kind=SensorKind.MEMS_ACCELEROMETER, quantity=Quantity.ACCELERATION)])
    p = tmp_path / "dump.bin"
    p.write_bytes(bridge.encode_hello(_hello()) + b"".join(bridge.encode_data(_pkt(i, i * 50)) for i in range(40)))
    m = app.import_bridge(p, "acc")
    assert m.device.backend == "bridge" and m.frames == 2000 and [c.label for c in m.channels] == ["x", "y", "z"]
    a = app.analyze(m.id)
    assert a.channels[0].n_averages >= 1


_ = threading
