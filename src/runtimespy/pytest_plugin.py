"""Opt-in pytest integration."""

from __future__ import annotations

from datetime import datetime, timezone
import shlex
import sys
import time

from .analysis import snapshot_scope
from .collector import RuntimeSpy
from .config import ConfigError, load_config
from .exporting import write_final_export
from .live import OnDemandSnapshotServer
from .storage import Storage


def pytest_addoption(parser):
    group = parser.getgroup("runtimespy")
    group.addoption(
        "--runtimespy",
        action="store_true",
        default=False,
        help="record RuntimeSpy execution counts",
    )
    group.addoption(
        "--runtimespy-context",
        default="pytest",
        help="context label stored with this RuntimeSpy run",
    )


def pytest_configure(config):
    if not config.getoption("--runtimespy"):
        return
    try:
        spy_config = load_config()
    except ConfigError as exc:
        import pytest

        raise pytest.UsageError(str(exc)) from exc
    collector = RuntimeSpy(spy_config)
    started = datetime.now(timezone.utc)
    collector.start()
    snapshot_server = OnDemandSnapshotServer(
        collector,
        context=config.getoption("--runtimespy-context"),
        started_at=started.isoformat(),
    ).start()
    config._runtimespy_state = (
        collector,
        snapshot_server,
        started,
        time.perf_counter(),
    )


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "_runtimespy_state"):
        session.config._runtimespy_exitstatus = int(exitstatus)


def pytest_unconfigure(config):
    state = getattr(config, "_runtimespy_state", None)
    if state is None:
        return
    collector, snapshot_server, started, started_clock = state
    snapshot_server.stop()
    collector.stop()
    exit_code = int(getattr(config, "_runtimespy_exitstatus", 0))
    sources = snapshot_scope(collector.scope)
    hits = collector.hits
    command = shlex.join(["pytest", *sys.argv[1:]])
    run_id = Storage(collector.config.database_path).record_run(
        started_at=started.isoformat(),
        duration_seconds=time.perf_counter() - started_clock,
        command=command,
        context=config.getoption("--runtimespy-context"),
        exit_code=exit_code,
        python_version=sys.version,
        hits=hits,
        sources=sources,
    )
    write_final_export(
        project_root=collector.config.project_root,
        started_at=started.isoformat(),
        command=command,
        context=config.getoption("--runtimespy-context"),
        run_id=run_id,
        exit_code=exit_code,
        sources=sources,
        hits=hits,
    )
    del config._runtimespy_state
