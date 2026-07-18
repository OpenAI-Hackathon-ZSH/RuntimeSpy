"""On-demand IPC snapshots for running RuntimeSpy processes."""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import socketserver
import threading
from typing import Any
import uuid

from .analysis import snapshot_scope
from .collector import RuntimeSpy


SESSION_SCHEMA_VERSION = 1


class _SnapshotRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        owner: OnDemandSnapshotServer = self.server.owner  # type: ignore[attr-defined]
        try:
            raw = self.rfile.readline(64 * 1024)
            request = json.loads(raw.decode("utf-8"))
            token = request.get("token", "")
            if not isinstance(token, str) or not hmac.compare_digest(token, owner.token):
                response: dict[str, Any] = {"ok": False, "error": "unauthorized"}
            elif request.get("action") != "snapshot":
                response = {"ok": False, "error": "unsupported action"}
            else:
                response = {
                    "ok": True,
                    "snapshot": owner.snapshot(
                        include_source=bool(request.get("include_source", False))
                    ),
                }
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
            response = {"ok": False, "error": str(exc)}
        self.wfile.write(
            json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class OnDemandSnapshotServer:
    """Expose collector state only when an exporter explicitly requests it."""

    def __init__(self, collector: RuntimeSpy, *, context: str, started_at: str):
        self.collector = collector
        self.context = context
        self.started_at = started_at
        self.session_id = uuid.uuid4().hex
        self.token = secrets.token_urlsafe(32)
        self.directory = collector.config.project_root / ".runtimespy" / "sessions"
        self.registry_path = self.directory / f"{os.getpid()}-{self.session_id}.json"
        self._server: _ThreadingServer | None = None
        self._thread: threading.Thread | None = None

    def snapshot(self, *, include_source: bool = False) -> dict[str, Any]:
        hits = self.collector.hits
        hits_by_file: dict[str, dict[str, int]] = {}
        for (path, line), count in hits.items():
            hits_by_file.setdefault(path, {})[str(line)] = count

        files: list[dict[str, Any]] = []
        for item in snapshot_scope(self.collector.scope):
            file_data: dict[str, Any] = {
                "path": item.path,
                "module": item.module,
                "content_hash": item.content_hash,
                "executable_lines": list(item.executable_lines),
                "hits": hits_by_file.pop(item.path, {}),
                "parse_error": item.parse_error,
            }
            if include_source:
                file_data["source"] = item.source
            files.append(file_data)

        for path, file_hits in sorted(hits_by_file.items()):
            files.append(
                {
                    "path": path,
                    "module": "",
                    "content_hash": "",
                    "executable_lines": sorted(int(line) for line in file_hits),
                    "hits": file_hits,
                    "parse_error": None,
                    **({"source": None} if include_source else {}),
                }
            )
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "pid": os.getpid(),
            "context": self.context,
            "started_at": self.started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(self.collector.config.project_root),
            "database_path": str(self.collector.config.database_path),
            "files": files,
        }

    def _write_registry(self, host: str, port: int) -> None:
        payload = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "pid": os.getpid(),
            "host": host,
            "port": port,
            "token": self.token,
            "context": self.context,
            "started_at": self.started_at,
            "project_root": str(self.collector.config.project_root),
            "database_path": str(self.collector.config.database_path),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.registry_path)

    def start(self) -> "OnDemandSnapshotServer":
        server = _ThreadingServer(("127.0.0.1", 0), _SnapshotRequestHandler)
        server.owner = self  # type: ignore[attr-defined]
        host, port = server.server_address
        self._server = server
        self._write_registry(str(host), int(port))
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name=f"runtimespy-export-{self.session_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self.registry_path.unlink(missing_ok=True)
        finally:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
            if self._thread is not None:
                self._thread.join(timeout=2.0)
            self._server = None
            self._thread = None
