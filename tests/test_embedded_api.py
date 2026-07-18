from pathlib import Path
import runpy
import tempfile
import unittest

import runtimespy
from runtimespy.storage import Storage


class EmbeddedApiTests(unittest.TestCase):
    def test_init_collects_and_persists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "example"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("", encoding="utf-8")
            target = source / "target.py"
            target.write_text("value = 1\nvalue += 1\n", encoding="utf-8")

            session = runtimespy.init(source="src", project_root=root, context="embedded")
            runpy.run_path(str(target))
            run_id = session.stop()

            self.assertGreater(run_id, 0)
            self.assertEqual(
                session.export_path, (root / ".runtimespy" / "export.json").resolve()
            )
            self.assertTrue(session.export_path.is_file())
            stored = Storage(root / ".runtimespy" / "runtime.db").load_sources()
            target_data = next(item for item in stored if item.path.endswith("target.py"))
            self.assertEqual(target_data.hits[1], 1)
            self.assertEqual(target_data.hits[2], 1)


if __name__ == "__main__":
    unittest.main()
