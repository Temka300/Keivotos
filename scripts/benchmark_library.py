"""Read-only benchmark for the Danbooru library queries that scale with size."""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any


CODE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = CODE_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import DATA_DB_PATH, USER_DB_PATH  # noqa: E402


def _query_cases(connection: sqlite3.Connection) -> list[tuple[str, str, tuple[Any, ...]]]:
    folder_row = connection.execute(
        "SELECT folder FROM files WHERE folder IS NOT NULL GROUP BY folder ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()
    tag_row = connection.execute(
        "SELECT tag_id FROM post_tags GROUP BY tag_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()
    folder = folder_row[0] if folder_row else ""
    tag_id = tag_row[0] if tag_row else -1
    return [
        (
            "browse_date_page",
            """SELECT p.id FROM posts p JOIN files f ON f.id=p.file_id
               ORDER BY COALESCE(p.created_at, '') DESC, f.name ASC LIMIT 60""",
            (),
        ),
        (
            "browse_downloaded_page",
            """SELECT p.id FROM posts p JOIN files f ON f.id=p.file_id
               ORDER BY COALESCE(f.downloaded_at, '') DESC, f.name ASC LIMIT 60""",
            (),
        ),
        (
            "rating_date_page",
            """SELECT p.id FROM posts p JOIN files f ON f.id=p.file_id
               WHERE p.rating=? ORDER BY COALESCE(p.created_at, '') DESC, f.name ASC LIMIT 60""",
            ("g",),
        ),
        (
            "folder_downloaded_page",
            """SELECT p.id FROM posts p JOIN files f ON f.id=p.file_id
               WHERE f.folder=? ORDER BY COALESCE(f.downloaded_at, '') DESC, f.name ASC LIMIT 60""",
            (folder,),
        ),
        (
            "popular_tag_page",
            """SELECT p.id FROM post_tags pt JOIN posts p ON p.id=pt.post_id
               JOIN files f ON f.id=p.file_id WHERE pt.tag_id=?
               ORDER BY COALESCE(p.created_at, '') DESC, f.name ASC LIMIT 60""",
            (tag_id,),
        ),
        (
            "tag_counts_first_page",
            """SELECT t.id, COUNT(pt.post_id) AS cnt FROM tags t
               JOIN post_tags pt ON pt.tag_id=t.id GROUP BY t.id
               ORDER BY cnt DESC, t.name ASC LIMIT 100""",
            (),
        ),
        (
            "duplicate_md5_groups",
            """SELECT local_md5, COUNT(*) AS cnt FROM files
               WHERE local_md5 IS NOT NULL AND local_md5<>''
               GROUP BY local_md5 HAVING COUNT(*)>1 ORDER BY cnt DESC LIMIT 100""",
            (),
        ),
        (
            "random_image_current",
            "SELECT id FROM posts ORDER BY RANDOM() LIMIT 1",
            (),
        ),
    ]


def _time_query(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
    rounds: int,
) -> tuple[list[float], int]:
    connection.execute(sql, params).fetchall()  # warm cache and compile the statement
    timings: list[float] = []
    rows = 0
    for _ in range(rounds):
        started = time.perf_counter()
        result = connection.execute(sql, params).fetchall()
        timings.append((time.perf_counter() - started) * 1000)
        rows = len(result)
    return timings, rows


def _quick_check(database: Path) -> str:
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row else "no result"
    finally:
        connection.close()


def benchmark(database: Path, rounds: int, user_database: Path | None = None) -> dict[str, Any]:
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("files", "posts", "tags", "post_tags")
        }
        results = []
        for name, sql, params in _query_cases(connection):
            timings, row_count = _time_query(connection, sql, params, rounds)
            plan = [row[3] for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", params)]
            results.append(
                {
                    "name": name,
                    "median_ms": round(statistics.median(timings), 3),
                    "minimum_ms": round(min(timings), 3),
                    "maximum_ms": round(max(timings), 3),
                    "rows_returned": row_count,
                    "plan": plan,
                }
            )
        return {
            "database": str(database.resolve()),
            "integrity": {
                "library_database": _quick_check(database),
                "user_database": _quick_check(user_database) if user_database and user_database.is_file() else "not found",
            },
            "rounds": rounds,
            "counts": counts,
            "results": results,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATA_DB_PATH)
    parser.add_argument("--user-database", type=Path, default=USER_DB_PATH)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f"database not found: {args.database}")
    report = benchmark(args.database, max(1, min(100, args.rounds)), args.user_database)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    counts = report["counts"]
    print(
        f"Library: {counts['files']:,} files, {counts['tags']:,} tags, "
        f"{counts['post_tags']:,} post-tag links"
    )
    print(f"Database: {report['database']}")
    print(
        "Integrity: library " + report["integrity"]["library_database"]
        + ", user " + report["integrity"]["user_database"]
    )
    print(f"Rounds: {report['rounds']} (warm-cache median)\n")
    for result in report["results"]:
        scan = any("SCAN" in item.upper() and "USING INDEX" not in item.upper() for item in result["plan"])
        marker = "scan" if scan else "indexed"
        print(
            f"{result['name']:<28} {result['median_ms']:>9.3f} ms  "
            f"[{marker}]  min {result['minimum_ms']:.3f} / max {result['maximum_ms']:.3f}"
        )
    print("\nUse --json to retain the full EXPLAIN QUERY PLAN output for before/after comparisons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
