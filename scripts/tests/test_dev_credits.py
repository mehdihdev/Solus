"""The local launcher reads data only, with a narrow UUID-only schema."""

import json
import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class DevCreditConfigTests(unittest.TestCase):
    def test_local_config(self) -> None:
        read = runpy.run_path(str(Path(__file__).parents[1] / "dev_credits.py"))["read_allowlist"]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "credits.json"
            self.assertEqual(read(path), "")
            identity = "01a002ca-da5b-7960-be81-6eddcdd5be6d"
            path.write_text(json.dumps({"user_ids": [identity]}))
            self.assertEqual(read(path), identity)
            for value in (
                {"user_ids": ["bad"]},
                {"user_ids": identity},
                {"user_ids": [], "extra": True},
                ["bad"],
            ):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    read(path)

    def test_invalid_json_and_size(self) -> None:
        read = runpy.run_path(str(Path(__file__).parents[1] / "dev_credits.py"))["read_allowlist"]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "credits.json"
            for raw in ("{", " " * 16385):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    read(path)
