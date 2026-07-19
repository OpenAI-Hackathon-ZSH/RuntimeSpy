from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import simulate_traffic  # noqa: E402


class PacedTrafficTests(unittest.TestCase):
    def test_waits_between_requests_but_not_before_the_first(self):
        result = simulate_traffic.HttpResult(200, {}, {})
        caller = simulate_traffic.PacedCaller(2.0)

        with (
            patch.object(simulate_traffic, "call", return_value=result) as call,
            patch.object(simulate_traffic.time, "sleep") as sleep,
        ):
            caller("http://localhost", "GET", "/first")
            sleep.assert_not_called()
            caller("http://localhost", "GET", "/second")

        sleep.assert_called_once_with(2.0)
        self.assertEqual(call.call_count, 2)

    def test_negative_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            simulate_traffic.PacedCaller(-1)


if __name__ == "__main__":
    unittest.main()
