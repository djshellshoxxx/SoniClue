import hashlib

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from sonicclue.acquisition.backends import SimulatedBackend
from sonicclue.acquisition.multi import DeviceSpec, MultiCaptureSession, align_pair
from sonicclue.acquisition.session import SessionState
from sonicclue.app.service import CaptureSpec
from sonicclue.app.updater import sign_manifest, verify_update
from sonicclue.domain.errors import DeviceError, StateError, ValidationError
from sonicclue.domain.model import ChannelConfig
from test_acquisition import MemSink


def _specs(n=2, bad=None):
    return [DeviceSpec(f"d{i}", SimulatedBackend(), 0, 48000, 1, MemSink()) for i in range(n)]


def test_two_devices_complete_with_exact_frames():
    m = MultiCaptureSession(_specs(), duration_s=0.5)
    m.start()
    out = m.wait(timeout=20)
    assert set(out) == {"d0", "d1"}
    assert all(o.state is SessionState.COMPLETED and o.frames == 24000 for o in out.values())


def test_rejects_single_or_duplicate_devices():
    with pytest.raises(StateError):
        MultiCaptureSession(_specs(1))
    s = _specs()
    s[1].name = "d0"
    with pytest.raises(StateError):
        MultiCaptureSession(s)


def test_start_is_all_or_nothing():
    s = _specs()
    s[1].channels = 99  # unsupported by the simulated device
    m = MultiCaptureSession(s, duration_s=5)
    with pytest.raises(DeviceError):
        m.start()
    assert m.sessions["d0"].state in (SessionState.CANCELLED, SessionState.STOPPING, SessionState.COMPLETED)
    with pytest.raises(StateError):
        m.start()


def test_align_pair_recovers_known_delay():
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(48000 * 6)
    other = np.roll(ref, 240)  # 5 ms
    mapping, _flags, _res = align_pair(ref, 48000, other, 48000, ref_id="a", other_id="b")
    assert abs(abs(mapping.offset_s) - 0.005) < 2e-4


def test_multi_capture_application_persists_and_stores_alignment(app):
    app.create_case("multi-device integration")
    channels = [ChannelConfig(index=0, label="mic", agc="off")]
    specs = [CaptureSpec(channels=channels, duration_s=0.5, backend="simulated", device=0, samplerate=48000)
             for _ in range(2)]
    handle = app.start_multi_capture(specs)
    outcome = handle.finalize(timeout=20)
    assert len(outcome.captures) == 2
    assert all(m.status == "complete" and m.source == "simulated" for m in outcome.captures)
    assert len(app.captures()) == 2
    assert len(outcome.alignments) == 1
    mapping = outcome.alignments[0]["mapping"]
    assert mapping.reference_capture_id == outcome.captures[0].id
    assert mapping.other_capture_id == outcome.captures[1].id
    assert app.store.get("clock_mapping", mapping.id) is not None


def test_multi_capture_start_failure_discards_prepared_streams(app):
    app.create_case("multi-device startup rollback")
    valid = CaptureSpec(channels=[ChannelConfig(index=0, label="mic")], duration_s=3,
                        backend="simulated", device=0, samplerate=48000)
    invalid = CaptureSpec(channels=[ChannelConfig(index=i, label=f"ch{i}") for i in range(4)], duration_s=3,
                          backend="simulated", device=0, samplerate=48000)
    with pytest.raises(DeviceError):
        app.start_multi_capture([valid, invalid])
    assert app.captures() == []
    assert list((app.store.path / "captures").iterdir()) == []


def _bundle(tmp_path, version="0.2.0"):
    (tmp_path / "app.bin").write_bytes(b"payload")
    manifest = {"version": version, "files": {"app.bin": hashlib.sha256(b"payload").hexdigest()}}
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return manifest, sign_manifest(manifest, key), pub


def test_update_valid(tmp_path):
    m, sig, pub = _bundle(tmp_path)
    verify_update(m, sig, pub, tmp_path, current_version="0.1.0")


def test_update_rejections(tmp_path):
    m, sig, pub = _bundle(tmp_path)
    other_pub = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with pytest.raises(ValidationError, match="signature"):
        verify_update(m, sig, other_pub, tmp_path, current_version="0.1.0")
    with pytest.raises(ValidationError, match="downgrade"):
        verify_update(m, sig, pub, tmp_path, current_version="0.2.0")
    (tmp_path / "app.bin").write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="checksum"):
        verify_update(m, sig, pub, tmp_path, current_version="0.1.0")
    (tmp_path / "app.bin").write_bytes(b"payload")
    (tmp_path / "extra.bin").write_bytes(b"x")
    with pytest.raises(ValidationError, match="file set"):
        verify_update(m, sig, pub, tmp_path, current_version="0.1.0")
    m2 = dict(m, version="9.9.9")
    (tmp_path / "extra.bin").unlink()
    with pytest.raises(ValidationError, match="signature"):
        verify_update(m2, sig, pub, tmp_path, current_version="0.1.0")
