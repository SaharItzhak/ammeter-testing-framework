from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.testing.history import HistoryStore, main as history_main
from src.testing.report import generate_report, open_report


def sample_result(ammeter):
    return {
        "ammeter": ammeter,
        "measurements": [{"elapsed_seconds": 0.25, "current_amperes": 1.25}],
        "elapsed_seconds": 0.25,
        "stop_reason": "count",
        "statistics": {
            "mean": 1.25,
            "median": 1.25,
            "standard_deviation": 0.0,
            "minimum": 1.25,
            "maximum": 1.25,
        },
    }


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "history.sqlite3"
        self.store = HistoryStore(self.database)
        self.parameters = {
            "measurements_count": 1,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 1.0,
        }

    def save(self, ammeter):
        return self.store.save(
            sample_result(ammeter),
            self.parameters,
            "2026-01-01T00:00:00+00:00",
        )

    def test_empty_history_has_a_clear_dashboard_state(self):
        report_path = generate_report(self.database)
        report = report_path.read_text(encoding="utf-8")

        self.assertEqual(report_path, self.database.with_suffix(".html"))
        self.assertIn('<html lang="en" dir="ltr">', report)
        self.assertIn("No history yet", report)
        self.assertIn("python main.py", report)
        self.assertFalse(self.database.exists())

    def test_report_contains_runs_and_escapes_untrusted_history_text(self):
        self.save('<img src=x onerror="alert(1)">')

        report = generate_report(self.database).read_text(encoding="utf-8")

        self.assertIn("Ammeter test history", report)
        self.assertNotRegex(report, r"[\u0590-\u05FF]")
        self.assertIn("1.25 A", report)
        self.assertIn("Sampling settings", report)
        self.assertIn("5 s", report)
        self.assertIn("data-mean=", report)
        self.assertIn("&lt;img", report)
        self.assertNotIn('<img src=x onerror="alert(1)">', report)
        self.assertTrue(self.database.is_file())
        self.assertEqual(len(self.store.list_runs()), 1)

    def test_chart_plots_measurements_and_handles_constant_values(self):
        result = sample_result("greenlee")
        result["measurements"].append({"elapsed_seconds": 1.25, "current_amperes": 1.25})
        self.store.save(result, self.parameters, "2026-01-01T00:00:00+00:00")

        report = generate_report(self.database).read_text(encoding="utf-8")

        self.assertIn("Current over elapsed time", report)
        self.assertIn('points="85.00,90.00 460.00,90.00"', report)
        self.assertIn("0.25 s", report)
        self.assertIn("1.25 A", report)
        self.assertIn('data-currents="1.25,1.25"', report)
        self.assertIn("Reference current (A)", report)

    def test_chart_scales_varying_measurements(self):
        result = sample_result("greenlee")
        result["measurements"].append({"elapsed_seconds": 1.25, "current_amperes": 3.25})
        self.store.save(result, self.parameters, "2026-01-01T00:00:00+00:00")

        report = generate_report(self.database).read_text(encoding="utf-8")

        self.assertIn('points="85.00,150.00 460.00,30.00"', report)

    def test_html_database_is_not_overwritten_by_report(self):
        database = self.database.with_suffix(".html")
        store = HistoryStore(database)
        saved = store.save(sample_result("greenlee"), self.parameters, "2026-01-01T00:00:00+00:00")
        original = database.read_bytes()

        report = generate_report(database)

        self.assertEqual(report.name, "history.html.report.html")
        self.assertTrue(report.is_file())
        self.assertEqual(database.read_bytes(), original)
        self.assertEqual(store.get(saved["id"]), saved)

    def test_report_refuses_to_overwrite_a_hard_link_to_database(self):
        self.save("greenlee")
        report = self.database.with_suffix(".html")
        try:
            os.link(self.database, report)
        except OSError as error:
            self.skipTest(f"Hard links unavailable: {error}")
        original = self.database.read_bytes()

        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            generate_report(self.database)
        self.assertEqual(self.database.read_bytes(), original)
        self.assertEqual(len(self.store.list_runs()), 1)

    @patch("src.testing.report.webbrowser.open", return_value=True)
    def test_open_report_launches_local_file(self, browser_open):
        message = open_report(self.database)

        browser_open.assert_called_once_with(self.database.with_suffix(".html").resolve().as_uri())
        self.assertIn("opened in your browser", message)

    @patch("src.testing.report.webbrowser.open", return_value=True)
    def test_history_report_command_opens_empty_dashboard(self, browser_open):
        output = StringIO()
        with patch("sys.argv", ["history", "--database", str(self.database), "report"]):
            with redirect_stdout(output):
                history_main()

        self.assertIn("opened in your browser", output.getvalue())
        self.assertTrue(self.database.with_suffix(".html").is_file())
        browser_open.assert_called_once()

    @patch("src.testing.report.webbrowser.open", return_value=False)
    def test_browser_unavailable_leaves_report_path(self, browser_open):
        message = open_report(self.database)

        self.assertIn(str(self.database.with_suffix(".html")), message)
        self.assertIn("Open this file in a browser", message)

    def test_corrupt_database_report_returns_a_clear_error(self):
        self.database.write_bytes(b"not a SQLite database")
        output = StringIO()
        with patch("sys.argv", ["history", "--database", str(self.database), "report"]):
            with redirect_stderr(output):
                with self.assertRaises(SystemExit) as raised:
                    history_main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("History error:", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
