"""Storage, recovery, integrity and archive-safety tests (docs/specs/13, 15)."""

import io
import json
import os
import sqlite3
import zipfile

import numpy as np
import pytest

from sonicclue.domain.errors import CaseLockedError, ImportSafetyError, IntegrityError, StorageError
from sonicclue.domain.model import CaptureManifest, ChannelConfig, utcnow
from sonicclue.storage import archive
from sonicclue.storage.migrations import migrate
from sonicclue.storage.store import Workspace
from sonicclue.storage.writer import CaptureWriter, read_chunks


def _ws(tmp_path):
    return Workspace(tmp_path / "ws")


def _write_capture(store, cid="cap-aaaaaa", seconds=2.5, fs=8000.0, nch=2):
    hdr = {"schema_version": "1.0.0", "id": cid, "case_id": store.case.id, "created_utc": utcnow().isoformat(), "source": "live",
           "device": {"backend": "simulated", "name": "x"}, "sample_rate_hz": fs, "sample_format": "float32",
           "channels": [ChannelConfig(index=i, label=f"c{i}").model_dump(mode="json") for i in range(nch)],
           "clock_domain": "x", "context": {}, "software_version": "t", "gaps": [], "quality": []}
    w = CaptureWriter(store.capture_dir(cid), cid, fs, nch, hdr, chunk_seconds=1.0)
    data = (np.random.default_rng(0).standard_normal((int(seconds * fs), nch)) * 0.1).astype(np.float32)
    for i in range(0, len(data), 1000):
        w.write(data[i : i + 1000])
    return w, data, hdr


def test_create_open_lock_and_reopen(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    cid = st.case.id
    with pytest.raises(CaseLockedError):
        ws.open_case(cid)  # same process, still open
    st.close()
    st2 = ws.open_case(cid)
    assert st2.case.title == "A"
    st2.close()


def test_stale_lock_reclaimed(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    cid = st.case.id
    st.close()
    (ws.case_path(cid) / "case.lock").write_text(json.dumps({"pid": 999999, "host": __import__("socket").gethostname(), "time": 0}))
    ws.open_case(cid).close()


def test_capture_roundtrip_immutable_and_lossless(tmp_path):
    st = _ws(tmp_path).create_case("A")
    w, data, hdr = _write_capture(st)
    chunks = w.close()
    m = CaptureManifest.model_validate({**hdr, "frames": len(data), "chunks": chunks})
    st.save_capture(m)
    back = st.load_capture_data(m, verify=True)
    np.testing.assert_array_equal(back, data)  # float32 bit-exact
    assert len(chunks) == 3
    with pytest.raises(StorageError):
        st.put("capture", m, replace=False)  # immutable
    with pytest.raises(StorageError):
        st.delete("capture", m.id)
    np.testing.assert_array_equal(st.load_capture_data(m, 9000, 12000), data[9000:12000])
    st.close()


def test_verify_detects_tampering_and_missing(tmp_path):
    st = _ws(tmp_path).create_case("A")
    w, data, hdr = _write_capture(st)
    m = CaptureManifest.model_validate({**hdr, "frames": len(data), "chunks": w.close()})
    st.save_capture(m)
    assert st.verify() == []
    p = st.capture_dir(m.id) / m.chunks[1].file
    os.chmod(p, 0o644)
    b = bytearray(p.read_bytes())
    b[-10] ^= 0xFF
    p.write_bytes(bytes(b))
    probs = st.verify()
    assert any("checksum" in x for x in probs)
    with pytest.raises(IntegrityError):
        read_chunks(st.capture_dir(m.id), m.chunks, verify=True)
    # Capture chunks are intentionally read-only. On Windows, deletion of a
    # read-only file fails even when no process has it open. Explicitly make
    # this fixture writable before simulating an externally deleted chunk.
    missing_chunk = st.capture_dir(m.id) / m.chunks[2].file
    os.chmod(missing_chunk, 0o644)
    missing_chunk.unlink()
    assert any("missing" in x for x in st.verify())
    st.close()


def test_crash_recovery_from_journal(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    cid = st.case.id
    w, data, hdr = _write_capture(st, seconds=2.5)
    # simulate crash: no close(), leave a partial file
    (st.capture_dir("cap-aaaaaa") / "chunk_00002.wav.part").write_bytes(b"junk")
    st.close()
    st2 = ws.open_case(cid)
    assert st2.recovered == ["cap-aaaaaa"]
    m = st2.get("capture", "cap-aaaaaa")
    assert m.status == "recovered" and m.frames == 16000  # two complete 1 s chunks kept
    assert {q.code.value for q in m.quality} >= {"recovered_capture", "partial_capture"}
    np.testing.assert_array_equal(st2.load_capture_data(m), data[:16000])
    st2.close()


def test_damaged_document_detected(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    cid = st.case.id
    st.close()
    con = sqlite3.connect(ws.case_path(cid) / "case.db")
    con.execute("UPDATE documents SET json='{\"broken\": true}' WHERE kind='case'")
    con.commit()
    con.close()
    st = ws.open_case(cid)
    assert any("failed validation" in p for p in st.verify())
    with pytest.raises(IntegrityError):
        _ = st.case
    st.close()
    assert ws.list_cases()[0]["title"] == "(unreadable)"


def test_newer_store_version_rejected_and_migration_backup(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    cid = st.case.id
    st.close()
    db = ws.case_path(cid) / "case.db"
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value='99' WHERE key='store_version'")
    con.commit()
    con.close()
    from sonicclue.domain.errors import SchemaVersionError

    with pytest.raises(SchemaVersionError):
        ws.open_case(cid)
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value='1' WHERE key='store_version'")
    con.commit()
    con.close()
    bak = migrate(db, 1)  # no-op migration still makes a backup first
    assert bak.exists()


def test_archive_roundtrip(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    w, data, hdr = _write_capture(st)
    m = CaptureManifest.model_validate({**hdr, "frames": len(data), "chunks": w.close()})
    st.save_capture(m)
    out = tmp_path / "a.scarchive"
    man = archive.export_case(st, out)
    cid = st.case.id
    st.close()
    ws2 = Workspace(tmp_path / "ws2")
    assert archive.import_case(out, ws2) == cid
    st2 = ws2.open_case(cid)
    assert st2.verify() == []
    np.testing.assert_array_equal(st2.load_capture_data(st2.get("capture", m.id)), data)
    st2.close()
    assert len(man.entries) >= 4
    with pytest.raises(StorageError):
        archive.import_case(out, ws2)  # exists


def _zip(tmp_path, entries: dict, name="bad.zip", manifest=True):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return p


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "captures\\x.wav", "C:/x", "other/x"])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    p = _zip(tmp_path, {name: b"x", "archive.json": b"{}"})
    with pytest.raises(ImportSafetyError):
        archive.import_case(p, _ws(tmp_path))


def test_archive_rejects_bomb_symlink_and_mismatch(tmp_path):
    ws = _ws(tmp_path)
    p = _zip(tmp_path, {"captures/x.bin": b"\0" * 5_000_000, "archive.json": b"{}"}, "bomb.zip")
    with pytest.raises(ImportSafetyError, match="compression"):
        archive.import_case(p, ws)
    p2 = tmp_path / "link.zip"
    with zipfile.ZipFile(p2, "w") as z:
        zi = zipfile.ZipInfo("captures/l")
        zi.external_attr = (0o120777 << 16)
        z.writestr(zi, "/etc/passwd")
        z.writestr("archive.json", "{}")
    with pytest.raises(ImportSafetyError, match="symlink"):
        archive.import_case(p2, ws)
    p3 = _zip(tmp_path, {"case.db": b"x", "archive.json": b"{\"broken\": 1}"}, "m.zip")
    with pytest.raises(ImportSafetyError, match="archive.json"):
        archive.import_case(p3, ws)
    p4 = tmp_path / "notzip.scarchive"
    p4.write_bytes(b"not a zip")
    with pytest.raises(ImportSafetyError):
        archive.import_case(p4, ws)


def test_archive_rejects_tampered_entry(tmp_path):
    ws = _ws(tmp_path)
    st = ws.create_case("A")
    out = tmp_path / "a.scarchive"
    archive.export_case(st, out)
    st.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(buf, "w") as zout:
        for i in zin.infolist():
            data = zin.read(i.filename)
            if i.filename == "case.db":
                data = data[:-1] + bytes([data[-1] ^ 1])
            zout.writestr(i, data)
    bad = tmp_path / "t.scarchive"
    bad.write_bytes(buf.getvalue())
    with pytest.raises(ImportSafetyError, match="checksum"):
        archive.import_case(bad, Workspace(tmp_path / "ws3"))
    assert not list((tmp_path / "ws3" / "cases").iterdir())  # nothing left behind


def test_paths_with_spaces_and_hash(tmp_path):
    ws = Workspace(tmp_path / "John Smith #1" / "Documents 100%")
    st = ws.create_case("spaces")
    cid = st.case.id
    st.close()
    assert ws.list_cases()[0]["title"] == "spaces"
    ws.open_case(cid).close()
