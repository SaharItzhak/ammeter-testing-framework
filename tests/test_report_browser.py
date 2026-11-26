import tempfile
import unittest
import statistics
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError as error:
    if error.name != "playwright":
        raise
    sync_playwright = None

from src.testing.history import HistoryStore
from src.testing.report import generate_report


@unittest.skipUnless(sync_playwright, "Install requirements-dev.txt and Playwright Chromium for browser tests")
class ReportBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        database = Path(self.directory.name) / "history.sqlite3"
        store = HistoryStore(database)
        parameters = {
            "measurements_count": 3,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 2.0,
        }
        def save(ammeter, values):
            return store.save({
                "ammeter": ammeter,
                "measurements": [
                    {"elapsed_seconds": index * 0.5, "current_amperes": value}
                    for index, value in enumerate(values)
                ],
                "elapsed_seconds": 1.0,
                "stop_reason": "count",
                "statistics": {
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "standard_deviation": statistics.pstdev(values),
                    "minimum": min(values),
                    "maximum": max(values),
                },
            }, parameters, "2026-01-01T00:00:00+00:00")
        self.first = save("greenlee", [1.0, 3.0, 5.0])
        self.second = save("entes", [2.0, 2.0, 2.0])
        self.page.goto(generate_report(database).resolve().as_uri())

    def test_graph_and_reference_calculation_in_browser(self):
        row = self.page.locator(f'tr[data-run-id="{self.first["id"]}"]')
        row.locator("summary").click()
        self.assertEqual(row.locator("svg circle").count(), 3)
        self.assertEqual(row.locator("polyline").get_attribute("points"),
                         "85.00,150.00 272.50,90.00 460.00,30.00")
        row.locator(".reference-current").fill("2")
        row.locator(".assess-reference").click()
        self.assertEqual(
            row.locator(".reference-result").inner_text(),
            "Mean error (measured − reference): 1 A; mean absolute error: 1.66667 A; RMSE: 1.91485 A.",
        )
        row.locator(".reference-current").fill("")
        row.locator(".assess-reference").click()
        self.assertEqual(row.locator(".reference-result").inner_text(), "Enter a finite reference current.")

    def test_filter_and_comparison_in_browser(self):
        self.page.locator("#filterAmmeter").select_option("greenlee")
        self.assertEqual(self.page.locator("#visibleCount").inner_text(), "1 runs")
        self.assertTrue(self.page.locator(f'tr[data-run-id="{self.first["id"]}"]').is_visible())
        self.assertTrue(self.page.locator(f'tr[data-run-id="{self.second["id"]}"]').is_hidden())
        self.page.locator("#firstRun").select_option(self.first["id"])
        self.page.locator("#secondRun").select_option(self.second["id"])
        self.page.locator("#compareButton").click()
        self.assertIn("-1 A", self.page.locator("#compareResult").inner_text())
