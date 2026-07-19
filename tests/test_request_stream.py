from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

import runtimespy
from runtimespy import api
from runtimespy import transport


SOURCE = (
    "def choose(flag):\n"
    "    if flag:\n"
    "        return 'yes'\n"
    "    return 'no'\n"
    "\n"
    "choose(True)\n"
    "choose(False)\n"
)


class RequestStreamTests(unittest.TestCase):
    def test_initial_graph_and_request_local_frequencies_are_emitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "example"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("", encoding="utf-8")
            target = source / "target.py"
            target.write_text(SOURCE, encoding="utf-8")

            with (
                patch.object(transport, "send_graph") as send_graph,
                patch.object(transport, "send_frequency") as send_frequency,
                patch.object(
                    api, "install_optional_integrations"
                ) as install_integrations,
            ):
                session = runtimespy.init(
                    source="src",
                    project_root=root,
                    context="request-stream-test",
                    serve_export=False,
                )
                initial = send_graph.call_args.args[0]

                install_integrations.assert_called_once_with()
                self.assertEqual(initial["schema_version"], 2)
                self.assertEqual(initial["mode"], "initial")
                self.assertEqual(initial["summary"]["executed_nodes"], 0)
                self.assertTrue(initial["graph"]["nodes"])
                self.assertTrue(
                    all(node["frequency"] == 0 for node in initial["graph"]["nodes"])
                )
                self.assertTrue(
                    all(edge["frequency"] == 0 for edge in initial["graph"]["edges"])
                )

                first_request = runtimespy.begin_request()
                runpy.run_path(str(target))
                first_payload = runtimespy.end_request(first_request)

                second_request = runtimespy.begin_request()
                runpy.run_path(str(target))
                second_payload = runtimespy.end_request(second_request)
                self.assertEqual(
                    runtimespy.end_request(second_request), second_payload
                )
                session.stop()

                self.assertEqual(first_payload, second_payload)
                self.assertEqual(send_frequency.call_count, 2)
                frequencies = first_payload["Frequency"]
                self.assertTrue(frequencies)
                self.assertTrue(all(item["count"] > 0 for item in frequencies))
                initial_ids = {node["id"] for node in initial["graph"]["nodes"]}
                self.assertTrue(
                    all(item["node"] in initial_ids for item in frequencies)
                )

    def test_request_api_is_a_noop_without_an_active_session(self):
        self.assertIsNone(runtimespy.begin_request())
        self.assertIsNone(runtimespy.end_request(None))


if __name__ == "__main__":
    unittest.main()
