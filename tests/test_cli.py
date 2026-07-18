from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest

from runtimespy.cli import main


class CliTests(unittest.TestCase):
    def test_init_inspect_run_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "sample"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            app = package / "app.py"
            app.write_text("value = 1\nif value:\n    value += 1\n", encoding="utf-8")

            previous = Path.cwd()
            output = io.StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(output):
                    self.assertEqual(main(["init", "--source", "src"]), 0)
                    self.assertEqual(main(["inspect"]), 0)
                    self.assertEqual(main(["run", "--", "python", str(app)]), 0)
                    self.assertEqual(main(["report"]), 0)
                    self.assertEqual(
                        main(["export", "--output", ".runtimespy/export.json"]), 0
                    )
            finally:
                os.chdir(previous)

            text = output.getvalue()
            self.assertIn("Will instrument 2 Python file(s)", text)
            self.assertIn("RuntimeSpy run #1", text)
            self.assertTrue((root / ".runtimespy" / "report.html").is_file())
            self.assertTrue((root / ".runtimespy" / "export.json").is_file())


if __name__ == "__main__":
    unittest.main()
