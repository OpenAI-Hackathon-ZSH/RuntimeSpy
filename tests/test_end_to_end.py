from pathlib import Path
import tempfile
import unittest

from runtimespy.config import RuntimeSpyConfig
from runtimespy.report import write_report
from runtimespy.runner import run_session
from runtimespy.storage import Storage


class EndToEndTests(unittest.TestCase):
    def test_run_store_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "demo"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("", encoding="utf-8")
            program = source / "program.py"
            program.write_text(
                "def choose(flag):\n"
                "    if flag:\n"
                "        return 'yes'\n"
                "    return 'no'\n"
                "\n"
                "choose(True)\n",
                encoding="utf-8",
            )
            config = RuntimeSpyConfig(project_root=root, source=("src",))

            result = run_session(config, ["python", str(program)], context="test")

            self.assertEqual(result.exit_code, 0)
            self.assertGreater(result.hit_events, 0)
            storage = Storage(config.database_path)
            files = storage.load_sources()
            self.assertEqual(len(files), 2)
            observed = next(item for item in files if item.path.endswith("program.py"))
            self.assertGreater(observed.hits.get(2, 0), 0)
            self.assertEqual(observed.hits.get(4, 0), 0)

            report = write_report(files, storage.latest_run(), root / "report.html")
            html = report.read_text(encoding="utf-8")
            self.assertIn("RuntimeSpy execution heatmap", html)
            self.assertIn("program.py", html)
            self.assertIn("unseen", html)


if __name__ == "__main__":
    unittest.main()
