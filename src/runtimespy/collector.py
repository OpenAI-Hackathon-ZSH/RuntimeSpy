"""Low-overhead line-event collection using CPython sys.monitoring."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from types import CodeType
from typing import Mapping

from .config import RuntimeSpyConfig
from .scope import ScopeMatcher


LineKey = tuple[str, int]


class RuntimeSpy:
    """Collect line execution counts for files inside a configured scope."""

    def __init__(
        self,
        config: RuntimeSpyConfig | None = None,
        *,
        include: list[str] | tuple[str, ...] | None = None,
        exclude: list[str] | tuple[str, ...] | None = None,
        source: list[str] | tuple[str, ...] | None = None,
    ):
        if config is None:
            from .config import load_config

            config = load_config()
        if source is not None or include is not None or exclude is not None:
            config = RuntimeSpyConfig(
                project_root=config.project_root,
                source=tuple(source or config.source),
                include_modules=tuple(include or config.include_modules),
                exclude_modules=tuple(exclude or config.exclude_modules),
                exclude_paths=config.exclude_paths,
                data_file=config.data_file,
            )
        self.config = config
        self.scope = ScopeMatcher(config)
        self._hits: Counter[LineKey] = Counter()
        self._code_cache: dict[CodeType, str | None] = {}
        self._tool_id: int | None = None
        self._running = False

    @property
    def hits(self) -> Mapping[LineKey, int]:
        return dict(self._hits)

    def execution_count(self, file: str, line: int) -> int:
        return self._hits[(file, line)]

    def _claim_tool_id(self) -> int:
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None:
            raise RuntimeError("RuntimeSpy requires CPython 3.12 or newer")
        for tool_id in (3, 4):
            if monitoring.get_tool(tool_id) is None:
                monitoring.use_tool_id(tool_id, "runtimespy")
                return tool_id
        raise RuntimeError("no sys.monitoring tool ID is available (tried IDs 3 and 4)")

    def _line_callback(self, code: CodeType, line_number: int) -> None:
        relative = self._code_cache.get(code, ...)
        if relative is ...:
            filename = code.co_filename
            if not filename or filename.startswith("<"):
                relative = None
            else:
                decision = self.scope.decide(Path(filename))
                relative = decision.relative_path if decision.included else None
            self._code_cache[code] = relative
        if relative is not None:
            self._hits[(relative, line_number)] += 1

    def start(self) -> "RuntimeSpy":
        if self._running:
            raise RuntimeError("RuntimeSpy collector is already running")
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None:
            raise RuntimeError("RuntimeSpy requires CPython 3.12 or newer")
        tool_id = self._claim_tool_id()
        try:
            monitoring.register_callback(
                tool_id, monitoring.events.LINE, self._line_callback
            )
            monitoring.set_events(tool_id, monitoring.events.LINE)
        except BaseException:
            monitoring.free_tool_id(tool_id)
            raise
        self._tool_id = tool_id
        self._running = True
        return self

    def stop(self) -> None:
        if not self._running or self._tool_id is None:
            return
        monitoring = sys.monitoring
        tool_id = self._tool_id
        try:
            monitoring.set_events(tool_id, monitoring.events.NO_EVENTS)
            monitoring.register_callback(tool_id, monitoring.events.LINE, None)
        finally:
            monitoring.free_tool_id(tool_id)
            self._tool_id = None
            self._running = False

    def __enter__(self) -> "RuntimeSpy":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

