import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import main
from src.testing.history import HistoryStore


def result(ammeter, value):
    return {
        "ammeter": ammeter,
        "measurements": [{"elapsed_seconds": 0.0, "current_amperes": value}],
        "elapsed_seconds": 0.1,
        "stop_reason": "count",
        "statistics": {
            "mean": value, "median": value, "standard_deviation": 0.0,
            "minimum": value, "maximum": value,
        },
    }


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runs.sqlite3"
        self.store = HistoryStore(self.path)
        self.parameters = {
            "measurements_count": 1,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 1.0,
        }

    def save(self, ammeter, value):
        return self.store.save(
            result(ammeter, value), self.parameters, "2026-01-01T00:00:00+00:00"
        )

    def test_runs_persist_with_metadata_and_measurements(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        reopened = HistoryStore(self.path)

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(reopened.get(first["id"]), first)
        self.assertEqual(first["parameters"], self.parameters)
        self.assertEqual(first["result"]["measurements"][0]["current_amperes"], 1.0)
        self.assertEqual({run["id"] for run in reopened.list_runs()}, {first["id"], second["id"]})

    def test_comparison_preserves_both_runs_and_calculates_differences(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        comparison = self.store.compare(first["id"], second["id"])

        self.assertEqual(comparison["first"], first)
        self.assertEqual(comparison["second"], second)
        self.assertEqual(comparison["second_minus_first"]["mean"], 2.0)
        self.assertEqual(comparison["second_minus_first"]["standard_deviation"], 0.0)

    def test_comparison_without_statistics_does_not_invent_differences(self):
        first = self.save("greenlee", 1.0)
        empty_result = result("entes", 3.0)
        empty_result["measurements"] = []
        empty_result["statistics"] = None
        second = self.store.save(empty_result, self.parameters, "2026-01-01T00:00:00+00:00")

        self.assertIsNone(self.store.compare(first["id"], second["id"])["second_minus_first"])

    def test_missing_database_and_run_are_reported(self):
        with self.assertRaises(FileNotFoundError):
            self.store.list_runs()
        self.assertFalse(self.path.exists())
        self.save("greenlee", 1.0)
        with self.assertRaisesRegex(KeyError, "Run not found"):
            self.store.get("missing")

    def test_duplicate_id_does_not_overwrite_existing_run(self):
        with patch("src.testing.history.uuid.uuid4", return_value=uuid.UUID(int=1)):
            first = self.save("greenlee", 1.0)
            with self.assertRaises(sqlite3.IntegrityError):
                self.save("entes", 3.0)

        self.assertEqual(self.store.get(first["id"]), first)
        self.assertEqual(len(self.store.list_runs()), 1)

    @patch("main.AmmeterTestFramework")
    @patch("main.GreenleeAmmeter.start_server")
    def test_main_saves_successful_run(self, start_server, framework_factory):
        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError("Server was not stopped")

        start_server.side_effect = serve
        framework_factory.return_value.run_test.return_value = result("greenlee", 1.0)
        main.main("greenlee", count=1, duration=5, frequency=1, database=self.path)

        runs = self.store.list_runs()
        self.assertEqual(len(runs), 1)
        saved = self.store.get(runs[0]["id"])
        self.assertEqual(saved["result"], result("greenlee", 1.0))
        self.assertEqual(saved["parameters"], self.parameters)

    def test_history_cli_lists_shows_and_compares_runs(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        base = [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path)]
        for args in (["list"], ["show", first["id"]], ["compare", first["id"], second["id"]]):
            with self.subTest(command=args[0]):
                completed = subprocess.run(base + args, capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(json.loads(completed.stdout))
        missing = subprocess.run(base + ["show", "missing"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("Run not found", missing.stderr)


if __name__ == "__main__":
    unittest.main()
