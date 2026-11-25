from contextlib import redirect_stdout
from io import StringIO
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
        self.assertIn("עוד אין היסטוריה", report)
        self.assertIn("python main.py", report)
        self.assertFalse(self.database.exists())

    def test_report_contains_runs_and_escapes_untrusted_history_text(self):
        self.save('<img src=x onerror="alert(1)">')

        report = generate_report(self.database).read_text(encoding="utf-8")

        self.assertIn("היסטוריית בדיקות אמפר", report)
        self.assertIn("1.25 A", report)
        self.assertIn("הגדרות דגימה", report)
        self.assertIn("5 שנ׳", report)
        self.assertIn("data-mean=", report)
        self.assertIn("&lt;img", report)
        self.assertNotIn('<img src=x onerror="alert(1)">', report)

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
