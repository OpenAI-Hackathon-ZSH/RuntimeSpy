"""Low-overhead line-event collection using CPython sys.monitoring."""

from __future__ import annotations

from collections import Counter
import dis
from pathlib import Path
import sys
from types import CodeType
from typing import Mapping

from .config import RuntimeSpyConfig
from .scope import ScopeMatcher


LineKey = tuple[str, int]
CodeStartKey = tuple[str, str, int]
BranchKey = tuple[str, str, int, int, int, int]


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
        self._starts: Counter[CodeStartKey] = Counter()
        self._branches: Counter[BranchKey] = Counter()
        self._code_cache: dict[CodeType, str | None] = {}
        self._position_cache: dict[CodeType, dict[int, tuple[int, int]]] = {}
        self._branch_events: tuple[int, ...] = ()
        self._tool_id: int | None = None
        self._running = False

    @property
    def hits(self) -> Mapping[LineKey, int]:
        return dict(self._hits)

    @property
    def starts(self) -> Mapping[CodeStartKey, int]:
        return dict(self._starts)

    @property
    def branches(self) -> Mapping[BranchKey, int]:
        return dict(self._branches)

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

    def _relative_for_code(self, code: CodeType) -> str | None:
        relative = self._code_cache.get(code, ...)
        if relative is ...:
            filename = code.co_filename
            if not filename or filename.startswith("<"):
                relative = None
            else:
                decision = self.scope.decide(Path(filename))
                relative = decision.relative_path if decision.included else None
            self._code_cache[code] = relative
        return relative

    def _line_callback(self, code: CodeType, line_number: int) -> None:
        relative = self._relative_for_code(code)
        if relative is not None:
            self._hits[(relative, line_number)] += 1

    def _start_callback(self, code: CodeType, instruction_offset: int) -> None:
        relative = self._relative_for_code(code)
        if relative is not None:
            qualname = code.co_qualname.replace(".<locals>.", ".")
            self._starts[(relative, qualname, code.co_firstlineno)] += 1

    def _positions_for_code(self, code: CodeType) -> dict[int, tuple[int, int]]:
        positions = self._position_cache.get(code)
        if positions is None:
            positions = {}
            for instruction in dis.get_instructions(code):
                position = instruction.positions
                if position is not None and position.lineno is not None:
                    positions[instruction.offset] = (
                        position.lineno,
                        position.col_offset or 0,
                    )
            self._position_cache[code] = positions
        return positions

    def _branch_callback(
        self, code: CodeType, instruction_offset: int, destination_offset: int
    ) -> None:
        relative = self._relative_for_code(code)
        if relative is None:
            return
        positions = self._positions_for_code(code)
        source = positions.get(instruction_offset)
        destination = positions.get(destination_offset)
        if source is None or destination is None:
            return
        qualname = code.co_qualname.replace(".<locals>.", ".")
        self._branches[
            (relative, qualname, source[0], source[1], destination[0], destination[1])
        ] += 1

    def start(self) -> "RuntimeSpy":
        if self._running:
            raise RuntimeError("RuntimeSpy collector is already running")
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None:
            raise RuntimeError("RuntimeSpy requires CPython 3.12 or newer")
        tool_id = self._claim_tool_id()
        if hasattr(monitoring.events, "BRANCH_LEFT"):
            branch_events = (
                monitoring.events.BRANCH_LEFT,
                monitoring.events.BRANCH_RIGHT,
            )
        else:
            branch_events = (monitoring.events.BRANCH,)
        try:
            monitoring.register_callback(
                tool_id, monitoring.events.LINE, self._line_callback
            )
            monitoring.register_callback(
                tool_id, monitoring.events.PY_START, self._start_callback
            )
            for event in branch_events:
                monitoring.register_callback(tool_id, event, self._branch_callback)
            monitoring.set_events(
                tool_id,
                monitoring.events.LINE
                | monitoring.events.PY_START
                | sum(branch_events),
            )
        except BaseException:
            monitoring.free_tool_id(tool_id)
            raise
        self._tool_id = tool_id
        self._branch_events = branch_events
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
            monitoring.register_callback(tool_id, monitoring.events.PY_START, None)
            for event in self._branch_events:
                monitoring.register_callback(tool_id, event, None)
        finally:
            monitoring.free_tool_id(tool_id)
            self._tool_id = None
            self._branch_events = ()
            self._running = False

    def __enter__(self) -> "RuntimeSpy":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
