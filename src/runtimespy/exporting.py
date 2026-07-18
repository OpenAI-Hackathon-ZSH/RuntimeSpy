"""Build stable JSON exports from running processes or stored runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Iterable, Mapping, TextIO

from .analysis import SourceSnapshot
from .collector import LineKey
from .config import ConfigError, load_config
from .storage import Storage


EXPORT_SCHEMA_VERSION = 1
DEFAULT_EXPORT_FILE = ".runtimespy/export.json"


class ExportError(RuntimeError):
    pass


def _pid_is_running(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _candidate_roots(start: Path) -> tuple[Path, ...]:
    resolved = start.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    return (resolved, *resolved.parents)


def _read_registries(start: Path) -> list[dict[str, Any]]:
    for root in _candidate_roots(start):
        directory = root / ".runtimespy" / "sessions"
        if not directory.is_dir():
            continue
        registries: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("schema_version") == 1
                and isinstance(value.get("pid"), int)
                and _pid_is_running(value["pid"])
            ):
                registries.append(value)
        return registries
    return []


def _request_snapshot(
    registry: dict[str, Any], *, include_source: bool
) -> dict[str, Any] | None:
    try:
        host = str(registry["host"])
        port = int(registry["port"])
        request = json.dumps(
            {
                "token": registry["token"],
                "action": "snapshot",
                "include_source": include_source,
            },
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        chunks: list[bytes] = []
        with socket.create_connection((host, port), timeout=3.0) as connection:
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            while True:
                chunk = connection.recv(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        response = json.loads(b"".join(chunks).decode("utf-8"))
    except (KeyError, OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    snapshot = response.get("snapshot") if response.get("ok") else None
    return snapshot if isinstance(snapshot, dict) else None


def _merge_live_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    total_events = 0
    for session in snapshots:
        for item in session.get("files", []):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            path = item["path"]
            target = files.setdefault(
                path,
                {
                    "path": path,
                    "module": item.get("module", ""),
                    "content_hash": item.get("content_hash", ""),
                    "executable_lines": item.get("executable_lines", []),
                    "hits": {},
                    "parse_error": item.get("parse_error"),
                },
            )
            if "source" in item and "source" not in target:
                target["source"] = item["source"]
            for line, count in item.get("hits", {}).items():
                numeric_count = int(count)
                target["hits"][str(line)] = target["hits"].get(str(line), 0) + numeric_count
                total_events += numeric_count

    sessions = [
        {
            key: item.get(key)
            for key in (
                "session_id",
                "pid",
                "context",
                "started_at",
                "updated_at",
                "project_root",
            )
        }
        for item in snapshots
    ]
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "active_sessions": sessions,
        "summary": {"files": len(files), "events": total_events},
        "files": [files[path] for path in sorted(files)],
    }


def _find_database(start: Path, registries: list[dict[str, Any]]) -> Path:
    for item in registries:
        database = item.get("database_path")
        if isinstance(database, str) and Path(database).is_file():
            return Path(database)
    try:
        return load_config(start).database_path
    except ConfigError:
        for root in _candidate_roots(start):
            candidate = root / ".runtimespy" / "runtime.db"
            if candidate.is_file():
                return candidate
    raise ExportError("no running RuntimeSpy session or stored runtime database found")


def _stored_export(database: Path, *, include_source: bool) -> dict[str, Any]:
    storage = Storage(database)
    sources = storage.load_sources()
    latest = storage.latest_run()
    files: list[dict[str, Any]] = []
    total_events = 0
    for item in sources:
        hits = {str(line): count for line, count in sorted(item.hits.items())}
        total_events += sum(hits.values())
        file_data: dict[str, Any] = {
            "path": item.path,
            "module": item.module,
            "executable_lines": list(item.executable_lines),
            "hits": hits,
            "parse_error": item.parse_error,
        }
        if include_source:
            file_data["source"] = item.source
        files.append(file_data)
    latest_data = None
    if latest is not None:
        latest_data = {
            "run_id": latest.id,
            "started_at": latest.started_at,
            "command": latest.command,
            "context": latest.context,
            "exit_code": latest.exit_code,
        }
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "stored",
        "latest_run": latest_data,
        "summary": {"files": len(files), "events": total_events},
        "files": files,
    }


def build_export(
    start: Path | str | None = None, *, include_source: bool = False
) -> dict[str, Any]:
    root = Path(start or Path.cwd())
    registries = _read_registries(root)
    snapshots = [
        snapshot
        for registry in registries
        if (snapshot := _request_snapshot(registry, include_source=include_source))
        is not None
    ]
    if snapshots:
        return _merge_live_snapshots(snapshots)
    return _stored_export(
        _find_database(root, registries), include_source=include_source
    )


def _files_for_run(
    sources: Iterable[SourceSnapshot],
    hits: Mapping[LineKey, int],
    *,
    include_source: bool,
) -> tuple[list[dict[str, Any]], int]:
    hits_by_file: dict[str, dict[str, int]] = {}
    for (path, line), count in hits.items():
        hits_by_file.setdefault(path, {})[str(line)] = count
    files: list[dict[str, Any]] = []
    total_events = 0
    for item in sources:
        file_hits = hits_by_file.pop(item.path, {})
        total_events += sum(file_hits.values())
        file_data: dict[str, Any] = {
            "path": item.path,
            "module": item.module,
            "content_hash": item.content_hash,
            "executable_lines": list(item.executable_lines),
            "hits": file_hits,
            "parse_error": item.parse_error,
        }
        if include_source:
            file_data["source"] = item.source
        files.append(file_data)
    return files, total_events


def write_final_export(
    *,
    project_root: Path,
    destination: str | Path = DEFAULT_EXPORT_FILE,
    started_at: str,
    command: str,
    context: str,
    run_id: int,
    exit_code: int,
    sources: Iterable[SourceSnapshot],
    hits: Mapping[LineKey, int],
    include_source: bool = False,
) -> Path:
    files, total_events = _files_for_run(
        sources, hits, include_source=include_source
    )
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "final",
        "session": {
            "run_id": run_id,
            "pid": os.getpid(),
            "context": context,
            "started_at": started_at,
            "command": command,
            "exit_code": exit_code,
        },
        "summary": {"files": len(files), "events": total_events},
        "files": files,
    }
    target = Path(destination)
    if not target.is_absolute():
        target = project_root / target
    written = write_export(payload, target)
    assert written is not None
    return written


def write_export(
    payload: dict[str, Any],
    destination: str | Path,
    *,
    compact: bool = False,
    stream: TextIO | None = None,
) -> Path | None:
    indent = None if compact else 2
    separators = (",", ":") if compact else None
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=indent,
        separators=separators,
    )
    if str(destination) == "-":
        output = stream or sys.stdout
        output.write(content)
        output.write("\n")
        output.flush()
        return None

    path = Path(destination).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path
