"""In-process execution of Python scripts, modules, and pytest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
from pathlib import Path
import runpy
import shlex
import sys
import time
from typing import Sequence

from .analysis import snapshot_scope
from .collector import RuntimeSpy
from .config import RuntimeSpyConfig
from .exporting import write_final_export
from .live import OnDemandSnapshotServer
from .storage import Storage


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: int
    exit_code: int
    hit_events: int
    hit_lines: int
    export_path: Path


def _system_exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    print(exc.code, file=sys.stderr)
    return 1


def _execute_python(arguments: list[str], project_root: Path) -> int:
    if not arguments:
        raise RunnerError("missing script, -m module, or -c code after python")
    old_argv = sys.argv[:]
    old_path = sys.path[:]
    try:
        if arguments[0] == "-m":
            if len(arguments) < 2:
                raise RunnerError("python -m requires a module name")
            module = arguments[1]
            sys.argv = [module, *arguments[2:]]
            sys.path.insert(0, str(project_root))
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        elif arguments[0] == "-c":
            if len(arguments) < 2:
                raise RunnerError("python -c requires code")
            sys.argv = ["-c", *arguments[2:]]
            sys.path.insert(0, str(project_root))
            namespace = {"__name__": "__main__", "__package__": None}
            exec(compile(arguments[1], "<string>", "exec"), namespace, namespace)
        else:
            script = Path(arguments[0])
            if not script.is_absolute():
                script = project_root / script
            if not script.is_file():
                raise RunnerError(f"Python script does not exist: {arguments[0]}")
            sys.argv = [str(script), *arguments[1:]]
            sys.path.insert(0, str(script.parent))
            runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv
        sys.path[:] = old_path
    return 0


def execute(command: Sequence[str], project_root: Path) -> int:
    arguments = list(command)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    if not arguments:
        raise RunnerError("missing command; for example: runtimespy run -- python app.py")

    executable = Path(arguments[0]).name
    if executable in {"python", "python3", Path(sys.executable).name}:
        return _execute_python(arguments[1:], project_root)
    if executable == "pytest":
        try:
            pytest = importlib.import_module("pytest")
        except ModuleNotFoundError as exc:
            raise RunnerError("pytest is not installed in this environment") from exc
        return int(pytest.main(arguments[1:]))
    if arguments[0].endswith(".py"):
        return _execute_python(arguments, project_root)
    raise RunnerError(
        "unsupported target; use `python script.py`, `python -m module`, or `pytest`"
    )


def run_session(
    config: RuntimeSpyConfig,
    command: Sequence[str],
    *,
    context: str = "default",
) -> RunResult:
    collector = RuntimeSpy(config)
    started = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    exit_code = 1
    pending_error: BaseException | None = None
    snapshot_server = OnDemandSnapshotServer(
        collector,
        context=context,
        started_at=started.isoformat(),
    )

    collector.start()
    try:
        snapshot_server.start()
    except BaseException:
        collector.stop()
        raise
    try:
        try:
            exit_code = execute(command, config.project_root)
        except SystemExit as exc:
            exit_code = _system_exit_code(exc)
        except BaseException as exc:
            pending_error = exc
            exit_code = 1
    finally:
        snapshot_server.stop()
        collector.stop()

    duration = time.perf_counter() - started_clock
    sources = snapshot_scope(collector.scope)
    hits = collector.hits
    storage = Storage(config.database_path)
    command_text = shlex.join(command)
    run_id = storage.record_run(
        started_at=started.isoformat(),
        duration_seconds=duration,
        command=command_text,
        context=context,
        exit_code=exit_code,
        python_version=sys.version,
        hits=hits,
        sources=sources,
    )
    export_path = write_final_export(
        project_root=config.project_root,
        started_at=started.isoformat(),
        command=command_text,
        context=context,
        run_id=run_id,
        exit_code=exit_code,
        sources=sources,
        hits=hits,
    )
    if pending_error is not None:
        raise pending_error
    return RunResult(
        run_id=run_id,
        exit_code=exit_code,
        hit_events=sum(hits.values()),
        hit_lines=len(hits),
        export_path=export_path,
    )
