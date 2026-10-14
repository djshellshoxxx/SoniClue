"""Portable case archives (.scarchive, a zip) with safe import.

Export: a consistent DB snapshot, the capture chunks, derived arrays (optional)
and reports, plus ``archive.json`` (ArchiveManifest) listing every entry's size
and SHA-256.

Import safeguards (untrusted input, docs/specs/15-security-and-licensing.md section 4):
* archive file size <= limits.max_archive_bytes
* entry count <= limits.max_entries
* every name is relative, uses '/', has no '..', no drive letter, no
  backslash, no NUL, and sits under an allowed top-level folder
* no symlinks (zip external attributes) and no directories with data
* per-entry uncompressed size <= max_entry_bytes, total <= max_total_bytes,
  compression ratio <= max_ratio (zip-bomb defence)
* archive.json must validate, list exactly the entries present, and every
  SHA-256 must match after extraction
* extraction goes to a temporary directory; the database is opened read-only,
  integrity-checked, and every document re-validated before the case is moved
  into the workspace atomically (rename)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .. import __version__
from ..domain.errors import ImportSafetyError, StorageError
from ..domain.model import ArchiveEntry, ArchiveManifest, dump_json, utcnow
from .files import sha256_file
from .store import CaseStore, Workspace, sqlite_uri

ALLOWED_TOP = {"case.db", "captures", "derived", "reports", "archive.json"}


@dataclass(frozen=True)
class ImportLimits:
    max_archive_bytes: int = 8 * 1024**3
    max_total_bytes: int = 16 * 1024**3
    max_entry_bytes: int = 4 * 1024**3
    max_entries: int = 50000
    max_ratio: float = 200.0


def export_case(store: CaseStore, out_path: Path, include_derived: bool = True) -> ArchiveManifest:
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "case.db"
        store.snapshot_db(snap)
        files: list[tuple[str, Path]] = [("case.db", snap)]
        for sub in ("captures", "reports") + (("derived",) if include_derived else ()):
            for p in sorted((store.path / sub).rglob("*")):
                if p.is_file() and not p.name.endswith((".part", ".tmp")) and not any(part.startswith(".") for part in p.relative_to(store.path).parts):
                    files.append((p.relative_to(store.path).as_posix(), p))
        entries = [ArchiveEntry(path=a, size=p.stat().st_size, sha256=sha256_file(p)) for a, p in files]
        man = ArchiveManifest(case_id=store.case.id, created_utc=utcnow(), software_version=__version__, entries=entries)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("archive.json", dump_json(man))
            for arc, p in files:
                z.write(p, arc)
        tmp.replace(out_path)
    store.audit("archive.export", out_path.name, f"{len(entries)} entries")
    return man


def _check_name(name: str) -> None:
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or ":" in name:
        raise ImportSafetyError(f"unsafe path in archive: {name!r}")
    parts = PurePosixPath(name).parts
    if ".." in parts or parts[0] not in ALLOWED_TOP:
        raise ImportSafetyError(f"unexpected path in archive: {name!r}")


def import_case(archive: Path, workspace: Workspace, limits: ImportLimits = ImportLimits()) -> str:
    archive = Path(archive)
    if archive.stat().st_size > limits.max_archive_bytes:
        raise ImportSafetyError("archive exceeds the maximum allowed size")
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise ImportSafetyError("not a valid archive (zip structure damaged)") from None
    with z:
        infos = z.infolist()
        if len(infos) > limits.max_entries:
            raise ImportSafetyError("archive has too many entries")
        total = 0
        for i in infos:
            _check_name(i.filename)
            mode = (i.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ImportSafetyError(f"symlink in archive: {i.filename}")
            if i.is_dir():
                continue
            if i.file_size > limits.max_entry_bytes:
                raise ImportSafetyError(f"entry too large: {i.filename}")
            if i.compress_size and i.file_size / i.compress_size > limits.max_ratio:
                raise ImportSafetyError(f"suspicious compression ratio for {i.filename}")
            total += i.file_size
            if total > limits.max_total_bytes:
                raise ImportSafetyError("archive expands beyond the allowed total size")
        try:
            man = ArchiveManifest.model_validate_json(z.read("archive.json"))
        except KeyError:
            raise ImportSafetyError("archive.json missing") from None
        except Exception as exc:  # noqa: BLE001
            raise ImportSafetyError(f"archive.json invalid: {str(exc).splitlines()[0]}") from None
        names = {i.filename for i in infos if not i.is_dir()} - {"archive.json"}
        listed = {e.path for e in man.entries}
        if names != listed:
            raise ImportSafetyError(f"archive contents do not match archive.json ({len(names ^ listed)} differences)")
        for e in man.entries:
            _check_name(e.path)
        dest = workspace.case_path(man.case_id)
        if dest.exists():
            raise StorageError(f"case {man.case_id} already exists in this workspace", code="SC_CASE_EXISTS")
        tmpdir = Path(tempfile.mkdtemp(prefix=".import-", dir=str(workspace.root / "cases")))
        try:
            for e in man.entries:
                target = tmpdir / e.path
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(e.path) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                if target.stat().st_size != e.size or sha256_file(target) != e.sha256:
                    raise ImportSafetyError(f"checksum mismatch for {e.path}")
            conn = sqlite3.connect(sqlite_uri(tmpdir / "case.db", readonly=True), uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ImportSafetyError("database in archive is damaged")
            except sqlite3.DatabaseError:
                raise ImportSafetyError("database in archive is not readable") from None
            finally:
                conn.close()
            st = CaseStore(tmpdir)
            try:
                problems = st.verify()
                if st.case.id != man.case_id:
                    problems.append("case id mismatch")
            finally:
                st.close()
            if problems:
                raise ImportSafetyError("archive failed verification: " + "; ".join(problems[:5]))
            tmpdir.rename(dest)
        except BaseException:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
    with workspace.open_case(man.case_id) as s:
        s.audit("archive.import", archive.name, json.dumps({"entries": len(man.entries), "from": man.software_version}))
    return man.case_id
