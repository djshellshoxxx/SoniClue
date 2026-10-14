"""Regression tests for the full code audit (session of TASK-012)."""

import json
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
