"""Shared test fixtures and builders."""

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from sonicclue.domain.model import (  # noqa: E402
    Case,
    CaptureContext,
    CaptureManifest,
    ChannelConfig,
    DeviceInfo,
    Equipment,
    Mounting,
    Placement,
    SensorDescriptor,
    SensorKind,
)
from sonicclue.domain.units import Quantity  # noqa: E402

FS = 48000.0
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def app(tmp_path):
    from sonicclue.app.service import SonicClueApp

    a = SonicClueApp(tmp_path / "ws", sim_speed=50.0)
    yield a
    a.shutdown()


def mic_contact_case(case_id="case-test01"):
    return Case(id=case_id, title="t", created_utc=NOW, updated_utc=NOW,
                equipment=[Equipment(id="pc", name="PC", kind="computer"), Equipment(id="hvac", name="AC", kind="hvac")],
                sensors=[SensorDescriptor(id="mic1", kind=SensorKind.STUDIO_MIC, quantity=Quantity.SOUND_PRESSURE),
                         SensorDescriptor(id="ct1", kind=SensorKind.CONTACT_PICKUP, quantity=Quantity.RELATIVE)])


def make_manifest(n_frames, channels=None, *, cid="cap-000001", fs=FS, state=None, label="", source="live", intervention=None,
                  run=None, step=None, position="P1", mounting=Mounting.STAND, agc="off", gain=30.0):
    chans = channels or [ChannelConfig(index=0, label="mic", sensor_id="mic1", agc=agc, input_gain_db=gain,
                                       placement=Placement(position_id=position, mounting=mounting))]
    return CaptureManifest(id=cid, case_id="case-test01", created_utc=NOW, source=source,
                           device=DeviceInfo(backend="simulated", name="test dev"), sample_rate_hz=fs, channels=chans,
                           frames=n_frames, clock_domain="x", software_version="test",
                           context=CaptureContext(condition_label=label, equipment_state=state or {}, intervention=intervention,
                                                  procedure_run_id=run, procedure_step=step))


def analyzed_item(x, **kw):
    """Run the real pipeline on array x (frames[, ch]) and return a compare.Item."""
    from sonicclue.analysis.pipeline import analyze
    from sonicclue.compare.compare import Item

    data = np.atleast_2d(np.asarray(x, np.float32))
    if data.shape[0] < data.shape[1]:
        data = data.T
    m = make_manifest(data.shape[0], **kw)
    case = mic_contact_case()
    out = analyze(m, data, {s.id: s for s in case.sensors}, {})
    return Item(m, out.result, out.arrays)
