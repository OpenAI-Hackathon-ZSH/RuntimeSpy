"""Opt-in pytest integration."""

from __future__ import annotations

from datetime import datetime, timezone
import shlex
import sys
import time

from .analysis import snapshot_scope
from .collector import RuntimeSpy
from .config import ConfigError, load_config
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
    collector.start()
    config._runtimespy_state = (
        collector,
        datetime.now(timezone.utc),
        time.perf_counter(),
    )


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "_runtimespy_state"):
        session.config._runtimespy_exitstatus = int(exitstatus)


def pytest_unconfigure(config):
    state = getattr(config, "_runtimespy_state", None)
    if state is None:
        return
    collector, started, started_clock = state
    collector.stop()
    exit_code = int(getattr(config, "_runtimespy_exitstatus", 0))
    Storage(collector.config.database_path).record_run(
        started_at=started.isoformat(),
        duration_seconds=time.perf_counter() - started_clock,
        command=shlex.join(["pytest", *sys.argv[1:]]),
        context=config.getoption("--runtimespy-context"),
        exit_code=exit_code,
        python_version=sys.version,
        hits=collector.hits,
        sources=snapshot_scope(collector.scope),
    )
    del config._runtimespy_state
