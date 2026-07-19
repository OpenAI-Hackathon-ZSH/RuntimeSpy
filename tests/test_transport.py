import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from runtimespy import transport


class TransportTests(unittest.TestCase):
    def test_full_graph_and_node_counts_use_the_configured_routes(self):
        response = MagicMock()
        response.__enter__.return_value = response
        payload = {"value": "graph"}

        with (
            patch.object(transport, "urlopen", return_value=response) as open_url,
            self.assertLogs("runtimespy.transport", level="INFO") as report_logs,
        ):
            self.assertTrue(
                transport.send_graph(
                    payload,
                    endpoint="https://collector.example/runtime",
                )
            )
            graph_request = open_url.call_args.args[0]
            self.assertEqual(
                graph_request.full_url,
                "https://collector.example/runtime/report/full_graph",
            )
            self.assertEqual(graph_request.get_method(), "POST")
            self.assertEqual(
                graph_request.get_header("Content-type"), "application/json"
            )
            self.assertEqual(json.loads(graph_request.data), payload)

            self.assertTrue(
                transport.send_frequency(
                    {"Frequency": []},
                    endpoint="https://collector.example/runtime",
                )
            )
            node_request = open_url.call_args.args[0]
            self.assertEqual(
                node_request.full_url,
                "https://collector.example/runtime/report/node",
            )

        self.assertIn(
            'body={"value":"graph"}',
            report_logs.output[0],
        )
        self.assertIn(
            'body={"Frequency":[]}',
            report_logs.output[1],
        )

    def test_reporting_failure_does_not_break_the_application(self):
        with (
            patch.object(transport, "urlopen", side_effect=URLError("offline")),
            self.assertLogs("runtimespy.transport", level="WARNING"),
        ):
            sent = transport.send_frequency(
                {"Frequency": []},
                endpoint="http://127.0.0.1:9000",
            )
        self.assertFalse(sent)

    def test_missing_endpoint_disables_http_reporting(self):
        with patch.object(transport, "urlopen") as open_url:
            self.assertFalse(transport.send_graph({}, endpoint=None))
        open_url.assert_not_called()

    def test_endpoint_is_validated_and_normalized(self):
        self.assertEqual(
            transport.normalize_endpoint(" https://collector.example/api/ "),
            "https://collector.example/api",
        )
        for endpoint in ("", "collector.example", "ftp://collector.example"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    transport.normalize_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
