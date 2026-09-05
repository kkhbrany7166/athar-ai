"""Isolated environment-loading regression tests using synthetic credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class EnvironmentTests(unittest.TestCase):
    def check_loading(self, *, existing: bool = False, missing: bool = False) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "project"
            package = root / "athar"
            package.mkdir(parents=True)
            (package / "__init__.py").touch()
            shutil.copyfile(Path(__file__).resolve().parents[1] / "athar" / "config.py", package / "config.py")
            if not missing:
                (root / ".env").write_text("OPENAI_API_KEY=synthetic-project-value\n", encoding="utf-8")
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / ".env").write_text("OPENAI_API_KEY=wrong-directory-value\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.pop("OPENAI_API_KEY", None)
            environment.pop("PYTHON_DOTENV_DISABLED", None)
            environment["PYTHONPATH"] = str(root)
            if existing:
                environment["OPENAI_API_KEY"] = "synthetic-shell-value"
            expected = "synthetic-shell-value" if existing else None if missing else "synthetic-project-value"
            code = (
                "import os; from pathlib import Path; import athar.config as config; "
                f"assert config.PROJECT_ROOT == Path({str(root)!r}); "
                f"assert os.environ.get('OPENAI_API_KEY') == {expected!r}"
            )
            result = subprocess.run([sys.executable, "-c", code], cwd=elsewhere,
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, "Environment loading subprocess failed")
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")

    def test_project_env_loads_from_unrelated_working_directory(self):
        self.check_loading()

    def test_existing_environment_takes_precedence(self):
        self.check_loading(existing=True)

    def test_missing_project_env_does_not_discover_another_env(self):
        self.check_loading(missing=True)
