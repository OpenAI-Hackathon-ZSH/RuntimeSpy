"""RuntimeSpy command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import webbrowser

from .config import (
    ConfigError,
    RuntimeSpyConfig,
    choose_source_roots,
    detect_source_roots,
    load_config,
    write_config,
)
from .report import write_report
from .runner import RunnerError, run_session
from .scope import ScopeMatcher
from .storage import Storage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtimespy", description="Runtime execution heatmaps for Python projects"
    )
    parser.add_argument("--version", action="version", version="RuntimeSpy 0.1.0")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    init = subparsers.add_parser("init", help="create project configuration")
    init.add_argument("--source", action="append", default=[])
    init.add_argument("--include", action="append", default=[], dest="include_modules")
    init.add_argument("--exclude", action="append", default=[], dest="exclude_modules")
    init.add_argument("--exclude-path", action="append", default=[], dest="exclude_paths")
    init.add_argument("--data-file", default=".runtimespy/runtime.db")
    init.add_argument("--force", action="store_true")

    inspect = subparsers.add_parser("inspect", help="preview the instrumented file set")
    inspect.add_argument("--show-skipped", action="store_true")

    explain = subparsers.add_parser("explain", help="explain one scope decision")
    explain.add_argument("target", help="source path or importable module name")

    run = subparsers.add_parser("run", help="run and record a Python target")
    run.add_argument("--context", default="default")
    run.add_argument("command", nargs=argparse.REMAINDER)

    report = subparsers.add_parser("report", help="generate an HTML heatmap")
    report.add_argument("--output", default=".runtimespy/report.html")
    report.add_argument("--open", action="store_true", dest="open_report")
    return parser


def _init(args: argparse.Namespace) -> int:
    root = Path.cwd().resolve()
    sources = tuple(args.source) or choose_source_roots(detect_source_roots(root))
    config = RuntimeSpyConfig(
        project_root=root,
        source=sources,
        include_modules=tuple(args.include_modules),
        exclude_modules=tuple(args.exclude_modules),
        exclude_paths=tuple(args.exclude_paths),
        data_file=args.data_file,
    )
    path = write_config(config, force=args.force)
    print(f"Created {path}")
    print(f"Source roots: {', '.join(config.source)}")
    print("Run `runtimespy inspect` to preview the selected files.")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    matcher = ScopeMatcher(load_config())
    decisions = matcher.discover()
    included = [item for item in decisions if item.included]
    skipped = [item for item in decisions if not item.included]
    print(f"Will instrument {len(included)} Python file(s):")
    for item in included:
        print(f"  + {item.relative_path}  [{item.module}]")
    if args.show_skipped:
        print(f"\nSkipped {len(skipped)} Python file(s):")
        for item in skipped:
            print(f"  - {item.relative_path}: {item.reason}")
    elif skipped:
        print(f"\n{len(skipped)} file(s) skipped; use --show-skipped for reasons.")
    return 0


def _explain(args: argparse.Namespace) -> int:
    matcher = ScopeMatcher(load_config())
    target = Path(args.target)
    if target.exists() or args.target.endswith(".py") or "/" in args.target:
        decision = matcher.decide(target)
    else:
        decision = matcher.find_module(args.target)
        if decision is None:
            print(f"No Python file found for module {args.target!r}", file=sys.stderr)
            return 1
    status = "INCLUDED" if decision.included else "SKIPPED"
    print(status)
    print(f"Path: {decision.relative_path}")
    print(f"Module: {decision.module or '-'}")
    print(f"Reason: {decision.reason}")
    return 0


def _run(args: argparse.Namespace) -> int:
    config = load_config()
    result = run_session(config, args.command, context=args.context)
    print(
        f"RuntimeSpy run #{result.run_id}: {result.hit_events} events across "
        f"{result.hit_lines} source lines (exit {result.exit_code})"
    )
    return result.exit_code


def _report(args: argparse.Namespace) -> int:
    config = load_config()
    storage = Storage(config.database_path)
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = config.project_root / destination
    path = write_report(storage.load_sources(), storage.latest_run(), destination)
    print(f"Created {path}")
    if args.open_report:
        webbrowser.open(path.as_uri())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    handlers = {
        "init": _init,
        "inspect": _inspect,
        "explain": _explain,
        "run": _run,
        "report": _report,
    }
    try:
        return handlers[args.subcommand](args)
    except (ConfigError, RunnerError) as exc:
        parser.error(str(exc))
    return 2

