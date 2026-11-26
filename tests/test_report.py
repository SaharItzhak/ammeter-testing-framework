from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os

import pytest

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


@pytest.fixture
def report_context(tmp_path):
    database = tmp_path / "history.sqlite3"
    store = HistoryStore(database)
    parameters = {
        "measurements_count": 1,
        "total_duration_seconds": 5.0,
        "sampling_frequency_hz": 1.0,
    }
    return database, store, parameters


def save(store, parameters, ammeter):
    return store.save(sample_result(ammeter), parameters, "2026-01-01T00:00:00+00:00")


def test_empty_history_has_a_clear_dashboard_state(report_context):
    database, _, _ = report_context
    report_path = generate_report(database)
    report = report_path.read_text(encoding="utf-8")

    assert report_path == database.with_suffix(".html")
    assert '<html lang="en" dir="ltr">' in report
    assert "No history yet" in report
    assert "python main.py" in report
    assert not database.exists()


def test_report_contains_runs_and_escapes_untrusted_history_text(report_context):
    database, store, parameters = report_context
    save(store, parameters, '<img src=x onerror="alert(1)">')

    report = generate_report(database).read_text(encoding="utf-8")

    assert "Ammeter test history" in report
    assert not any("\u0590" <= character <= "\u05ff" for character in report)
    assert "1.25 A" in report
    assert "Sampling settings" in report
    assert "Coefficient of variation" in report
    assert "not greater accuracy" in report
    assert "5 s" in report
    assert "data-mean=" in report
    assert "&lt;img" in report
    assert '<img src=x onerror="alert(1)">' not in report
    assert database.is_file()
    assert len(store.list_runs()) == 1


def test_chart_plots_measurements_and_handles_constant_values(report_context):
    database, store, parameters = report_context
    result = sample_result("greenlee")
    result["measurements"].append({"elapsed_seconds": 1.25, "current_amperes": 1.25})
    store.save(result, parameters, "2026-01-01T00:00:00+00:00")

    report = generate_report(database).read_text(encoding="utf-8")

    assert "Current over elapsed time" in report
    assert 'points="85.00,90.00 460.00,90.00"' in report
    assert "0.25 s" in report
    assert "1.25 A" in report
    assert 'data-currents="1.25,1.25"' in report
    assert "Reference current (A)" in report


def test_chart_scales_varying_measurements(report_context):
    database, store, parameters = report_context
    result = sample_result("greenlee")
    result["measurements"].append({"elapsed_seconds": 1.25, "current_amperes": 3.25})
    store.save(result, parameters, "2026-01-01T00:00:00+00:00")

    report = generate_report(database).read_text(encoding="utf-8")

    assert 'points="85.00,150.00 460.00,30.00"' in report


def test_html_database_is_not_overwritten_by_report(report_context):
    database, _, parameters = report_context
    database = database.with_suffix(".html")
    store = HistoryStore(database)
    saved = store.save(sample_result("greenlee"), parameters, "2026-01-01T00:00:00+00:00")
    original = database.read_bytes()

    report = generate_report(database)

    assert report.name == "history.html.report.html"
    assert report.is_file()
    assert database.read_bytes() == original
    assert store.get(saved["id"]) == saved


def test_report_refuses_to_overwrite_a_hard_link_to_database(report_context):
    database, store, parameters = report_context
    save(store, parameters, "greenlee")
    report = database.with_suffix(".html")
    try:
        os.link(database, report)
    except OSError as error:
        pytest.skip(f"Hard links unavailable: {error}")
    original = database.read_bytes()

    with pytest.raises(ValueError, match="refusing to overwrite"):
        generate_report(database)
    assert database.read_bytes() == original
    assert len(store.list_runs()) == 1


@pytest.mark.parametrize("opens_browser", [True, False])
def test_open_report_launches_local_file(report_context, monkeypatch, opens_browser):
    database, _, _ = report_context
    browser_open = lambda url: opens_browser
    monkeypatch.setattr("src.testing.report.webbrowser.open", browser_open)

    message = open_report(database)

    if opens_browser:
        assert "opened in your browser" in message
    else:
        assert str(database.with_suffix(".html")) in message
        assert "Open this file in a browser" in message


def test_history_report_command_opens_empty_dashboard(report_context, monkeypatch, capsys):
    database, _, _ = report_context
    monkeypatch.setattr("src.testing.report.webbrowser.open", lambda url: True)
    monkeypatch.setattr("sys.argv", ["history", "--database", str(database), "report"])

    history_main()
    output = capsys.readouterr().out

    assert "opened in your browser" in output
    assert database.with_suffix(".html").is_file()


def test_corrupt_database_report_returns_a_clear_error(report_context, monkeypatch, capsys):
    database, _, _ = report_context
    database.write_bytes(b"not a SQLite database")
    monkeypatch.setattr("sys.argv", ["history", "--database", str(database), "report"])

    with pytest.raises(SystemExit) as raised:
        history_main()

    assert raised.value.code == 2
    output = capsys.readouterr().err
    assert "History error:" in output
    assert "Traceback" not in output
