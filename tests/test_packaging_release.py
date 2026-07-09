from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagingReleaseTests(unittest.TestCase):
    def test_package_data_contract_and_examples_decision_are_explicit(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]

        self.assertIn("examples", wheel["packages"])
        self.assertEqual(wheel["force-include"]["assets/starter.db"], "core/resources/starter.db")
        self.assertEqual(wheel["force-include"]["frontend/dist"], "frontend/dist")
        self.assertEqual(wheel["force-include"]["main.py"], "main.py")

        checklist = (ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
        self.assertIn("examples/` intentionally ships in the wheel", checklist)
        self.assertIn("python scripts/smoke_wheel_install.py", checklist)

    def test_starter_and_frontend_package_paths_exist_in_checkout(self) -> None:
        self.assertTrue((ROOT / "assets" / "starter.db").is_file())
        self.assertTrue((ROOT / "frontend" / "dist").is_dir())
        self.assertTrue(
            (ROOT / "frontend" / "dist" / ".gitkeep").is_file()
            or (ROOT / "frontend" / "dist" / "index.html").is_file()
        )

    def test_wheel_install_smoke_script_when_enabled(self) -> None:
        if os.environ.get("KDG_RUN_PACKAGING_SMOKE") != "1":
            self.skipTest("Set KDG_RUN_PACKAGING_SMOKE=1 to build/install the wheel.")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_wheel_install.py")],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
