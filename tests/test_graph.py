import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtimespy.analysis import SourceSnapshot
from runtimespy.config import RuntimeSpyConfig
from runtimespy.exporting import build_export
from runtimespy.graph import graph_from_snapshots
from runtimespy.runner import run_session


SOURCE = (
    "def choose(flag):\n"
    "    if flag:\n"
    "        return 'yes'\n"
    "    else:\n"
    "        return 'no'\n"
    "\n"
    "choose(True)\n"
    "choose(True)\n"
    "choose(False)\n"
)


class GraphTests(unittest.TestCase):
    def test_package_initializers_are_excluded_from_the_logical_graph(self):
        source = "from .service import Service\n"
        snapshot = SourceSnapshot(
            path="src/example/__init__.py",
            module="example",
            source=source,
            content_hash=hashlib.sha256(source.encode()).hexdigest(),
            executable_lines=(1,),
        )

        graph = graph_from_snapshots(
            [snapshot], {("src/example/__init__.py", 1): 1}
        )

        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])
        self.assertEqual(graph["hierarchy"]["files"], [])

    def test_common_control_constructs_become_graph_nodes(self):
        source = (
            "def flows(items, value, manager):\n"
            "    for item in items:\n"
            "        if item:\n"
            "            continue\n"
            "    else:\n"
            "        value = 1\n"
            "    while value:\n"
            "        break\n"
            "    try:\n"
            "        value += 1\n"
            "    except ValueError:\n"
            "        value = 0\n"
            "    else:\n"
            "        value += 2\n"
            "    finally:\n"
            "        value += 3\n"
            "    match value:\n"
            "        case 1:\n"
            "            value = 2\n"
            "        case _:\n"
            "            value = 3\n"
            "    with manager:\n"
            "        value += 1\n"
        )
        snapshot = SourceSnapshot(
            path="src/flows.py",
            module="flows",
            source=source,
            content_hash=hashlib.sha256(source.encode()).hexdigest(),
            executable_lines=(),
        )

        graph = graph_from_snapshots([snapshot], {})
        node_types = {node["type"] for node in graph["nodes"]}

        self.assertTrue(
            {
                "function_entry",
                "for_iteration",
                "loop_body",
                "loop_else",
                "while_condition",
                "try_body",
                "except_handler",
                "try_else",
                "finally_block",
                "match_subject",
                "match_case",
                "with_context",
            }.issubset(node_types)
        )

    def test_graph_node_ids_are_stable_and_branch_edges_have_frequencies(self):
        snapshot = SourceSnapshot(
            path="src/demo.py",
            module="demo",
            source=SOURCE,
            content_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
            executable_lines=(1, 2, 3, 5, 7, 8, 9),
        )
        hits = {
            ("src/demo.py", 1): 1,
            ("src/demo.py", 2): 3,
            ("src/demo.py", 3): 2,
            ("src/demo.py", 5): 1,
            ("src/demo.py", 7): 1,
            ("src/demo.py", 8): 1,
            ("src/demo.py", 9): 1,
        }
        starts = {
            ("src/demo.py", "<module>", 1): 1,
            ("src/demo.py", "choose", 1): 3,
        }

        first = graph_from_snapshots([snapshot], hits, starts)
        second = graph_from_snapshots([snapshot], hits, starts)

        self.assertEqual(
            [node["id"] for node in first["nodes"]],
            [node["id"] for node in second["nodes"]],
        )
        condition = next(node for node in first["nodes"] if node["type"] == "condition")
        function_entry = next(
            node for node in first["nodes"] if node["type"] == "function_entry"
        )
        true_branch = next(
            node for node in first["nodes"] if node["type"] == "branch_true"
        )
        false_branch = next(
            node for node in first["nodes"] if node["type"] == "branch_false"
        )
        self.assertEqual(function_entry["frequency"], 3)
        self.assertEqual(condition["frequency"], 3)
        self.assertEqual(true_branch["frequency"], 2)
        self.assertEqual(false_branch["frequency"], 1)
        self.assertEqual(
            (true_branch["start_line"], true_branch["end_line"]), (3, 3)
        )
        self.assertEqual(
            (false_branch["start_line"], false_branch["end_line"]), (5, 5)
        )
        true_edge = next(edge for edge in first["edges"] if edge["type"] == "true")
        false_edge = next(edge for edge in first["edges"] if edge["type"] == "false")
        self.assertEqual(true_edge["frequency"], 2)
        self.assertEqual(false_edge["frequency"], 1)
        self.assertTrue(
            all(isinstance(edge["frequency"], int) for edge in first["edges"])
        )
        self.assertNotIn(
            "definition", {node["type"] for node in first["nodes"]}
        )
        self.assertNotIn(
            "class_entry", {node["type"] for node in first["nodes"]}
        )
        self.assertNotIn("defines", {edge["type"] for edge in first["edges"]})

    def test_class_and_constructor_entries_are_not_coverage_nodes(self):
        source = (
            "class Service:\n"
            "    def __init__(self, enabled):\n"
            "        if enabled:\n"
            "            self.enabled = True\n"
            "\n"
            "Service(True)\n"
        )
        snapshot = SourceSnapshot(
            path="src/service.py",
            module="service",
            source=source,
            content_hash=hashlib.sha256(source.encode()).hexdigest(),
            executable_lines=(1, 2, 3, 4, 6),
        )

        graph = graph_from_snapshots(
            [snapshot],
            {
                ("src/service.py", 1): 1,
                ("src/service.py", 2): 1,
                ("src/service.py", 3): 1,
                ("src/service.py", 4): 1,
                ("src/service.py", 6): 1,
            },
            {
                ("src/service.py", "<module>", 1): 1,
                ("src/service.py", "Service.__init__", 2): 1,
            },
        )
        nodes = graph["nodes"]
        self.assertNotIn("definition", {node["type"] for node in nodes})
        self.assertNotIn("class_entry", {node["type"] for node in nodes})
        self.assertFalse(
            any(
                node["type"] == "function_entry"
                and node["qualname"] == "Service.__init__"
                for node in nodes
            )
        )
        constructor_condition = next(
            node
            for node in nodes
            if node["type"] == "condition"
            and node["qualname"] == "Service.__init__"
        )
        self.assertEqual(constructor_condition["frequency"], 1)

    def test_runtime_export_contains_project_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "src"
            source_root.mkdir()
            target = source_root / "demo.py"
            target.write_text(SOURCE, encoding="utf-8")
            config = RuntimeSpyConfig(project_root=root, source=("src",))

            run_session(config, ["python", str(target)], context="graph-test")

            payload = json.loads(
                (root / ".runtimespy" / "export.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["schema_version"], 2)
            self.assertNotIn("files", payload)
            self.assertEqual(payload["mode"], "final")
            nodes = payload["graph"]["nodes"]
            condition = next(node for node in nodes if node["type"] == "condition")
            true_branch = next(node for node in nodes if node["type"] == "branch_true")
            false_branch = next(node for node in nodes if node["type"] == "branch_false")
            self.assertEqual(condition["frequency"], 3)
            self.assertEqual(true_branch["frequency"], 2)
            self.assertEqual(false_branch["frequency"], 1)
            for node in (condition, true_branch, false_branch):
                self.assertEqual(node["path"], "src/demo.py")
                self.assertIn("start_line", node)
                self.assertIn("end_line", node)

    def test_scope_entry_frequency_is_not_inflated_by_a_leading_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "src"
            source_root.mkdir()
            target = source_root / "loop.py"
            target.write_text(
                "def iterate():\n"
                "    for value in range(3):\n"
                "        result = value\n"
                "\n"
                "iterate()\n",
                encoding="utf-8",
            )
            config = RuntimeSpyConfig(project_root=root, source=("src",))

            run_session(config, ["python", str(target)], context="loop-test")

            final = json.loads(
                (root / ".runtimespy" / "export.json").read_text(encoding="utf-8")
            )
            frequencies = {
                node["type"]: node["frequency"] for node in final["graph"]["nodes"]
            }
            self.assertEqual(frequencies["module_entry"], 1)
            self.assertEqual(frequencies["function_entry"], 1)
            self.assertEqual(frequencies["for_iteration"], 4)
            self.assertEqual(frequencies["loop_body"], 3)
            self.assertEqual(frequencies["loop_exit"], 1)

            stored = build_export(root)
            stored_frequencies = {
                node["type"]: node["frequency"] for node in stored["graph"]["nodes"]
            }
            self.assertEqual(stored_frequencies["module_entry"], 1)
            self.assertEqual(stored_frequencies["function_entry"], 1)

    def test_single_line_if_branches_are_counted_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "src"
            source_root.mkdir()
            target = source_root / "single_line.py"
            target.write_text(
                "def choose(flag):\n"
                "    if flag: return 1\n"
                "    return 0\n"
                "choose(True)\n"
                "choose(True)\n"
                "choose(False)\n",
                encoding="utf-8",
            )
            config = RuntimeSpyConfig(project_root=root, source=("src",))

            run_session(config, ["python", str(target)], context="single-line-test")

            payload = json.loads(
                (root / ".runtimespy" / "export.json").read_text(encoding="utf-8")
            )
            frequencies = {
                node["type"]: node["frequency"]
                for node in payload["graph"]["nodes"]
                if node["type"] in {"condition", "branch_true", "branch_false"}
            }
            self.assertEqual(frequencies["condition"], 3)
            self.assertEqual(frequencies["branch_true"], 2)
            self.assertEqual(frequencies["branch_false"], 1)

            stored = build_export(root)
            stored_frequencies = {
                node["type"]: node["frequency"]
                for node in stored["graph"]["nodes"]
                if node["type"] in {"condition", "branch_true", "branch_false"}
            }
            self.assertEqual(stored_frequencies, frequencies)


if __name__ == "__main__":
    unittest.main()
