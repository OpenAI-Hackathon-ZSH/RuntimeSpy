"""Public embedded API for installing RuntimeSpy in a target process."""

from __future__ import annotations

import atexit
from datetime import datetime, timezone
from pathlib import Path
import shlex
import sys
import time
from typing import Iterable

from .analysis import snapshot_scope
from .collector import RuntimeSpy
from .config import (
    DEFAULT_EXCLUDE_PATHS,
    ConfigError,
    RuntimeSpyConfig,
    detect_source_roots,
    load_config,
)
from .report import write_report
from .storage import Storage


_active_session: RuntimeSession | None = None


def _as_strings(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


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
        report: bool | str,
    ):
        self.config = config
        self.context = context
        self.report = report
        self.collector = RuntimeSpy(config)
        self.started_at = datetime.now(timezone.utc)
        self.started_clock = time.perf_counter()
        self.run_id: int | None = None
        self.report_path: Path | None = None
        self._stopped = False

    @property
    def hits(self):
        return self.collector.hits

    def start(self) -> "RuntimeSession":
        self.collector.start()
        return self

    def stop(self, *, exit_code: int = 0) -> int:
        """Stop collection, persist counters, and return the recorded run ID."""

        global _active_session
        if self._stopped:
            assert self.run_id is not None
            return self.run_id

        self.collector.stop()
        duration = time.perf_counter() - self.started_clock
        sources = snapshot_scope(self.collector.scope)
        storage = Storage(self.config.database_path)
        self.run_id = storage.record_run(
            started_at=self.started_at.isoformat(),
            duration_seconds=duration,
            command=shlex.join([sys.executable, *sys.argv]),
            context=self.context,
            exit_code=exit_code,
            python_version=sys.version,
            hits=self.collector.hits,
            sources=sources,
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
    report: bool | str = False,
) -> RuntimeSession:
    """Install RuntimeSpy in the current process and start collecting.

    ``source`` defines the hard filesystem boundary. ``skip_modules`` and
    ``skip_paths`` remove modules or paths inside that boundary. When ``source``
    is omitted, existing RuntimeSpy config is loaded; if none exists, the best
    detected source root is used.

    Example::

        import runtimespy

        runtimespy.init(
            source=["src"],
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
    session = RuntimeSession(config, context=context, report=report).start()
    _active_session = session
    atexit.register(_atexit_stop, session)
    return session


def shutdown(*, exit_code: int = 0) -> int | None:
    """Stop the active embedded session, if any."""

    if _active_session is None:
        return None
    return _active_session.stop(exit_code=exit_code)

