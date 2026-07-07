import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectScaffoldingTest(unittest.TestCase):
    def test_root_package_scripts_point_to_existing_python_files(self):
        package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        for script_name, command in package_json.get("scripts", {}).items():
            script_path = next((part for part in command.split() if part.endswith(".py")), "")
            with self.subTest(script=script_name):
                self.assertTrue(script_path, f"{script_name} should invoke a Python script")
                self.assertTrue((ROOT / script_path).exists(), f"{script_path} does not exist")

    def test_root_package_main_points_to_existing_file(self):
        package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertTrue((ROOT / package_json["main"]).exists())

    def test_web_typescript_configs_are_trackable(self):
        for relative_path in ("web/tsconfig.json", "web/tsconfig.node.json"):
            with self.subTest(path=relative_path):
                result = subprocess.run(
                    ["git", "check-ignore", "-q", relative_path],
                    cwd=ROOT,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, f"{relative_path} is ignored by git")

    def test_default_unittest_discovery_can_enter_tests_directory(self):
        self.assertTrue((ROOT / "tests" / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
