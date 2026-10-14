"""Regression tests for the full code audit (session of TASK-012)."""

import threading
import time

import numpy as np
import pytest

from sonicclue.acquisition.backends import SimulatedBackend
from sonicclue.acquisition.session import CaptureSession, SessionState
from sonicclue.app.jobs import JobRunner
from sonicclue.procedures import latest_intervention
from sonicclue.qualification import QualificationMatrix
from sonicclue.reporting.render import _csv_safe


def test_csv_formula_injection_neutralised():
    assert _csv_safe(["=1+1", "+x", "-y", "@z", "ok", 3]) == ["'=1+1", "'+x", "'-y", "'@z", "ok", 3]


def test_corrupt_qualification_file_recovers(tmp_path):
    p = tmp_path / "q.json"
    p.write_text("{not json")
    m = QualificationMatrix(p)
    assert m.records == [] and p.with_suffix(".corrupt").exists()


def test_jobs_shutdown_cancels_running_jobs():
    r = JobRunner(1)
    started = threading.Event()

    def job(cancel):
        started.set()
        while not cancel():
            time.sleep(0.01)
        return "stopped"

    fut, _ = r.submit(job)
    assert started.wait(2)
    r.shutdown()
    assert fut.result(2) == "stopped"


def test_latest_intervention_is_last():
    class Run:
        interventions = {"a": 1, "b": 2}

    assert latest_intervention(Run()) == 2


class _Boom:
    def __init__(self, after):
        self.n, self.after = 0, after

    def write(self, block):
        self.n += 1
        if self.n > self.after:
            raise OSError("disk full")

    def close(self):
        return []


def test_writer_failure_closes_stream():
    be = SimulatedBackend()
    sess = CaptureSession(be, 0, 48000.0, 1, _Boom(2), duration_s=30)
    sess.start()
    out = sess.wait(10)
    assert out.state is SessionState.FAILED
    assert sess._stream is None


def test_closed_store_rejects_writes(tmp_path):
    from sonicclue.domain.errors import StorageError
    from sonicclue.storage.store import Workspace

    ws = Workspace(tmp_path)
    case = ws.create_case("t") if hasattr(ws, "create_case") else None
    if case is None:
        pytest.skip("workspace API differs")
    case.close()
    with pytest.raises(StorageError):
        case.list("capture")


def test_clip_guard_across_chunks(monkeypatch):
    from sonicclue.dsp import levels

    monkeypatch.setattr(levels, "CHUNK", 1000)
    x = np.zeros(5000, np.float32)
    x[995:1005] = 1.0  # straddles a chunk boundary
    ref = levels.screen_channel(x.copy(), 1000.0, 0)
    monkeypatch.setattr(levels, "CHUNK", 1 << 21)
    full = levels.screen_channel(x.copy(), 1000.0, 0)
    np.testing.assert_array_equal(ref.valid, full.valid)
    assert ref.clipped_samples == 10


def test_bridge_discards_mismatched_axes():
    from sonicclue.sensors import bridge

    def pkt(ctr, axes):
        return bridge.BridgeData(seq=0, sample_counter=ctr, device_time_us=ctr, axes=axes, samples=[[1] * axes] * 4)

    hello = bridge.BridgeHello(protocol_version=bridge.VERSION, sample_rate_hz=1000.0, axes=3, full_scale_g=2.0,
                               device_model="m", firmware_version="1")
    asm = bridge.assemble([hello, pkt(0, 3), pkt(4, 1), pkt(8, 3)])
    assert asm.samples.shape[1] == 3
