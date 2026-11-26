import statistics
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_api.sync_playwright

from src.testing.history import HistoryStore
from src.testing.report import generate_report


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except playwright_api.Error as error:
            pytest.skip(f"Install Playwright Chromium to run browser tests: {error}")
        yield browser
        browser.close()


@pytest.fixture
def report_page(tmp_path, browser):
    page = browser.new_page()
    database = tmp_path / "history.sqlite3"
    store = HistoryStore(database)
    parameters = {
        "measurements_count": 3,
        "total_duration_seconds": 5.0,
        "sampling_frequency_hz": 2.0,
    }

    def save(ammeter, values):
        return store.save(
            {
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
            },
            parameters,
            "2026-01-01T00:00:00+00:00",
        )

    first = save("greenlee", [1.0, 3.0, 5.0])
    second = save("entes", [2.0, 2.0, 2.0])
    page.goto(generate_report(database).resolve().as_uri())
    yield page, first, second
    page.close()


def test_graph_and_reference_calculation_in_browser(report_page):
    page, first, _ = report_page
    row = page.locator(f'tr[data-run-id="{first["id"]}"]')
    row.locator("summary").click()
    assert row.locator("svg circle").count() == 3
    assert row.locator("polyline").get_attribute("points") == "85.00,150.00 272.50,90.00 460.00,30.00"
    row.locator(".reference-current").fill("2")
    row.locator(".assess-reference").click()
    assert row.locator(".reference-result").inner_text() == (
        "Mean error (measured − reference): 1 A; mean absolute error: "
        "1.66667 A; RMSE: 1.91485 A."
    )
    row.locator(".reference-current").fill("")
    row.locator(".assess-reference").click()
    assert row.locator(".reference-result").inner_text() == "Enter a finite reference current."


def test_filter_and_comparison_in_browser(report_page):
    page, first, second = report_page
    page.locator("#filterAmmeter").select_option("greenlee")
    assert page.locator("#visibleCount").inner_text() == "1 runs"
    assert page.locator(f'tr[data-run-id="{first["id"]}"]').is_visible()
    assert page.locator(f'tr[data-run-id="{second["id"]}"]').is_hidden()
    page.locator("#firstRun").select_option(first["id"])
    page.locator("#secondRun").select_option(second["id"])
    page.locator("#compareButton").click()
    assert "-1 A" in page.locator("#compareResult").inner_text()
