"""Build a project-level logical control-flow graph from Python ASTs."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping

from .analysis import SourceSnapshot
from .collector import BranchKey, CodeStartKey, LineKey


GRAPH_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class _Flow:
    entry: str | None
    exits: tuple[str, ...]


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _body_range(
    body: list[ast.stmt], fallback: ast.AST
) -> tuple[int, int, int, int]:
    if body:
        first = body[0]
        last = body[-1]
        return (
            first.lineno,
            first.col_offset,
            getattr(last, "end_lineno", last.lineno),
            getattr(last, "end_col_offset", last.col_offset),
        )
    line = getattr(fallback, "lineno", 1)
    column = getattr(fallback, "col_offset", 0)
    return (
        line,
        column,
        getattr(fallback, "end_lineno", line),
        getattr(fallback, "end_col_offset", column),
    )


def _node_range(node: ast.AST) -> tuple[int, int, int, int]:
    line = getattr(node, "lineno", 1)
    column = getattr(node, "col_offset", 0)
    return (
        line,
        column,
        getattr(node, "end_lineno", line),
        getattr(node, "end_col_offset", column),
    )


def _entry_line(body: list[ast.stmt], fallback: int) -> int:
    for statement in body:
        if not _is_docstring(statement):
            return statement.lineno
    return fallback


class _FileGraphBuilder:
    def __init__(
        self,
        *,
        path: str,
        module: str,
        source: str,
        content_hash: str,
        hits: Mapping[int, int],
        starts: Mapping[str, int],
        branches: Mapping[tuple[str, int, int, int, int], int],
    ):
        self.path = path
        self.module = module
        self.source = source
        self.content_hash = content_hash
        self.hits = hits
        self.starts = starts
        self.branches = branches
        self.lines = source.splitlines()
        self.nodes: list[dict[str, Any]] = []
        self.node_by_id: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        self.scopes: list[dict[str, Any]] = []

    @staticmethod
    def _contains_position(
        location: tuple[int, int, int, int], line: int, column: int
    ) -> bool:
        start_line, start_column, end_line, end_column = location
        if line < start_line or line > end_line:
            return False
        if line == start_line and column < start_column:
            return False
        if line == end_line and column >= end_column:
            return False
        return True

    def _branch_outcomes(
        self,
        *,
        qualname: str,
        condition: tuple[int, int, int, int],
        taken: tuple[int, int, int, int],
        alternate: tuple[int, int, int, int] | None,
    ) -> tuple[int, int, bool]:
        taken_count = 0
        alternate_count = 0
        matched = False
        for key, count in self.branches.items():
            branch_qualname, source_line, source_column, dest_line, dest_column = key
            if branch_qualname != qualname or not self._contains_position(
                condition, source_line, source_column
            ):
                continue
            if self._contains_position(taken, dest_line, dest_column):
                taken_count += count
                matched = True
            elif alternate is not None and self._contains_position(
                alternate, dest_line, dest_column
            ):
                alternate_count += count
                matched = True
            elif not self._contains_position(condition, dest_line, dest_column):
                alternate_count += count
                matched = True
        return taken_count, alternate_count, matched

    def _stable_id(
        self,
        *,
        node_type: str,
        qualname: str,
        location: tuple[int, int, int, int],
        label: str,
    ) -> str:
        start_line, start_column, end_line, end_column = location
        material = "\0".join(
            (
                self.path,
                self.content_hash,
                qualname,
                node_type,
                label,
                f"{start_line}:{start_column}-{end_line}:{end_column}",
            )
        )
        return "node_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]

    def _add_node(
        self,
        node_type: str,
        location: tuple[int, int, int, int],
        *,
        entry_line: int,
        parent_id: str | None,
        qualname: str,
        label: str,
        frequency: int | None = None,
    ) -> str:
        node_id = self._stable_id(
            node_type=node_type,
            qualname=qualname,
            location=location,
            label=label,
        )
        start_line, start_column, end_line, end_column = location
        value = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "path": self.path,
            "module": self.module,
            "qualname": qualname,
            "parent_id": parent_id,
            "start_line": start_line,
            "start_column": start_column,
            "end_line": end_line,
            "end_column": end_column,
            "entry_line": entry_line,
            "frequency": self.hits.get(entry_line, 0) if frequency is None else frequency,
        }
        self.nodes.append(value)
        self.node_by_id[node_id] = value
        return node_id

    def _add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        frequency: int = 0,
    ) -> None:
        key = (source, target, edge_type)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        material = "\0".join((source, target, edge_type))
        self.edges.append(
            {
                "id": "edge_"
                + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20],
                "from": source,
                "to": target,
                "type": edge_type,
                "frequency": frequency,
            }
        )

    def _connect(self, sources: Iterable[str], target: str, edge_type: str = "next") -> None:
        for source in sources:
            self._add_edge(source, target, edge_type)

    def _basic_block(
        self,
        statements: list[ast.stmt],
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        location = _body_range(statements, statements[0])
        statement_types = [type(statement).__name__ for statement in statements]
        node_id = self._add_node(
            "basic_block",
            location,
            entry_line=statements[0].lineno,
            parent_id=parent_id,
            qualname=qualname,
            label=", ".join(statement_types),
        )
        terminal = isinstance(
            statements[-1], (ast.Return, ast.Raise, ast.Break, ast.Continue)
        )
        return _Flow(node_id, () if terminal else (node_id,))

    def _definition(
        self,
        statement: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        definition_line = (
            self.lines[statement.lineno - 1]
            if 0 < statement.lineno <= len(self.lines)
            else ""
        )
        definition_location = (
            statement.lineno,
            statement.col_offset,
            statement.lineno,
            len(definition_line),
        )
        definition_id = self._add_node(
            "definition",
            definition_location,
            entry_line=statement.lineno,
            parent_id=parent_id,
            qualname=qualname,
            label=f"define {statement.name}",
        )
        nested_qualname = (
            statement.name if qualname == "<module>" else f"{qualname}.{statement.name}"
        )
        scope_type = "class_entry" if isinstance(statement, ast.ClassDef) else "function_entry"
        scope_id = self._add_node(
            scope_type,
            _node_range(statement),
            entry_line=_entry_line(statement.body, statement.lineno),
            parent_id=definition_id,
            qualname=nested_qualname,
            label=nested_qualname,
            frequency=self.starts.get(nested_qualname, 0),
        )
        self.scopes.append(
            {"id": scope_id, "type": scope_type, "qualname": nested_qualname}
        )
        self._add_edge(definition_id, scope_id, "defines")
        body_flow = self._build_region(
            statement.body, parent_id=scope_id, qualname=nested_qualname
        )
        if body_flow.entry is not None:
            self._add_edge(scope_id, body_flow.entry, "entry")
        return _Flow(definition_id, (definition_id,))

    def _if(
        self,
        statement: ast.If,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        condition_location = _node_range(statement.test)
        true_location = _body_range(statement.body, statement)
        false_location = (
            _body_range(statement.orelse, statement) if statement.orelse else None
        )
        branch_true_count, branch_false_count, has_branch_counts = self._branch_outcomes(
            qualname=qualname,
            condition=condition_location,
            taken=true_location,
            alternate=false_location,
        )
        line_condition_count = self.hits.get(statement.test.lineno, 0)
        if (
            has_branch_counts
            and branch_true_count + branch_false_count < line_condition_count
        ):
            branch_false_count += line_condition_count - (
                branch_true_count + branch_false_count
            )
        condition_id = self._add_node(
            "condition",
            condition_location,
            entry_line=statement.test.lineno,
            parent_id=parent_id,
            qualname=qualname,
            label="if",
            frequency=(
                branch_true_count + branch_false_count if has_branch_counts else None
            ),
        )
        condition_frequency = self.node_by_id[condition_id]["frequency"]

        true_id = self._add_node(
            "branch_true",
            true_location,
            entry_line=_entry_line(statement.body, statement.lineno),
            parent_id=condition_id,
            qualname=qualname,
            label="true",
            frequency=branch_true_count if has_branch_counts else None,
        )
        true_frequency = self.node_by_id[true_id]["frequency"]
        self._add_edge(condition_id, true_id, "true", frequency=true_frequency)
        true_flow = self._build_region(
            statement.body, parent_id=true_id, qualname=qualname
        )
        if true_flow.entry is not None:
            self._add_edge(true_id, true_flow.entry, "entry")
        true_exits = true_flow.exits or ((true_id,) if true_flow.entry is None else ())

        if statement.orelse:
            assert false_location is not None
            false_entry = _entry_line(statement.orelse, statement.lineno)
            false_frequency = (
                branch_false_count
                if has_branch_counts
                else self.hits.get(false_entry, 0)
            )
        else:
            false_location = condition_location
            false_entry = statement.test.lineno
            false_frequency = (
                branch_false_count
                if has_branch_counts
                else max(condition_frequency - true_frequency, 0)
            )
        false_id = self._add_node(
            "branch_false",
            false_location,
            entry_line=false_entry,
            parent_id=condition_id,
            qualname=qualname,
            label="false",
            frequency=false_frequency,
        )
        self._add_edge(condition_id, false_id, "false", frequency=false_frequency)
        false_flow = self._build_region(
            statement.orelse, parent_id=false_id, qualname=qualname
        )
        if false_flow.entry is not None:
            self._add_edge(false_id, false_flow.entry, "entry")
        false_exits = false_flow.exits or (
            (false_id,) if false_flow.entry is None else ()
        )
        return _Flow(condition_id, tuple((*true_exits, *false_exits)))

    def _loop(
        self,
        statement: ast.For | ast.AsyncFor | ast.While,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        expression = statement.test if isinstance(statement, ast.While) else statement.iter
        condition_location = _node_range(expression)
        body_location = _body_range(statement.body, statement)
        alternate_location = (
            _body_range(statement.orelse, statement) if statement.orelse else None
        )
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            transition_taken_location = _node_range(statement.target)
            transition_alternate_location = condition_location
        else:
            transition_taken_location = body_location
            transition_alternate_location = alternate_location
        body_count, exit_count, has_branch_counts = self._branch_outcomes(
            qualname=qualname,
            condition=condition_location,
            taken=transition_taken_location,
            alternate=transition_alternate_location,
        )
        line_condition_count = self.hits.get(expression.lineno, 0)
        if has_branch_counts and body_count + exit_count < line_condition_count:
            exit_count += line_condition_count - (body_count + exit_count)
        loop_type = "while_condition" if isinstance(statement, ast.While) else "for_iteration"
        condition_id = self._add_node(
            loop_type,
            condition_location,
            entry_line=expression.lineno,
            parent_id=parent_id,
            qualname=qualname,
            label="while" if isinstance(statement, ast.While) else "for",
            frequency=body_count + exit_count if has_branch_counts else None,
        )
        condition_frequency = self.node_by_id[condition_id]["frequency"]
        body_id = self._add_node(
            "loop_body",
            body_location,
            entry_line=_entry_line(statement.body, statement.lineno),
            parent_id=condition_id,
            qualname=qualname,
            label="loop body",
            frequency=body_count if has_branch_counts else None,
        )
        body_frequency = self.node_by_id[body_id]["frequency"]
        self._add_edge(condition_id, body_id, "iterate", frequency=body_frequency)
        body_flow = self._build_region(statement.body, parent_id=body_id, qualname=qualname)
        if body_flow.entry is not None:
            self._add_edge(body_id, body_flow.entry, "entry")
        self._connect(body_flow.exits, condition_id, "loop_back")

        exit_frequency = (
            exit_count
            if has_branch_counts
            else max(condition_frequency - body_frequency, 0)
        )
        if statement.orelse:
            exit_id = self._add_node(
                "loop_else",
                _body_range(statement.orelse, statement),
                entry_line=_entry_line(statement.orelse, statement.lineno),
                parent_id=condition_id,
                qualname=qualname,
                label="loop else",
            )
            exit_frequency = self.node_by_id[exit_id]["frequency"]
            exit_flow = self._build_region(
                statement.orelse, parent_id=exit_id, qualname=qualname
            )
            if exit_flow.entry is not None:
                self._add_edge(exit_id, exit_flow.entry, "entry")
            exits = exit_flow.exits or ((exit_id,) if exit_flow.entry is None else ())
        else:
            exit_id = self._add_node(
                "loop_exit",
                _node_range(expression),
                entry_line=expression.lineno,
                parent_id=condition_id,
                qualname=qualname,
                label="loop exit",
                frequency=exit_frequency,
            )
            exits = (exit_id,)
        self._add_edge(condition_id, exit_id, "exit", frequency=exit_frequency)
        return _Flow(condition_id, exits)

    def _try(
        self,
        statement: ast.Try | ast.TryStar,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        try_id = self._add_node(
            "try_body",
            _body_range(statement.body, statement),
            entry_line=_entry_line(statement.body, statement.lineno),
            parent_id=parent_id,
            qualname=qualname,
            label="try",
        )
        body_flow = self._build_region(statement.body, parent_id=try_id, qualname=qualname)
        if body_flow.entry is not None:
            self._add_edge(try_id, body_flow.entry, "entry")
        exits = list(body_flow.exits)

        for index, handler in enumerate(statement.handlers):
            handler_id = self._add_node(
                "except_handler",
                _body_range(handler.body, handler),
                entry_line=_entry_line(handler.body, handler.lineno),
                parent_id=try_id,
                qualname=qualname,
                label=f"except {index + 1}",
            )
            handler_frequency = self.node_by_id[handler_id]["frequency"]
            self._add_edge(try_id, handler_id, "exception", frequency=handler_frequency)
            handler_flow = self._build_region(
                handler.body, parent_id=handler_id, qualname=qualname
            )
            if handler_flow.entry is not None:
                self._add_edge(handler_id, handler_flow.entry, "entry")
            exits.extend(handler_flow.exits)

        if statement.orelse:
            else_id = self._add_node(
                "try_else",
                _body_range(statement.orelse, statement),
                entry_line=_entry_line(statement.orelse, statement.lineno),
                parent_id=try_id,
                qualname=qualname,
                label="try else",
            )
            self._connect(body_flow.exits, else_id, "normal")
            else_flow = self._build_region(
                statement.orelse, parent_id=else_id, qualname=qualname
            )
            if else_flow.entry is not None:
                self._add_edge(else_id, else_flow.entry, "entry")
            exits = list(else_flow.exits) + [
                item for item in exits if item not in body_flow.exits
            ]

        if statement.finalbody:
            final_id = self._add_node(
                "finally_block",
                _body_range(statement.finalbody, statement),
                entry_line=_entry_line(statement.finalbody, statement.lineno),
                parent_id=try_id,
                qualname=qualname,
                label="finally",
            )
            self._connect(exits, final_id, "finally")
            final_flow = self._build_region(
                statement.finalbody, parent_id=final_id, qualname=qualname
            )
            if final_flow.entry is not None:
                self._add_edge(final_id, final_flow.entry, "entry")
            exits = list(final_flow.exits)
        return _Flow(try_id, tuple(exits))

    def _match(
        self,
        statement: ast.Match,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        match_id = self._add_node(
            "match_subject",
            _node_range(statement.subject),
            entry_line=statement.subject.lineno,
            parent_id=parent_id,
            qualname=qualname,
            label="match",
        )
        exits: list[str] = []
        selected = 0
        for index, case in enumerate(statement.cases):
            case_line = _entry_line(case.body, getattr(case.pattern, "lineno", statement.lineno))
            case_id = self._add_node(
                "match_case",
                _body_range(case.body, case.pattern),
                entry_line=case_line,
                parent_id=match_id,
                qualname=qualname,
                label=f"case {index + 1}",
            )
            case_frequency = self.node_by_id[case_id]["frequency"]
            selected += case_frequency
            self._add_edge(match_id, case_id, "case", frequency=case_frequency)
            case_flow = self._build_region(case.body, parent_id=case_id, qualname=qualname)
            if case_flow.entry is not None:
                self._add_edge(case_id, case_flow.entry, "entry")
            exits.extend(case_flow.exits or ((case_id,) if case_flow.entry is None else ()))
        unmatched_frequency = max(self.node_by_id[match_id]["frequency"] - selected, 0)
        unmatched_id = self._add_node(
            "match_unmatched",
            _node_range(statement.subject),
            entry_line=statement.subject.lineno,
            parent_id=match_id,
            qualname=qualname,
            label="unmatched",
            frequency=unmatched_frequency,
        )
        self._add_edge(match_id, unmatched_id, "unmatched", frequency=unmatched_frequency)
        exits.append(unmatched_id)
        return _Flow(match_id, tuple(exits))

    def _with(
        self,
        statement: ast.With | ast.AsyncWith,
        *,
        parent_id: str,
        qualname: str,
    ) -> _Flow:
        with_id = self._add_node(
            "with_context",
            _node_range(statement.items[0].context_expr),
            entry_line=statement.items[0].context_expr.lineno,
            parent_id=parent_id,
            qualname=qualname,
            label="async with" if isinstance(statement, ast.AsyncWith) else "with",
        )
        body_flow = self._build_region(statement.body, parent_id=with_id, qualname=qualname)
        if body_flow.entry is not None:
            self._add_edge(with_id, body_flow.entry, "entry")
        return _Flow(with_id, body_flow.exits)

    def _build_control(
        self, statement: ast.stmt, *, parent_id: str, qualname: str
    ) -> _Flow:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return self._definition(statement, parent_id=parent_id, qualname=qualname)
        if isinstance(statement, ast.If):
            return self._if(statement, parent_id=parent_id, qualname=qualname)
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
            return self._loop(statement, parent_id=parent_id, qualname=qualname)
        if isinstance(statement, (ast.Try, ast.TryStar)):
            return self._try(statement, parent_id=parent_id, qualname=qualname)
        if isinstance(statement, ast.Match):
            return self._match(statement, parent_id=parent_id, qualname=qualname)
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            return self._with(statement, parent_id=parent_id, qualname=qualname)
        raise AssertionError(f"unsupported control statement: {type(statement).__name__}")

    @staticmethod
    def _is_control(statement: ast.stmt) -> bool:
        return isinstance(
            statement,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.TryStar,
                ast.Match,
                ast.With,
                ast.AsyncWith,
            ),
        )

    def _build_region(
        self, statements: list[ast.stmt], *, parent_id: str, qualname: str
    ) -> _Flow:
        entry: str | None = None
        exits: tuple[str, ...] = ()
        index = 0
        while index < len(statements):
            statement = statements[index]
            if _is_docstring(statement):
                index += 1
                continue
            if self._is_control(statement):
                flow = self._build_control(
                    statement, parent_id=parent_id, qualname=qualname
                )
                index += 1
            else:
                block: list[ast.stmt] = []
                while index < len(statements) and not self._is_control(statements[index]):
                    current = statements[index]
                    index += 1
                    if _is_docstring(current):
                        continue
                    block.append(current)
                    if isinstance(current, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                        break
                if not block:
                    continue
                flow = self._basic_block(block, parent_id=parent_id, qualname=qualname)

            if flow.entry is None:
                continue
            if entry is None:
                entry = flow.entry
            if exits:
                self._connect(exits, flow.entry)
            exits = flow.exits
        return _Flow(entry, exits)

    def build(self) -> dict[str, Any]:
        try:
            tree = ast.parse(self.source, filename=self.path)
        except SyntaxError:
            return {
                "path": self.path,
                "module": self.module,
                "root_node_id": None,
                "node_ids": [],
                "scopes": [],
                "nodes": [],
                "edges": [],
            }

        line_count = max(len(self.lines), 1)
        module_entry_line = _entry_line(tree.body, 1)
        root_id = self._add_node(
            "module_entry",
            (1, 0, line_count, len(self.lines[-1]) if self.lines else 0),
            entry_line=module_entry_line,
            parent_id=None,
            qualname="<module>",
            label=self.module or self.path,
            frequency=self.starts.get("<module>", 0),
        )
        self.scopes.append({"id": root_id, "type": "module_entry", "qualname": "<module>"})
        flow = self._build_region(tree.body, parent_id=root_id, qualname="<module>")
        if flow.entry is not None:
            self._add_edge(root_id, flow.entry, "entry")
        return {
            "path": self.path,
            "module": self.module,
            "root_node_id": root_id,
            "node_ids": [node["id"] for node in self.nodes],
            "scopes": self.scopes,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def _combine_files(files: Iterable[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    hierarchy: list[dict[str, Any]] = []
    for item in files:
        nodes.extend(item["nodes"])
        edges.extend(item["edges"])
        hierarchy.append(
            {
                key: item[key]
                for key in ("path", "module", "root_node_id", "node_ids", "scopes")
            }
        )
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "type": "control_flow",
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "executed_nodes": sum(1 for node in nodes if node["frequency"] > 0),
            "unseen_nodes": sum(1 for node in nodes if node["frequency"] == 0),
        },
        "hierarchy": {"files": hierarchy},
        "nodes": nodes,
        "edges": edges,
    }


def graph_from_snapshots(
    sources: Iterable[SourceSnapshot],
    hits: Mapping[LineKey, int],
    starts: Mapping[CodeStartKey, int] | None = None,
    branches: Mapping[BranchKey, int] | None = None,
) -> dict[str, Any]:
    hits_by_file: dict[str, dict[int, int]] = {}
    for (path, line), count in hits.items():
        hits_by_file.setdefault(path, {})[line] = count
    starts_by_file: dict[str, dict[str, int]] = {}
    for (path, qualname, first_line), count in (starts or {}).items():
        file_starts = starts_by_file.setdefault(path, {})
        file_starts[qualname] = file_starts.get(qualname, 0) + count
    branches_by_file: dict[
        str, dict[tuple[str, int, int, int, int], int]
    ] = {}
    for key, count in (branches or {}).items():
        path, qualname, source_line, source_column, dest_line, dest_column = key
        branches_by_file.setdefault(path, {})[
            (qualname, source_line, source_column, dest_line, dest_column)
        ] = count
    return _combine_files(
        _FileGraphBuilder(
            path=item.path,
            module=item.module,
            source=item.source,
            content_hash=item.content_hash,
            hits=hits_by_file.get(item.path, {}),
            starts=starts_by_file.get(item.path, {}),
            branches=branches_by_file.get(item.path, {}),
        ).build()
        for item in sources
    )


def graph_from_stored(sources: Iterable[Any]) -> dict[str, Any]:
    return _combine_files(
        _FileGraphBuilder(
            path=item.path,
            module=item.module,
            source=item.source,
            content_hash=hashlib.sha256(item.source.encode("utf-8")).hexdigest(),
            hits=item.hits,
            starts=item.starts,
            branches=item.branches,
        ).build()
        for item in sources
    )
