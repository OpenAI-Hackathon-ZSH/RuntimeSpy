"""Static source inventory used by the report."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
import tokenize

from .scope import ScopeDecision, ScopeMatcher


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: str
    module: str
    source: str
    content_hash: str
    executable_lines: tuple[int, ...]
    parse_error: str | None = None


def _docstring_nodes(tree: ast.AST) -> set[ast.AST]:
    result: set[ast.AST] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            result.add(first)
    return result


def snapshot(decision: ScopeDecision) -> SourceSnapshot:
    try:
        with tokenize.open(decision.path) as handle:
            source = handle.read()
    except (OSError, SyntaxError, UnicodeError) as exc:
        return SourceSnapshot(
            decision.relative_path,
            decision.module,
            "",
            "",
            (),
            f"cannot read source: {exc}",
        )

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    try:
        tree = ast.parse(source, filename=str(decision.path))
    except SyntaxError as exc:
        return SourceSnapshot(
            decision.relative_path,
            decision.module,
            source,
            digest,
            (),
            f"syntax error: {exc.msg} at line {exc.lineno}",
        )

    docstrings = _docstring_nodes(tree)
    lines = {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt)
        and node not in docstrings
        and hasattr(node, "lineno")
    }
    return SourceSnapshot(
        decision.relative_path,
        decision.module,
        source,
        digest,
        tuple(sorted(lines)),
    )


def snapshot_scope(scope: ScopeMatcher) -> list[SourceSnapshot]:
    return [snapshot(item) for item in scope.discover() if item.included]

