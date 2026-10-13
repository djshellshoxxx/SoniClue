# 13 Storage and project format

Code: `src/sonicclue/storage/` (store, writer, archive, files, migrations). Tests: `tests/test_storage.py`.

## 1 Workspace

`<workspace>/` (default `Documents/SonicClue`, or `$SONICCLUE_WORKSPACE`, or `--workspace`): `cases/<case_id>/`, `settings.json`, `qualification.json`, `calibrations/*.json` (calibration library). Workspace files are written atomically.

## 2 Case layout

```
cases/<case_id>/
  case.db              SQLite, WAL, synchronous=FULL
  case.lock            {"pid", "host", "time"}  (exclusive; stale if PID dead on same host or > 12 h)
  captures/<cap_id>/   chunk_00000.wav ... (float32 WAV, read-only), journal.json, manifest.json, original.<ext> (imports)
  derived/<an_id>.npz  analysis arrays (re-creatable)
  reports/<rep_id>.*   rendered reports
  case.db.bak-v<N>-<t> migration backups
```

`case.db` tables: `meta(key, value)` (store_version, created_by); `documents(kind, id, parent, json, created)` with kinds case, capture, calibration, analysis, comparison, procedure_run, diagnosis, report, clock_mapping, annotation; `audit(seq, ts, action, target, detail)`.

## 3 Immutability and provenance

Captures are inserted with `replace=False` (SC_IMMUTABLE on overwrite), cannot be deleted from a case, and their chunk files are chmod read-only with a SHA-256 in the manifest. Imports keep `original.<ext>` byte-identical. Analyses reference `capture_id`, `config`, `algorithm_version`, `software_version`, and are append-only (latest used). Comparisons reference capture ids, run id and algorithm version. Diagnoses reference the ruleset version and evidence sources. Reports carry `case_digest` = SHA-256 over the case document and all chunk hashes.

## 4 Consistency mechanisms

* Small files: atomic write (temp in same directory, fsync, `os.replace`, directory fsync).
* Chunks: written as `.part`, renamed, then journaled. Recovery keeps only the contiguous checksum-verified prefix.
* Database: WAL + `synchronous=FULL`; every write in `BEGIN IMMEDIATE … COMMIT` with rollback on error; one connection per thread; writes serialised by an RLock.
* Locking: `O_CREAT|O_EXCL` lock file; same-process reopen refused; stale locks reclaimed.

## 5 Integrity verification

`CaseStore.verify()`: `PRAGMA integrity_check`; every document re-validated against its contract; every chunk exists and matches its SHA-256; derived arrays present. GUI: Verify integrity. CLI: `case verify` (exit 3 on problems). Damaged documents raise SC_INTEGRITY and are shown as "(unreadable)" in the case list rather than hidden.

## 6 Migrations

`STORE_VERSION = 1`. On open: newer → SC_SCHEMA_VERSION (no partial read); older → copy `case.db` to a backup, run registered migrations in one transaction, update meta. The rollback path: older SonicClue builds can open the backup copy. Document schema versioning: spec 04 section 2.

## 7 Portable archives (`.scarchive`)

A zip containing `archive.json` (ArchiveManifest: case id, software version, entries with size and SHA-256), a consistent DB snapshot (SQLite backup API), captures, reports and optionally derived arrays. Import safeguards: archive ≤ 8 GiB; ≤ 50 000 entries; names relative, '/', no '..', no drive letter, no backslash, no NUL, only allowed top-level folders; no symlinks; per-entry ≤ 4 GiB; total ≤ 16 GiB; compression ratio ≤ 200; manifest validates and lists exactly the entries present; every SHA-256 and size matches; DB integrity check; full `verify()` in a temp directory before an atomic rename into the workspace; an existing case id → SC_CASE_EXISTS. All tested with malicious fixtures.

## 8 Annotations, history, before/after

Annotations (user assertions) are documents with a target id. History = audit log plus all diagnosis snapshots. Before/after comparisons are stored documents.

## 9 Size estimates

Float32 per channel: 192 kB/s at 48 kHz → 0.69 GB per channel-hour. Analysis arrays are typically 1-5 MB per capture.
