"""Synthetic checks for confidential artifact classes, without real organizer fingerprints."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/check_public_confidentiality.py"
spec = importlib.util.spec_from_file_location("public_confidentiality", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfidentialityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.unit = self.root / "units/SYN-PRACTICE"
        self.unit.mkdir(parents=True)
        (self.unit / "card.toml").write_text('[task]\nsplit="public-dev"\n')

    def test_practice_reference_values_are_allowed(self):
        target = self.unit / "checks/reference_data/expected.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"expected": 1.0}')
        self.assertEqual(module.check(self.root), [])

    def test_non_public_and_malformed_cards_refuse(self):
        for text in ('[task]\nsplit="private-test"', 'not toml', '[other]\nx=1'):
            with self.subTest(text=text):
                (self.unit / "card.toml").write_text(text)
                self.assertTrue(module.check(self.root))

    def test_renamed_nested_roster_export_refuses(self):
        for key in module.ROSTER_KEYS:
            with self.subTest(key=key):
                (self.root / "unrelated.data").write_text(json.dumps({"nested": [{key: ["SYNTHETIC"]}]}))
                self.assertIn("roster export structure is present", module.check(self.root))

    def test_solution_and_registry_classes_refuse(self):
        for name in ("model_solution.py", "oracle_model.bin", "answer_key.csv", "canary_registry.backup"):
            with self.subTest(name=name):
                path = self.unit / name
                path.write_text("synthetic")
                self.assertIn("solution or registry artifact is present", module.check(self.root))
                path.unlink()

    def test_symlink_and_empty_scan_refuse(self):
        (self.unit / "link").symlink_to("card.toml")
        self.assertTrue(module.check(self.root))
        (self.unit / "link").unlink()
        (self.unit / "card.toml").unlink()
        self.assertTrue(module.check(self.root))


if __name__ == "__main__":
    unittest.main()
