"""Case-store migrations (docs/specs/13-storage-and-project-format.md section 6).

STORE_VERSION is the layout version of case.db. Before any migration the
database is copied to ``case.db.bak-v<old>-<timestamp>``, so an older
SonicClue build can still open the backup (the rollback path). Migrations run
in one transaction and are idempotent.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

STORE_VERSION = 1

# from_version -> function(conn). Version 1 is the first release, so the table is empty.
MIGRATIONS: dict[int, callable] = {}


def migrate(db: Path, from_version: int) -> Path:
    backup = db.with_name(f"{db.name}.bak-v{from_version}-{int(time.time())}")
    shutil.copy2(db, backup)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("BEGIN IMMEDIATE")
        v = from_version
        while v < STORE_VERSION:
            fn = MIGRATIONS.get(v)
            if fn is None:
                raise RuntimeError(f"no migration from store v{v}")
            fn(conn)
            v += 1
        conn.execute("UPDATE meta SET value=? WHERE key='store_version'", (str(STORE_VERSION),))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return backup
