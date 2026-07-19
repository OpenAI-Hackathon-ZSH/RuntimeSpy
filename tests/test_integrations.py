import unittest
from unittest.mock import patch

from runtimespy.integrations import _instrument_flask_class


class FlaskIntegrationTests(unittest.TestCase):
    def test_wsgi_wrapper_automatically_tracks_each_request(self):
        events: list[object] = []
        trace = object()

        class FakeFlask:
            def wsgi_app(self, environ, start_response):
                events.append("application")
                return [b"ok"]

        with (
            patch(
                "runtimespy.api.begin_request",
                side_effect=lambda: events.append("begin") or trace,
            ),
            patch(
                "runtimespy.api.end_request",
                side_effect=lambda request: events.append(("end", request)),
            ),
        ):
            self.assertTrue(_instrument_flask_class(FakeFlask))
            self.assertFalse(_instrument_flask_class(FakeFlask))
            response = FakeFlask().wsgi_app({}, lambda *_args: None)

        self.assertEqual(response, [b"ok"])
        self.assertEqual(events, ["begin", "application", ("end", trace)])

    def test_wsgi_wrapper_finishes_a_failed_request(self):
        trace = object()

        class FailingFlask:
            def wsgi_app(self, environ, start_response):
                raise LookupError("request failed")

        with (
            patch("runtimespy.api.begin_request", return_value=trace),
            patch("runtimespy.api.end_request") as end_request,
        ):
            _instrument_flask_class(FailingFlask)
            with self.assertRaisesRegex(LookupError, "request failed"):
                FailingFlask().wsgi_app({}, lambda *_args: None)

        end_request.assert_called_once_with(trace)


if __name__ == "__main__":
    unittest.main()
