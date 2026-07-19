"""Public embedded API for installing RuntimeSpy in a target process."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
import sys
import time
from typing import Iterable

from . import transport
from .analysis import SourceSnapshot, snapshot_scope
from .collector import RequestScope, RuntimeSpy
from .config import (
    DEFAULT_EXCLUDE_PATHS,
    ConfigError,
    RuntimeSpyConfig,
    detect_source_roots,
    load_config,
)
from .exporting import DEFAULT_EXPORT_FILE, write_final_export
from .graph import graph_from_snapshots
from .integrations import install_optional_integrations
from .live import OnDemandSnapshotServer
from .report import write_report
from .storage import Storage


_active_session: RuntimeSession | None = None


def _as_strings(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


@dataclass(slots=True)
class RuntimeRequest:
    """One request-local collection scope owned by a RuntimeSession."""

    session: "RuntimeSession"
    scope: RequestScope
    finished: bool = False
    payload: dict[str, object] | None = None


class RuntimeSession:
    """A running embedded RuntimeSpy collection session.

    Sessions created by :func:`init` are stopped and persisted automatically at
    interpreter exit. Calling :meth:`stop` explicitly is useful in tests and in
    long-running processes that need a precise observation window.
    """

    def __init__(
        self,
        config: RuntimeSpyConfig,
        *,
        context: str,
        endpoint: str | None,
        report: bool | str,
        export_file: str | None,
        serve_export: bool,
    ):
        self.config = config
        self.context = context
        self.endpoint = transport.normalize_endpoint(endpoint)
        self.report = report
        self.collector = RuntimeSpy(config)
        self.sources: tuple[SourceSnapshot, ...] = ()
        self.started_at = datetime.now(timezone.utc)
        self.started_clock = time.perf_counter()
        self.run_id: int | None = None
        self.report_path: Path | None = None
        self.export_path: Path | None = None
        self.snapshot_server = (
            OnDemandSnapshotServer(
                self.collector,
                context=context,
                started_at=self.started_at.isoformat(),
            )
            if serve_export
            else None
        )
        self.export_file = export_file
        self._stopped = False

    @property
    def hits(self):
        return self.collector.hits

    def start(self) -> "RuntimeSession":
        self.collector.start()
        try:
            self.sources = tuple(snapshot_scope(self.collector.scope))
            graph = graph_from_snapshots(self.sources, {}, {}, {})
            transport.send_graph(
                {
                    "schema_version": 2,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "initial",
                    "project": {"roots": [str(self.config.project_root)]},
                    "session": {
                        "pid": os.getpid(),
                        "context": self.context,
                        "started_at": self.started_at.isoformat(),
                        "command": shlex.join([sys.executable, *sys.argv]),
                    },
                    "summary": graph["summary"],
                    "graph": graph,
                },
                endpoint=self.endpoint,
            )
            install_optional_integrations()
            if self.snapshot_server is not None:
                self.snapshot_server.start()
        except BaseException:
            self.collector.stop()
            raise
        return self

    def begin_request(self) -> RuntimeRequest:
        """Begin a concurrency-isolated request counter scope."""

        if self._stopped:
            raise RuntimeError("RuntimeSpy session is already stopped")
        return RuntimeRequest(session=self, scope=self.collector.begin_request())

    def end_request(self, request: RuntimeRequest) -> dict[str, object]:
        """Finish a request and emit only the node counts observed within it."""

        if request.session is not self:
            raise RuntimeError("RuntimeSpy request belongs to a different session")
        if request.finished:
            assert request.payload is not None
            return request.payload

        counts = self.collector.end_request(request.scope)
        graph = graph_from_snapshots(
            self.sources,
            counts.hits,
            counts.starts,
            counts.branches,
        )
        payload: dict[str, object] = {
            "Frequency": [
                {"node": node["id"], "count": node["frequency"]}
                for node in graph["nodes"]
                if node["frequency"] > 0
            ]
        }
        request.finished = True
        request.payload = payload
        transport.send_frequency(payload, endpoint=self.endpoint)
        return payload

    def stop(self, *, exit_code: int = 0) -> int:
        """Stop collection, persist counters, and return the recorded run ID."""

        global _active_session
        if self._stopped:
            assert self.run_id is not None
            return self.run_id

        if self.snapshot_server is not None:
            self.snapshot_server.stop()
        self.collector.stop()
        duration = time.perf_counter() - self.started_clock
        sources = snapshot_scope(self.collector.scope)
        hits = self.collector.hits
        starts = self.collector.starts
        branches = self.collector.branches
        storage = Storage(self.config.database_path)
        command = shlex.join([sys.executable, *sys.argv])
        self.run_id = storage.record_run(
            started_at=self.started_at.isoformat(),
            duration_seconds=duration,
            command=command,
            context=self.context,
            exit_code=exit_code,
            python_version=sys.version,
            hits=hits,
            starts=starts,
            branches=branches,
            sources=sources,
        )
        if self.export_file is not None:
            self.export_path = write_final_export(
                project_root=self.config.project_root,
                destination=self.export_file,
                started_at=self.started_at.isoformat(),
                command=command,
                context=self.context,
                run_id=self.run_id,
                exit_code=exit_code,
                sources=sources,
                hits=hits,
                starts=starts,
                branches=branches,
            )
        if self.report:
            destination = (
                Path(self.report)
                if isinstance(self.report, str)
                else Path(".runtimespy/report.html")
            )
            if not destination.is_absolute():
                destination = self.config.project_root / destination
            self.report_path = write_report(
                storage.load_sources(), storage.latest_run(), destination
            )
        self._stopped = True
        if _active_session is self:
            _active_session = None
        return self.run_id

    def __enter__(self) -> "RuntimeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop(exit_code=1 if exc_type is not None else 0)


def _atexit_stop(session: RuntimeSession) -> None:
    session.stop()


def init(
    *,
    source: str | Iterable[str] | None = None,
    include_modules: str | Iterable[str] | None = None,
    skip_modules: str | Iterable[str] | None = None,
    skip_paths: str | Iterable[str] | None = None,
    project_root: str | Path | None = None,
    data_file: str = ".runtimespy/runtime.db",
    context: str = "runtime",
    endpoint: str | None = None,
    report: bool | str = False,
    export_file: str | None = DEFAULT_EXPORT_FILE,
    serve_export: bool = True,
) -> RuntimeSession:
    """Install RuntimeSpy in the current process and start collecting.

    ``source`` defines the hard filesystem boundary. ``skip_modules`` and
    ``skip_paths`` remove modules or paths inside that boundary. When ``source``
    is omitted, existing RuntimeSpy config is loaded; if none exists, the best
    detected source root is used. When ``endpoint`` is set, startup POSTs the
    complete zero-frequency graph to ``endpoint/report/full_graph`` and each
    completed request POSTs its node counts to ``endpoint/report/node``.
    ``runtimespy export`` requests current counts on demand; process exit writes
    final counts to ``export_file``.

    Example::

        import runtimespy

        runtimespy.init(
            source=["src"],
            endpoint="https://runtime.example/api",
            skip_modules=["my_app.generated.*"],
            report=True,
        )
    """

    global _active_session
    if _active_session is not None:
        raise RuntimeError("RuntimeSpy is already initialized in this process")

    root = Path(project_root or Path.cwd()).resolve()
    source_values = _as_strings(source)
    if not source_values:
        try:
            config = load_config(root)
        except ConfigError:
            detected = detect_source_roots(root)
            if not detected:
                raise ConfigError(
                    "cannot infer a source root; pass runtimespy.init(source=[...])"
                ) from None
            source_values = (detected[0],)
        else:
            source_values = config.source
            if include_modules is None:
                include_modules = config.include_modules
            if skip_modules is None:
                skip_modules = config.exclude_modules
            if skip_paths is None:
                skip_paths = config.exclude_paths
            if data_file == ".runtimespy/runtime.db":
                data_file = config.data_file
            root = config.project_root

    excluded_paths = tuple(
        dict.fromkeys((*DEFAULT_EXCLUDE_PATHS, *_as_strings(skip_paths)))
    )
    config = RuntimeSpyConfig(
        project_root=root,
        source=source_values,
        include_modules=_as_strings(include_modules),
        exclude_modules=_as_strings(skip_modules),
        exclude_paths=excluded_paths,
        data_file=data_file,
    )
    session = RuntimeSession(
        config,
        context=context,
        endpoint=endpoint,
        report=report,
        export_file=export_file,
        serve_export=serve_export,
    ).start()
    _active_session = session
    atexit.register(_atexit_stop, session)
    return session


def shutdown(*, exit_code: int = 0) -> int | None:
    """Stop the active embedded session, if any."""

    if _active_session is None:
        return None
    return _active_session.stop(exit_code=exit_code)


def begin_request() -> RuntimeRequest | None:
    """Begin per-request collection when an embedded session is active."""

    if _active_session is None:
        return None
    return _active_session.begin_request()


def end_request(request: RuntimeRequest | None) -> dict[str, object] | None:
    """Emit one request's node-frequency payload, if collection is active."""

    if request is None:
        return None
    return request.session.end_request(request)
