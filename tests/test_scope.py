from pathlib import Path
import tempfile
import unittest

from runtimespy.config import RuntimeSpyConfig, load_config, write_config
from runtimespy.scope import ScopeMatcher


class ScopeTests(unittest.TestCase):
    def test_source_boundary_and_excludes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "my_app"
            generated = package / "generated"
            generated.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            service = package / "service.py"
            service.write_text("value = 1\n", encoding="utf-8")
            skipped = generated / "client.py"
            skipped.write_text("value = 2\n", encoding="utf-8")
            outside = root / "dependency.py"
            outside.write_text("value = 3\n", encoding="utf-8")

            config = RuntimeSpyConfig(
                project_root=root,
                source=("src",),
                include_modules=("my_app",),
                exclude_modules=("my_app.generated",),
            )
            matcher = ScopeMatcher(config)

            self.assertTrue(matcher.decide(service).included)
            self.assertFalse(matcher.decide(skipped).included)
            self.assertFalse(matcher.decide(outside).included)
            self.assertIn("exclude module", matcher.decide(skipped).reason)

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            config = RuntimeSpyConfig(
                project_root=root,
                source=("src",),
                include_modules=("app.*",),
                exclude_modules=("app.generated.*",),
                exclude_paths=("**/vendor/**",),
            )
            write_config(config)
            loaded = load_config(root)
            self.assertEqual(loaded.source, ("src",))
            self.assertEqual(loaded.include_modules, ("app.*",))
            self.assertIn("**/vendor/**", loaded.exclude_paths)


if __name__ == "__main__":
    unittest.main()
