"""Case store: one directory per case.

    <case_dir>/
      case.db            SQLite (WAL, synchronous=FULL): documents + audit log
      case.lock          exclusive lock (pid, host, time); stale locks are reclaimed
      captures/<id>/     immutable chunk WAVs + journal.json (+ manifest.json copy)
      derived/<id>.npz   analysis arrays (re-creatable from captures)
      reports/           rendered reports

Documents are stored as validated JSON in a single ``documents`` table
(kind, id, parent, json, created). Every load re-validates against the
pydantic contracts, so a damaged or hand-edited database is detected instead
of propagating bad data.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, TypeVar

import numpy as np
from pydantic import BaseModel
from pydantic import ValidationError as PydValidationError

from .. import __version__
from ..domain.errors import CaseLockedError, IntegrityError, SchemaVersionError, StorageError, ValidationError
from ..domain.model import (
    AnalysisResult,
    Annotation,
    CalibrationProfile,
    Case,
    CaptureManifest,
    ChunkRef,
    ClockMapping,
    ComparisonResult,
    DiagnosisSnapshot,
    ProcedureRun,
    QualityCode,
    QualityFlag,
    ReportDocument,
    Severity,
    dump_json,
    utcnow,
)
from .files import atomic_write_text, rmtree_force, sha256_file
from .migrations import STORE_VERSION, migrate
from .writer import CaptureWriter, read_chunks

T = TypeVar("T", bound=BaseModel)

KINDS: dict[str, type[BaseModel]] = {
    "case": Case,
    "capture": CaptureManifest,
    "calibration": CalibrationProfile,
    "analysis": AnalysisResult,
    "comparison": ComparisonResult,
    "procedure_run": ProcedureRun,
    "diagnosis": DiagnosisSnapshot,
    "report": ReportDocument,
    "clock_mapping": ClockMapping,
    "annotation": Annotation,
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    kind TEXT NOT NULL, id TEXT NOT NULL, parent TEXT, json TEXT NOT NULL, created TEXT NOT NULL,
    PRIMARY KEY (kind, id));
CREATE INDEX IF NOT EXISTS documents_parent ON documents(kind, parent);
CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL,
    target TEXT NOT NULL, detail TEXT NOT NULL);
"""

LOCK_STALE_S = 12 * 3600


def sqlite_uri(path: Path, readonly: bool = False) -> str:
    """SQLite URI for a filesystem path. Percent-encodes characters that are special
    in URIs (spaces, '#', '?', '%'), which occur in Windows profile paths."""
    from urllib.parse import quote

    return "file:" + quote(Path(path).as_posix(), safe="/:") + ("?mode=ro" if readonly else "")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class CaseStore:
    """Open case. Thread-safe for concurrent readers and writers in one process
    (one SQLite connection per thread; writes are serialised by a lock)."""

    def __init__(self, path: Path, *, create: bool = False, case: Case | None = None, readonly: bool = False):
        self.path = Path(path)
        self.readonly = readonly
        if create:
            if self.path.exists() and any(self.path.iterdir()):
                raise StorageError(f"case directory {self.path} already exists", code="SC_CASE_EXISTS")
            self.path.mkdir(parents=True, exist_ok=True)
        elif not (self.path / "case.db").exists():
            raise StorageError(f"{self.path} is not a SonicClue case", code="SC_NOT_A_CASE")
        self._local = threading.local()
        self._wlock = threading.RLock()
        self._locked = False
        if not readonly:
            self._acquire_lock()
        try:
            for d in ("captures", "derived", "reports"):
                (self.path / d).mkdir(exist_ok=True)
            conn = self._conn()
            if create:
                with self._tx() as c:
                    c.executescript(SCHEMA_SQL)
                    c.execute("INSERT INTO meta VALUES ('store_version', ?)", (str(STORE_VERSION),))
                    c.execute("INSERT INTO meta VALUES ('created_by', ?)", (__version__,))
                if case is None:
                    raise StorageError("create=True requires a Case")
                self.put("case", case)
                self.audit("case.create", case.id, case.title)
            else:
                ver = int(conn.execute("SELECT value FROM meta WHERE key='store_version'").fetchone()[0])
                if ver > STORE_VERSION:
                    raise SchemaVersionError(f"case was written by a newer SonicClue (store v{ver}); upgrade required")
                if ver < STORE_VERSION:
                    if readonly:
                        raise SchemaVersionError("case needs migration; open read-write to migrate")
                    self.close_connections()
                    migrate(self.path / "case.db", ver)
            if not readonly:  # spools orphaned by a crashed analysis
                for d in (self.path / "derived").glob(".sc-spool-*"):
                    shutil.rmtree(d, ignore_errors=True)
            self.recovered = [] if readonly else self.recover()
        except BaseException:
            self.close()
            raise

    # ---------------- locking ----------------
    def _acquire_lock(self) -> None:
        lock = self.path / "case.lock"
        info = {"pid": os.getpid(), "host": socket.gethostname(), "time": time.time()}
        for _ in range(2):
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as fh:
                    json.dump(info, fh)
                self._locked = True
                return
            except FileExistsError:
                try:
                    cur = json.loads(lock.read_text() or "{}")
                except (OSError, ValueError):
                    cur = {}
                same_host = cur.get("host") == info["host"]
                stale = (same_host and not _pid_alive(int(cur.get("pid", -1)))) or \
                        (time.time() - float(cur.get("time", 0)) > LOCK_STALE_S)
                if cur.get("pid") == info["pid"] and same_host:
                    raise CaseLockedError("case is already open in this process") from None
                if stale:
                    try:
                        lock.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                raise CaseLockedError(f"case is open in another SonicClue instance (pid {cur.get('pid')} on {cur.get('host')})") from None
        raise CaseLockedError("could not acquire case lock")

    def close(self) -> None:
        self._closed = True
        self.close_connections()
        if self._locked:
            try:
                (self.path / "case.lock").unlink()
            except FileNotFoundError:
                pass
            self._locked = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------- sqlite ----------------
    _closed = False

    def _conn(self) -> sqlite3.Connection:
        if self._closed:
            raise StorageError("case is closed")
        c = getattr(self._local, "conn", None)
        if c is None:
            uri = sqlite_uri(self.path / "case.db", self.readonly)
            c = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
            if not self.readonly:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
            conns = getattr(self, "_all_conns", [])
            conns.append(c)
            self._all_conns = conns
        return c

    def close_connections(self) -> None:
        for c in getattr(self, "_all_conns", []):
            try:
                c.close()
            except sqlite3.Error:
                pass
        self._all_conns = []
        self._local = threading.local()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise StorageError("case opened read-only", code="SC_READONLY")
        with self._wlock:
            c = self._conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise

    # ---------------- documents ----------------
    def put(self, kind: str, doc: BaseModel, parent: str | None = None, *, replace: bool = True) -> None:
        model = KINDS[kind]
        if not isinstance(doc, model):
            raise ValidationError(f"{kind} expects {model.__name__}")
        doc_id = getattr(doc, "id")
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        with self._tx() as c:
            try:
                c.execute(f"{verb} INTO documents (kind, id, parent, json, created) VALUES (?,?,?,?,?)",
                          (kind, doc_id, parent, dump_json(doc), utcnow().isoformat()))
            except sqlite3.IntegrityError:
                raise StorageError(f"{kind} {doc_id} already exists (immutable)", code="SC_IMMUTABLE") from None

    def get(self, kind: str, doc_id: str) -> BaseModel | None:
        row = self._conn().execute("SELECT json FROM documents WHERE kind=? AND id=?", (kind, doc_id)).fetchone()
        return self._parse(kind, row[0]) if row else None

    def list(self, kind: str, parent: str | None = None) -> list:
        q = "SELECT json FROM documents WHERE kind=?" + (" AND parent=?" if parent else "") + " ORDER BY created, rowid"
        args = (kind, parent) if parent else (kind,)
        return [self._parse(kind, r[0]) for r in self._conn().execute(q, args).fetchall()]

    def delete(self, kind: str, doc_id: str) -> None:
        if kind == "capture":
            raise StorageError("original captures are immutable and cannot be deleted from a case", code="SC_IMMUTABLE")
        with self._tx() as c:
            c.execute("DELETE FROM documents WHERE kind=? AND id=?", (kind, doc_id))

    @staticmethod
    def _parse(kind: str, text: str):
        try:
            return KINDS[kind].model_validate_json(text)
        except PydValidationError as exc:
            msg = str(exc)
            if "schema_version" in msg:
                raise SchemaVersionError(f"{kind}: {msg.splitlines()[0]}") from None
            raise IntegrityError(f"stored {kind} failed validation: {exc.errors()[0]['msg']}") from None

    def audit(self, action: str, target: str, detail: str = "") -> None:
        with self._tx() as c:
            c.execute("INSERT INTO audit (ts, action, target, detail) VALUES (?,?,?,?)",
                      (utcnow().isoformat(), action, target, detail[:4000]))

    def audit_log(self, limit: int = 1000) -> list[dict]:
        rows = self._conn().execute("SELECT seq, ts, action, target, detail FROM audit ORDER BY seq DESC LIMIT ?", (limit,))
        return [dict(zip(("seq", "ts", "action", "target", "detail"), r)) for r in rows.fetchall()]

    # ---------------- case ----------------
    @property
    def case(self) -> Case:
        cases = self.list("case")
        if len(cases) != 1:
            raise IntegrityError(f"case store holds {len(cases)} case documents (expected 1)")
        return cases[0]

    def update_case(self, **changes) -> Case:
        new = self.case.model_copy(update={**changes, "updated_utc": utcnow()})
        new = Case.model_validate(new.model_dump())  # re-validate after update
        self.put("case", new)
        self.audit("case.update", new.id, ",".join(changes))
        return new

    # ---------------- captures ----------------
    def capture_dir(self, capture_id: str) -> Path:
        return self.path / "captures" / capture_id

    def new_capture_writer(self, capture_id: str, sample_rate: float, channels: int, header: dict) -> CaptureWriter:
        return CaptureWriter(self.capture_dir(capture_id), capture_id, sample_rate, channels, header)

    def save_capture(self, manifest: CaptureManifest) -> None:
        d = self.capture_dir(manifest.id)
        atomic_write_text(d / "manifest.json", dump_json(manifest))
        self.put("capture", manifest, parent=manifest.case_id, replace=False)
        self.audit("capture.add", manifest.id, f"{manifest.source} {manifest.duration_s:.1f}s {manifest.context.condition_label}")

    def load_capture_data(self, manifest: CaptureManifest, start: int = 0, stop: int | None = None,
                          verify: bool = False) -> np.ndarray:
        d = read_chunks(self.capture_dir(manifest.id), manifest.chunks, start, stop, verify)
        if d.shape[0] == 0:
            return np.zeros((0, len(manifest.channels)), np.float32)
        return d

    # ---------------- derived ----------------
    def save_analysis(self, result: AnalysisResult, arrays: dict[str, np.ndarray]) -> AnalysisResult:
        if arrays:
            name = f"{result.id}.npz"
            tmp = self.path / "derived" / f".{name}.tmp.npz"
            np.savez_compressed(tmp, **arrays)
            os.replace(tmp, self.path / "derived" / name)
            result = result.model_copy(update={"arrays_file": name})
        self.put("analysis", result, parent=result.capture_id)
        self.audit("analysis.add", result.id, f"capture {result.capture_id} alg {result.algorithm_version}")
        return result

    def load_arrays(self, result: AnalysisResult) -> dict[str, np.ndarray]:
        if not result.arrays_file:
            return {}
        p = self.path / "derived" / result.arrays_file
        if not p.exists():
            raise IntegrityError(f"derived arrays {result.arrays_file} missing (re-run analysis)")
        with np.load(p, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}

    def latest_analysis(self, capture_id: str) -> AnalysisResult | None:
        res = self.list("analysis", parent=capture_id)
        return res[-1] if res else None

    # ---------------- integrity & recovery ----------------
    def verify(self) -> list[str]:
        problems = []
        ok = self._conn().execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            problems.append(f"database integrity: {ok}")
        for kind in KINDS:
            try:
                self.list(kind)
            except (IntegrityError, SchemaVersionError) as exc:
                problems.append(str(exc))
        try:
            caps = self.list("capture")
        except (IntegrityError, SchemaVersionError):
            caps = []
        for m in caps:
            d = self.capture_dir(m.id)
            for c in m.chunks:
                p = d / c.file
                if not p.exists():
                    problems.append(f"capture {m.id}: missing {c.file}")
                elif sha256_file(p) != c.sha256:
                    problems.append(f"capture {m.id}: checksum mismatch in {c.file}")
        for a in self.list("analysis") if not problems else []:
            if a.arrays_file and not (self.path / "derived" / a.arrays_file).exists():
                problems.append(f"analysis {a.id}: derived arrays missing (re-run analysis)")
        return problems

    def recover(self) -> list[str]:
        """Rebuild manifests for captures interrupted by a crash (journal without
        a stored manifest). Returns the ids of recovered captures."""
        known = {r[0] for r in self._conn().execute("SELECT id FROM documents WHERE kind='capture'").fetchall()}
        recovered = []
        for d in sorted((self.path / "captures").glob("*")):
            if not d.is_dir() or d.name in known:
                continue
            j = d / "journal.json"
            for part in d.glob("*.part"):
                part.unlink(missing_ok=True)
            if not j.exists():
                continue
            try:
                info = json.loads(j.read_text())
                chunks = [ChunkRef(**c) for c in info["chunks"] if (d / c["file"]).exists()
                          and sha256_file(d / c["file"]) == c["sha256"]]
                # keep only the contiguous verified prefix
                good, pos = [], 0
                for c in chunks:
                    if c.start_frame != pos:
                        break
                    good.append(c)
                    pos += c.frames
                hdr = dict(info["header"])
                quality = [QualityFlag(**q) for q in hdr.pop("quality", [])]
                quality += [
                    QualityFlag(code=QualityCode.RECOVERED_CAPTURE, severity=Severity.WARNING,
                                message=f"recovered after interruption: {pos} frames kept from {len(good)} complete chunks"),
                    QualityFlag(code=QualityCode.PARTIAL_CAPTURE, severity=Severity.WARNING,
                                message="capture ended unexpectedly; the final seconds may be missing"),
                ]
                hdr.update(frames=pos, chunks=[c.model_dump() for c in good], quality=[q.model_dump() for q in quality],
                           status="recovered")
                m = CaptureManifest.model_validate(hdr)
                self.save_capture(m)
                self.audit("capture.recover", m.id, f"{pos} frames")
                recovered.append(m.id)
            except Exception as exc:  # noqa: BLE001 - a broken journal must not prevent opening the case
                self.audit("capture.recover_failed", d.name, str(exc)[:500])
        return recovered

    def snapshot_db(self, dest: Path) -> None:
        """Consistent copy of the database (sqlite online backup API)."""
        dst = sqlite3.connect(str(dest))
        try:
            self._conn().backup(dst)
        finally:
            dst.close()


_CASE_ID_RE = re.compile(r"[A-Za-z0-9_\-]{6,64}")


class Workspace:
    """Root folder holding cases (``cases/``) and ``settings.json``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "cases").mkdir(parents=True, exist_ok=True)

    def case_path(self, case_id: str) -> Path:
        if not _CASE_ID_RE.fullmatch(case_id or ""):
            raise StorageError(f"no such case (invalid id {case_id!r})", code="SC_NOT_FOUND")
        return self.root / "cases" / case_id

    def create_case(self, title: str, **fields) -> CaseStore:
        now = utcnow()
        case = Case(id=new_id("case"), title=title, created_utc=now, updated_utc=now, **fields)
        return CaseStore(self.case_path(case.id), create=True, case=case)

    def open_case(self, case_id: str, readonly: bool = False) -> CaseStore:
        return CaseStore(self.case_path(case_id), readonly=readonly)

    def list_cases(self) -> list[dict]:
        out = []
        for d in sorted((self.root / "cases").iterdir()):
            if not (d / "case.db").exists():
                continue
            try:
                conn = sqlite3.connect(sqlite_uri(d / "case.db", readonly=True), uri=True)
                row = conn.execute("SELECT json FROM documents WHERE kind='case'").fetchone()
                ncap = conn.execute("SELECT COUNT(*) FROM documents WHERE kind='capture'").fetchone()[0]
                conn.close()
                c = Case.model_validate_json(row[0])
                out.append({"id": c.id, "title": c.title, "updated": c.updated_utc.isoformat(), "captures": ncap,
                            "locked": (d / "case.lock").exists(), "error": ""})
            except Exception as exc:  # noqa: BLE001 - show damaged cases instead of hiding them
                out.append({"id": d.name, "title": "(unreadable)", "updated": "", "captures": 0,
                            "locked": False, "error": str(exc)[:200]})
        return out

    def delete_case(self, case_id: str) -> None:
        p = self.case_path(case_id)
        if (p / "case.lock").exists():
            raise CaseLockedError("close the case before deleting it")
        rmtree_force(p)

    @staticmethod
    def iso(dt: datetime) -> str:
        return dt.isoformat()
