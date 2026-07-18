"""SQLite persistence for source snapshots and cumulative line counters."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

from .analysis import SourceSnapshot
from .collector import LineKey


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    command TEXT NOT NULL,
    context TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    python_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    path TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    source TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    executable_lines TEXT NOT NULL,
    parse_error TEXT
);

CREATE TABLE IF NOT EXISTS line_hits (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (run_id, path, line)
);

CREATE TABLE IF NOT EXISTS line_totals (
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (path, line)
);
"""


@dataclass(frozen=True, slots=True)
class StoredSource:
    path: str
    module: str
    source: str
    executable_lines: tuple[int, ...]
    parse_error: str | None
    hits: dict[int, int]


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: int
    started_at: str
    command: str
    context: str
    exit_code: int


class Storage:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        return connection

    def record_run(
        self,
        *,
        started_at: str,
        duration_seconds: float,
        command: str,
        context: str,
        exit_code: int,
        python_version: str,
        hits: Mapping[LineKey, int],
        sources: Iterable[SourceSnapshot],
    ) -> int:
        source_list = list(sources)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (
                    started_at, duration_seconds, command, context, exit_code, python_version
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    duration_seconds,
                    command,
                    context,
                    exit_code,
                    python_version,
                ),
            )
            run_id = int(cursor.lastrowid)

            current_paths = {item.path for item in source_list}
            stored_paths = {
                row[0] for row in connection.execute("SELECT path FROM source_files")
            }
            for stale_path in stored_paths - current_paths:
                connection.execute("DELETE FROM source_files WHERE path = ?", (stale_path,))
                connection.execute("DELETE FROM line_totals WHERE path = ?", (stale_path,))

            for item in source_list:
                previous = connection.execute(
                    "SELECT content_hash FROM source_files WHERE path = ?", (item.path,)
                ).fetchone()
                if previous is not None and previous[0] != item.content_hash:
                    connection.execute("DELETE FROM line_totals WHERE path = ?", (item.path,))
                connection.execute(
                    """
                    INSERT INTO source_files (
                        path, module, source, content_hash, executable_lines, parse_error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        module = excluded.module,
                        source = excluded.source,
                        content_hash = excluded.content_hash,
                        executable_lines = excluded.executable_lines,
                        parse_error = excluded.parse_error
                    """,
                    (
                        item.path,
                        item.module,
                        item.source,
                        item.content_hash,
                        json.dumps(item.executable_lines),
                        item.parse_error,
                    ),
                )

            for (path, line), count in hits.items():
                connection.execute(
                    "INSERT INTO line_hits (run_id, path, line, count) VALUES (?, ?, ?, ?)",
                    (run_id, path, line, count),
                )
                connection.execute(
                    """
                    INSERT INTO line_totals (path, line, count) VALUES (?, ?, ?)
                    ON CONFLICT(path, line) DO UPDATE SET count = count + excluded.count
                    """,
                    (path, line, count),
                )
        return run_id

    def load_sources(self) -> list[StoredSource]:
        if not self.path.is_file():
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT path, module, source, executable_lines, parse_error
                FROM source_files ORDER BY path
                """
            ).fetchall()
            totals: dict[str, dict[int, int]] = {}
            for path, line, count in connection.execute(
                "SELECT path, line, count FROM line_totals"
            ):
                totals.setdefault(path, {})[int(line)] = int(count)
        return [
            StoredSource(
                path=row[0],
                module=row[1],
                source=row[2],
                executable_lines=tuple(json.loads(row[3])),
                parse_error=row[4],
                hits=totals.get(row[0], {}),
            )
            for row in rows
        ]

    def latest_run(self) -> RunSummary | None:
        if not self.path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, started_at, command, context, exit_code
                FROM runs ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        return RunSummary(*row) if row is not None else None
