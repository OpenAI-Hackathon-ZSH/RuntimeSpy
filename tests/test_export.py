import json
from pathlib import Path
import runpy
import tempfile
import unittest

import runtimespy
from runtimespy.exporting import build_export, write_export


class ExportTests(unittest.TestCase):
    def test_live_then_stored_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "example"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            target = package / "target.py"
            target.write_text("value = 1\nvalue += 1\n", encoding="utf-8")

            session = runtimespy.init(
                source="src",
                project_root=root,
                context="live-test",
            )
            runpy.run_path(str(target))
            destination = root / ".runtimespy" / "export.json"
            self.assertFalse(destination.exists())

            live = build_export(root)
            self.assertEqual(live["mode"], "live")
            self.assertEqual(live["active_sessions"][0]["context"], "live-test")
            target_data = next(
                item for item in live["files"] if item["path"].endswith("target.py")
            )
            self.assertEqual(target_data["hits"]["1"], 1)
            self.assertEqual(target_data["hits"]["2"], 1)

            write_export(live, destination)
            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8"))["mode"], "live"
            )

            session.stop()
            final = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(final["mode"], "final")
            self.assertEqual(final["session"]["context"], "live-test")
            final_target = next(
                item for item in final["files"] if item["path"].endswith("target.py")
            )
            self.assertEqual(final_target["hits"]["2"], 1)
            self.assertEqual(
                list((root / ".runtimespy").glob("*.json")), [destination]
            )

            stored = build_export(root, include_source=True)
            self.assertEqual(stored["mode"], "stored")
            stored_target = next(
                item for item in stored["files"] if item["path"].endswith("target.py")
            )
            self.assertIn("value += 1", stored_target["source"])


if __name__ == "__main__":
    unittest.main()
