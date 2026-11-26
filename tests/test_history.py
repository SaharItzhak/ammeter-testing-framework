from contextlib import closing
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
from src.testing.report import generate_report
from src.testing.test_framework import SamplingFailure

TEST_RUNTIME_CONFIG = {
    "sampling": {
        "measurements_count": 1,
        "total_duration_seconds": 5.0,
        "sampling_frequency_hz": 1.0,
    },
    "ports": {"greenlee": 5001, "entes": 5002, "circutor": 5003},
    "history_database": Path("unused-history.sqlite3"),
}


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
        self.assertEqual(self.store.list_runs(), [])
        self.assertFalse(self.path.exists())
        with self.assertRaisesRegex(KeyError, "No saved runs"):
            self.store.get("missing")

    def test_list_command_explains_empty_history(self):
        base = [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path)]
        completed = subprocess.run(base + ["list"], capture_output=True, text=True, timeout=10)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("No saved runs yet", completed.stdout)
        self.assertIn("python main.py", completed.stdout)
        self.assertFalse(self.path.exists())

    def test_show_and_compare_without_history_give_actionable_errors(self):
        base = [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path)]
        for args in (["show", "missing"], ["compare", "first", "second"]):
            with self.subTest(command=args[0]):
                completed = subprocess.run(
                    base + args, capture_output=True, text=True, timeout=10
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("No saved runs yet", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_empty_database_is_reported_as_no_runs(self):
        self.save("greenlee", 1.0)
        self.path.unlink()
        with closing(sqlite3.connect(self.path)):
            pass

        completed = subprocess.run(
            [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path), "list"],
            capture_output=True, text=True, timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("No saved runs yet", completed.stdout)

    def test_corrupt_database_has_a_concise_error(self):
        self.path.write_bytes(b"not a SQLite database")
        completed = subprocess.run(
            [
                sys.executable, "-B", "-m", "src.testing.history",
                "--database", str(self.path), "list",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("History error:", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_duplicate_id_does_not_overwrite_existing_run(self):
        with patch("src.testing.history.uuid.uuid4", return_value=uuid.UUID(int=1)):
            first = self.save("greenlee", 1.0)
            with self.assertRaises(sqlite3.IntegrityError):
                self.save("entes", 3.0)

        self.assertEqual(self.store.get(first["id"]), first)
        self.assertEqual(len(self.store.list_runs()), 1)

    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.AmmeterTestFramework")
    @patch("main.GreenleeAmmeter.start_server")
    def test_main_saves_successful_run(self, start_server, framework_factory, runtime_config):
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

    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.request_current_from_ammeter", side_effect=[1.0, 3.0, TimeoutError("lost connection")])
    @patch("main.GreenleeAmmeter.start_server")
    def test_main_saves_partial_failed_run_and_preserves_history(self, start_server, request, config):
        earlier = self.save("entes", 4.0)
        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError("Server was not stopped")
        start_server.side_effect = serve
        with self.assertRaisesRegex(RuntimeError, "partial results saved as run") as raised:
            main.main("greenlee", count=3, duration=5, frequency=100, database=self.path)

        runs = self.store.list_runs()
        failed = next(run for run in runs if run["status"] == "failed")
        record = self.store.get(failed["id"])
        self.assertIn(failed["id"], str(raised.exception))
        self.assertEqual(self.store.get(earlier["id"]), earlier)
        self.assertEqual(record["result"]["stop_reason"], "error")
        self.assertIn("lost connection", record["result"]["error"])
        self.assertEqual(len(record["result"]["measurements"]), 2)
        report = generate_report(self.path).read_text(encoding="utf-8")
        self.assertIn("Failed (partial)", report)
        self.assertIn("lost connection", report)
        self.assertIn("max absolute deviation", report)
        base = [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path)]
        listed = subprocess.run(base + ["list"], capture_output=True, text=True, timeout=10)
        shown = subprocess.run(base + ["show", failed["id"]], capture_output=True, text=True, timeout=10)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("failed", listed.stdout)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Failure: TimeoutError: lost connection (partial results)", shown.stdout)
        self.assertIn("max absolute deviation", shown.stdout)

    def test_cli_returns_failure_and_saves_partial_results(self):
        run_cli = (
            "import runpy; from unittest.mock import patch\n"
            "def serve(self, ready, stop):\n"
            "    ready.set()\n"
            "    stop.wait(3)\n"
            "with patch('Ammeters.Greenlee_Ammeter.GreenleeAmmeter.start_server', serve), "
            "patch('Ammeters.client.request_current_from_ammeter', "
            "side_effect=[1.0, OSError('connection lost')]):\n"
            "    runpy.run_path('main.py', run_name='__main__')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", run_cli, "--ammeter", "greenlee",
             "--database", str(self.path), "--count", "3", "--frequency", "100"],
            capture_output=True, text=True, timeout=10,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("partial results saved as run", completed.stderr)
        self.assertIn("connection lost", completed.stderr)
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(len(self.store.get(runs[0]["id"])["result"]["measurements"]), 1)

    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.HistoryStore.save", side_effect=OSError("disk full"))
    @patch("main.AmmeterTestFramework")
    @patch("main.GreenleeAmmeter.start_server")
    def test_partial_save_failure_reports_original_and_storage_errors(
        self, start_server, framework_factory, save, config
    ):
        def serve(ready, stop):
            ready.set()
            stop.wait(3)
        start_server.side_effect = serve
        partial = result("greenlee", 1.0)
        partial["stop_reason"] = "error"
        partial["error"] = "TimeoutError: connection lost"
        framework_factory.return_value.run_test.side_effect = SamplingFailure(
            partial["error"], partial
        )
        with self.assertRaisesRegex(RuntimeError, "connection lost.*could not save partial results: disk full"):
            main.main("greenlee", count=3, duration=5, frequency=1, database=self.path)

    def test_history_cli_lists_shows_and_compares_runs(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        base = [sys.executable, "-B", "-m", "src.testing.history", "--database", str(self.path)]
        outputs = {}
        for args in (["list"], ["show", first["id"]], ["compare", first["id"], second["id"]]):
            with self.subTest(command=args[0]):
                completed = subprocess.run(base + args, capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip())
                outputs[args[0]] = completed.stdout
        self.assertIn(first["id"], outputs["list"])
        self.assertIn("Statistics:", outputs["show"])
        self.assertIn("Run comparison", outputs["compare"])
        self.assertIn("DIFFERENCE", outputs["compare"])
        missing = subprocess.run(base + ["show", "missing"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("Use `list`", missing.stderr)

    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.AmmeterTestFramework")
    @patch("main.GreenleeAmmeter.start_server")
    def test_main_does_not_save_a_run_without_measurements(
        self, start_server, framework_factory, runtime_config
    ):
        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError("Server was not stopped")

        start_server.side_effect = serve
        empty_result = result("greenlee", 1.0)
        empty_result["measurements"] = []
        empty_result["statistics"] = None
        framework_factory.return_value.run_test.return_value = empty_result
        with self.assertRaisesRegex(RuntimeError, "no history record was saved"):
            main.main("greenlee", count=1, duration=5, frequency=1, database=self.path)

        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
