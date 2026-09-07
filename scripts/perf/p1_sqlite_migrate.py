"""P1 measurement 1b — SQLite startup cost: connect + schema + migrate.

Mirrors the real per-library open path (AssetsManager/core/database.py:920):
``sqlite3.connect`` -> ``PRAGMA busy_timeout`` -> ``preflight_recorded_version``
-> ``executescript(_SCHEMA)`` -> ``migrate_db(conn)`` -> ``commit``.

Measured on a fresh (cold: migration runs on an empty DB) and a re-opened
(warm: migration is a version check) library file, N runs each, medians.

Evidence: docs/reports/performance-audit-2026-09-06/evidence/p1-sqlite-migrate.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _p1_common import environment, project_root, write_json  # noqa: E402

sys.path.insert(0, str(project_root()))


def one_open(db_path: Path, schema_sql: str) -> dict:
    """One full managed-open sequence against *db_path*, segment-timed."""
    t_connect0 = time.perf_counter()
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    t_connect = time.perf_counter() - t_connect0

    from AssetsManager.core.db_migrations import (
        migrate as migrate_db,
        preflight_recorded_version,
    )

    t_preflight0 = time.perf_counter()
    preflight_recorded_version(conn)
    t_preflight = time.perf_counter() - t_preflight0

    t_schema0 = time.perf_counter()
    conn.executescript(schema_sql)
    t_schema = time.perf_counter() - t_schema0

    t_migrate0 = time.perf_counter()
    migrate_db(conn)
    t_migrate = time.perf_counter() - t_migrate0

    t_commit0 = time.perf_counter()
    conn.commit()
    t_commit = time.perf_counter() - t_commit0
    conn.close()
    return {
        "connect_pragma_ms": t_connect * 1000,
        "preflight_ms": t_preflight * 1000,
        "schema_ms": t_schema * 1000,
        "migrate_ms": t_migrate * 1000,
        "commit_ms": t_commit * 1000,
        "total_ms": (t_connect + t_preflight + t_schema + t_migrate + t_commit) * 1000,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    from AssetsManager.core import database as dbmod

    schema_sql = dbmod._SCHEMA

    cold: list[dict] = []
    warm: list[dict] = []
    tmp = Path(tempfile.mkdtemp(prefix="p1_sqlite_"))
    try:
        for _ in range(args.runs):
            # Cold: brand-new library file each run (migration does real work).
            db = tmp / "cold.db"
            if db.exists():
                db.unlink()
            cold.append(one_open(db, schema_sql))
        # Warm: reopen the last DB (version check only).
        db = tmp / "cold.db"
        for _ in range(args.runs):
            warm.append(one_open(db, schema_sql))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    def summarize(rows: list[dict]) -> dict:
        keys = rows[0].keys()
        return {
            k: {
                "median_ms": round(statistics.median(r[k] for r in rows), 3),
                "min_ms": round(min(r[k] for r in rows), 3),
                "max_ms": round(max(r[k] for r in rows), 3),
            }
            for k in keys
        }

    payload = {
        "measurement": "sqlite-startup-cost",
        "runs": args.runs,
        "cold_fresh_db": summarize(cold),
        "warm_reopen_db": summarize(warm),
        "cold_rows_ms": [{k: round(v, 3) for k, v in r.items()} for r in cold],
        "warm_rows_ms": [{k: round(v, 3) for k, v in r.items()} for r in warm],
        "environment": environment(),
    }
    write_json("p1-sqlite-migrate.json", payload)
    print(json.dumps({k: payload[k] for k in ("cold_fresh_db", "warm_reopen_db")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
