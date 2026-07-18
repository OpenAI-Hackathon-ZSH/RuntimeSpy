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
from .collector import BranchKey, CodeStartKey, LineKey
from .config import ConfigError, load_config
from .graph import graph_from_snapshots, graph_from_stored
from .storage import Storage


EXPORT_SCHEMA_VERSION = 2
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


def _request_snapshot(registry: dict[str, Any]) -> dict[str, Any] | None:
    try:
        host = str(registry["host"])
        port = int(registry["port"])
        request = json.dumps(
            {
                "token": registry["token"],
                "action": "snapshot",
            },
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        chunks: list[bytes] = []
        with socket.create_connection((host, port), timeout=30.0) as connection:
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


def _merge_graphs(graphs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    files: dict[str, dict[str, Any]] = {}
    for graph in graphs:
        for node in graph.get("nodes", []):
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                continue
            node_id = node["id"]
            if node_id not in nodes:
                nodes[node_id] = dict(node)
            else:
                nodes[node_id]["frequency"] += int(node.get("frequency", 0))
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
                continue
            edge_id = edge["id"]
            if edge_id not in edges:
                edges[edge_id] = {
                    **edge,
                    "frequency": int(edge.get("frequency") or 0),
                }
            else:
                edges[edge_id]["frequency"] += int(edge.get("frequency") or 0)
        hierarchy = graph.get("hierarchy", {})
        for item in hierarchy.get("files", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                files.setdefault(item["path"], item)

    node_values = [nodes[node_id] for node_id in sorted(nodes)]
    edge_values = [edges[edge_id] for edge_id in sorted(edges)]
    return {
        "schema_version": 1,
        "type": "control_flow",
        "summary": {
            "nodes": len(node_values),
            "edges": len(edge_values),
            "executed_nodes": sum(
                1 for node in node_values if node.get("frequency", 0) > 0
            ),
            "unseen_nodes": sum(
                1 for node in node_values if node.get("frequency", 0) == 0
            ),
        },
        "hierarchy": {"files": [files[path] for path in sorted(files)]},
        "nodes": node_values,
        "edges": edge_values,
    }


def _merge_live_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    graph = _merge_graphs(
        item["graph"] for item in snapshots if isinstance(item.get("graph"), dict)
    )

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
    project_roots = sorted(
        {
            str(item["project_root"])
            for item in snapshots
            if isinstance(item.get("project_root"), str)
        }
    )
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "project": {"roots": project_roots},
        "active_sessions": sessions,
        "summary": graph["summary"],
        "graph": graph,
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


def _stored_export(database: Path) -> dict[str, Any]:
    storage = Storage(database)
    sources = storage.load_sources()
    latest = storage.latest_run()
    graph = graph_from_stored(sources)
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
        "project": {"roots": [str(database.parent.parent)]},
        "latest_run": latest_data,
        "summary": graph["summary"],
        "graph": graph,
    }


def build_export(start: Path | str | None = None) -> dict[str, Any]:
    root = Path(start or Path.cwd())
    registries = _read_registries(root)
    snapshots = [
        snapshot
        for registry in registries
        if (snapshot := _request_snapshot(registry)) is not None
    ]
    if snapshots:
        return _merge_live_snapshots(snapshots)
    return _stored_export(_find_database(root, registries))


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
    starts: Mapping[CodeStartKey, int],
    branches: Mapping[BranchKey, int],
) -> Path:
    graph = graph_from_snapshots(sources, hits, starts, branches)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "final",
        "project": {"roots": [str(project_root)]},
        "session": {
            "run_id": run_id,
            "pid": os.getpid(),
            "context": context,
            "started_at": started_at,
            "command": command,
            "exit_code": exit_code,
        },
        "summary": graph["summary"],
        "graph": graph,
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
