#!/usr/bin/env python3
"""Detect and mitigate excessive Codex logs_2.sqlite write churn."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any


TRIGGER_NAME = "block_log_inserts"
TRIGGER_SQL = f"""
CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAME}
BEFORE INSERT ON logs
BEGIN
  SELECT RAISE(IGNORE);
END;
"""


def database_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home).expanduser() / "logs_2.sqlite" if codex_home else Path.home() / ".codex" / "logs_2.sqlite"


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def connect(path: Path, read_only: bool) -> sqlite3.Connection:
    if read_only:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(path, timeout=10)


def table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'logs'"
    ).fetchone()
    return row is not None


def trigger_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (TRIGGER_NAME,),
    ).fetchone()
    return row is not None


def snapshot(path: Path) -> dict[str, int]:
    with connect(path, read_only=True) as connection:
        row_count, max_id, estimated_bytes = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(estimated_bytes), 0) FROM logs"
        ).fetchone()
    return {
        "rows": int(row_count),
        "max_id": int(max_id),
        "estimated_bytes": int(estimated_bytes),
        "db_bytes": file_size(path),
        "wal_bytes": file_size(Path(f"{path}-wal")),
        "shm_bytes": file_size(Path(f"{path}-shm")),
    }


def delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: after[key] - before[key] for key in before}


def install(path: Path) -> tuple[bool, list[tuple[int, int, int]]]:
    with connect(path, read_only=False) as connection:
        connection.execute(TRIGGER_SQL)
        connection.commit()
        installed = trigger_exists(connection)
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    return installed, checkpoint


def remove(path: Path) -> tuple[bool, list[tuple[int, int, int]]]:
    with connect(path, read_only=False) as connection:
        connection.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME}")
        connection.commit()
        removed = not trigger_exists(connection)
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    return removed, checkpoint


def emit(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"status: {result['status']}")
    print(f"database: {result['database']}")
    if "delta" in result:
        print(f"delta: {result['delta']}")
    if "message" in result:
        print(result["message"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-seconds", type=float, default=15.0)
    parser.add_argument("--id-threshold", type=int, default=20)
    parser.add_argument("--wal-threshold-bytes", type=int, default=256 * 1024)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = database_path()
    result: dict[str, Any] = {"database": str(path)}

    if args.sample_seconds < 0 or args.id_threshold < 0 or args.wal_threshold_bytes < 0:
        result.update(status="error", message="Thresholds and sample duration must be non-negative.")
        emit(result, args.json)
        return 2

    if not path.is_file():
        result.update(status="not_found", message="Codex log database does not exist.")
        emit(result, args.json)
        return 0

    try:
        with connect(path, read_only=True) as connection:
            if not table_exists(connection):
                result.update(status="no_logs_table", message="The database has no logs table.")
                emit(result, args.json)
                return 0
            protected = trigger_exists(connection)

        if args.remove:
            removed, checkpoint = remove(path)
            result.update(
                status="removed" if removed else "error",
                checkpoint=checkpoint,
                wal_bytes=file_size(Path(f"{path}-wal")),
            )
            emit(result, args.json)
            return 0 if removed else 1

        if protected:
            with connect(path, read_only=False) as connection:
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            result.update(
                status="protected",
                trigger=TRIGGER_NAME,
                checkpoint=checkpoint,
                snapshot=snapshot(path),
            )
            emit(result, args.json)
            return 0

        before = snapshot(path)
        if args.sample_seconds:
            time.sleep(args.sample_seconds)
        after = snapshot(path)
        changes = delta(before, after)
        excessive = args.force or changes["max_id"] >= args.id_threshold or changes["wal_bytes"] >= args.wal_threshold_bytes
        result.update(before=before, after=after, delta=changes, excessive=excessive)

        if not excessive:
            result.update(status="healthy", message="Write churn stayed below configured thresholds.")
            emit(result, args.json)
            return 0

        if args.dry_run:
            result.update(status="problem_detected", message="Excessive write churn detected; no changes made.")
            emit(result, args.json)
            return 0

        installed, checkpoint = install(path)
        result.update(
            status="protected" if installed else "error",
            trigger=TRIGGER_NAME if installed else None,
            checkpoint=checkpoint,
            final_snapshot=snapshot(path),
        )
        emit(result, args.json)
        return 0 if installed else 1
    except (OSError, sqlite3.Error) as error:
        result.update(status="error", message=str(error))
        emit(result, args.json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
