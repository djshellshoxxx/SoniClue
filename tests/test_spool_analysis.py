"""TASK-012: spooled (disk-backed) analysis must equal in-memory analysis and clean up after itself."""

import numpy as np
import pytest

from sonicclue.analysis.pipeline import analyze
from sonicclue.analysis.spool import ChannelSpool
from sonicclue.domain.errors import AnalysisError
from sonicclue.domain.model import CaptureManifest, ChannelConfig, DeviceInfo, utcnow
from sonicclue.dsp import levels

FS = 8000.0


def _data(seconds=40, clip=False):
    n = int(seconds * FS)
    t = np.arange(n) / FS
    rng = np.random.default_rng(3)
    a = (0.05 * np.sin(2 * np.pi * 440 * t) + 0.01 * rng.standard_normal(n)).astype(np.float32)
    b = (0.03 * np.sin(2 * np.pi * 440 * t + 0.4) + 0.01 * rng.standard_normal(n)).astype(np.float32)
    if clip:
        a[1000:1010] = 1.0
        a[1020] = np.nan
    return np.stack([a, b], axis=1)


def _manifest(n):
    return CaptureManifest(id="cap-spool1", case_id="c", created_utc=utcnow(), source="live", device=DeviceInfo(backend="file"),
                           sample_rate_hz=FS, channels=[ChannelConfig(index=0, label="a"), ChannelConfig(index=1, label="b")],
                           frames=n, clock_domain="x", software_version="t")


def _dump(r):
    d = r.result.model_dump(mode="json")
    d.pop("id"); d.pop("created_utc")
    return d


@pytest.mark.parametrize("clip", [False, True])
def test_spooled_equals_in_memory(tmp_path, clip):
    x = _data(clip=clip)
    ref = analyze(_manifest(len(x)), x.copy(), {}, {})
    with ChannelSpool(lambda a, b: x[a:b], len(x), 2, tmp_path) as sp:
        out = analyze(_manifest(len(x)), sp, {}, {})
    assert _dump(out) == _dump(ref)
    assert out.arrays.keys() == ref.arrays.keys()
    for k in ref.arrays:
        np.testing.assert_allclose(out.arrays[k], ref.arrays[k], rtol=1e-9, atol=0)


def test_spool_does_not_touch_source_and_cleans_up(tmp_path):
    x = _data(10)
    keep = x.copy()
    with ChannelSpool(lambda a, b: x[a:b], len(x), 2, tmp_path) as sp:
        assert list(tmp_path.iterdir())
        analyze(_manifest(len(x)), sp, {}, {})
    np.testing.assert_array_equal(x, keep)
    assert not list(tmp_path.iterdir())


def test_spool_cleans_up_on_loader_failure(tmp_path):
    def bad(a, b):
        raise RuntimeError("disk read failed")

    with pytest.raises(RuntimeError):
        with ChannelSpool(bad, 100, 1, tmp_path):
            pass
    assert not list(tmp_path.iterdir())


def test_spool_rejects_wrong_block_shape(tmp_path):
    with pytest.raises(AnalysisError):
        with ChannelSpool(lambda a, b: np.zeros((b - a, 3), np.float32), 100, 2, tmp_path):
            pass
    assert not list(tmp_path.iterdir())


def test_spool_rejects_insufficient_disk(tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple

    U = namedtuple("U", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(10, 10, 0))
    with pytest.raises(AnalysisError, match="free disk"):
        with ChannelSpool(lambda a, b: np.zeros((b - a, 1), np.float32), 1000, 1, tmp_path):
            pass


def test_clip_guard_merge_matches_naive():
    n = 5000
    x = np.zeros(n, np.float32)
    for i in (0, 3, 4, 100, 2000, 2001, 4999):
        x[i] = 1.0
    sc = levels.screen_channel(x.copy(), 1000.0, 0)
    g = max(1, int(levels.CLIP_GUARD_S * 1000.0))
    want = np.ones(n, bool)
    for i in np.flatnonzero(np.abs(x) >= levels.CLIP_LEVEL):
        want[max(0, i - g) : min(n, i + g + 1)] = False
    np.testing.assert_array_equal(sc.valid, want)
