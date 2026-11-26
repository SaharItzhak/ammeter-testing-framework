from __future__ import annotations

import html
import re
import webbrowser
from pathlib import Path

from typing import TYPE_CHECKING

from src.testing.history import format_timestamp, format_timing
from src.testing.test_framework import coefficient_of_variation

if TYPE_CHECKING:
    from src.testing.history import HistoryRecord

STATISTICS = (
    ("mean", "Mean"),
    ("median", "Median"),
    ("standard_deviation", "Standard deviation"),
    ("minimum", "Minimum"),
    ("maximum", "Maximum"),
)


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _measurement_rows(record: HistoryRecord) -> str:
    measurements = record["result"]["measurements"]
    if not measurements:
        return '<tr><td colspan="3" class="empty-cell">No measurements were collected.</td></tr>'
    return "".join(
        "<tr>"
        f'<td dir="ltr">{index}</td>'
        f'<td dir="ltr">{measurement["elapsed_seconds"]:.3f} s</td>'
        f'<td dir="ltr">{_format_number(measurement["current_amperes"])} A</td>'
        "</tr>"
        for index, measurement in enumerate(measurements, 1)
    )


def _statistics_rows(record: HistoryRecord) -> str:
    statistics = record["result"]["statistics"]
    if statistics is None:
        return '<p class="muted">No statistics are available for this run.</p>'
    rows = "".join(
        f"<div><dt>{label}</dt><dd dir=\"ltr\">"
        f"{_format_number(statistics[key])} A</dd></div>"
        for key, label in STATISTICS
    )
    variation = coefficient_of_variation(statistics)
    value = (
        "unavailable (mean is zero)"
        if variation is None
        else f"{_format_number(variation)}%"
    )
    return (
        f"{rows}<div><dt>Coefficient of variation</dt>"
        f"<dd dir=\"ltr\">{value}</dd></div>"
    )


def _measurement_chart(record: HistoryRecord) -> str:
    measurements = record["result"]["measurements"]
    if not measurements:
        return ""
    times = [measurement["elapsed_seconds"] for measurement in measurements]
    currents = [measurement["current_amperes"] for measurement in measurements]
    min_time, max_time = min(times), max(times)
    min_current, max_current = min(currents), max(currents)

    def position(value: float, lower: float, upper: float) -> float:
        if lower == upper:
            return 0.5
        scale = max(abs(lower), abs(upper))
        return (value / scale - lower / scale) / (upper / scale - lower / scale)

    points = [
        (85 + 375 * position(t, min_time, max_time),
         150 - 120 * position(current, min_current, max_current))
        for t, current in zip(times, currents)
    ]
    coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    dots = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" />' for x, y in points)
    return (
        '<figure class="measurement-chart"><figcaption>Current over elapsed time</figcaption>'
        '<svg viewBox="0 0 480 200" role="img" aria-label="Current in amperes over elapsed time in seconds. '
        'Exact values are listed in the measurements table.">'
        '<path d="M85 20 V150 H460" fill="none" stroke="#64748b" />'
        f'<polyline points="{coordinates}" fill="none" stroke="#175cd3" stroke-width="2" />'
        f'<g fill="#175cd3">{dots}</g>'
        f'<text x="80" y="24" text-anchor="end">{_escape(_format_number(max_current))} A</text>'
        f'<text x="80" y="154" text-anchor="end">{_escape(_format_number(min_current))} A</text>'
        f'<text x="85" y="173">{_escape(_format_number(min_time))} s</text>'
        f'<text x="460" y="173" text-anchor="end">{_escape(_format_number(max_time))} s</text>'
        '</svg></figure>'
    )


def _reference_assessment(record: HistoryRecord) -> str:
    measurements = record["result"]["measurements"]
    if not measurements:
        return ""
    currents = ",".join(str(item["current_amperes"]) for item in measurements)
    return (
        f'<div class="reference-assessment" data-currents="{_escape(currents)}">'
        '<h4>Assess against a reference</h4>'
        '<p class="muted">Use a known constant current measured under the same conditions. '
        'The reference is not saved; emulator values do not supply a known reference.</p>'
        '<label>Reference current (A)<input class="reference-current" type="number" step="any" '
        'placeholder="Enter a known current"></label>'
        '<button class="assess-reference" type="button">Assess measurements</button>'
        '<p class="reference-result" aria-live="polite"></p></div>'
    )


def _run_row(record: HistoryRecord) -> str:
    result = record["result"]
    parameters = record["parameters"]
    run_id = record["id"]
    ammeter = result["ammeter"]
    statistics = result["statistics"]
    mean = "" if statistics is None else _format_number(statistics["mean"])
    consistency_note = (
        '<p class="muted">Lower variation means more consistent readings, '
        'not greater accuracy.</p>'
        if statistics is not None
        else ""
    )
    status = "Failed (partial)" if result["stop_reason"] == "error" else "Completed"
    failure = (
        f'<p class="failure">Failed: {_escape(result["error"])}. Measurements below are partial.</p>'
        if result.get("error") else ""
    )
    details = (
        f'<details><summary>Run details</summary>'
        '<div class="run-meta">'
        f'<div><span>Started</span><strong dir="ltr">{_escape(format_timestamp(record["started_at"]))}</strong></div>'
        f'<div><span>Elapsed</span><strong dir="ltr">{result["elapsed_seconds"]:.3f} s</strong></div>'
        f'<div><span>Stop reason</span><strong>{_escape(result["stop_reason"])}</strong></div>'
        f'<div><span>Sampling settings</span><strong dir="ltr">{parameters["measurements_count"]} measurements · '
        f'{parameters["total_duration_seconds"]:g} s · {parameters["sampling_frequency_hz"]:g} Hz</strong></div>'
        "</div>"
        f'{failure}<p class="muted">{_escape(format_timing(result, parameters["sampling_frequency_hz"]))}</p>'
        f'<dl class="stats">{_statistics_rows(record)}</dl>'
        f'{consistency_note}'
        f'{_measurement_chart(record)}'
        f'{_reference_assessment(record)}'
        '<h4>Measurements</h4><div class="table-scroll"><table>'
        "<thead><tr><th>#</th><th>Time</th><th>Current</th></tr></thead>"
        f"<tbody>{_measurement_rows(record)}</tbody></table></div>"
        "</details>"
    )
    return (
        f'<tr data-run-id="{_escape(run_id)}" data-ammeter="{_escape(ammeter)}" '
        f'data-mean="{_escape(mean)}">'
        f'<td class="run-id" dir="ltr">{_escape(run_id)}</td>'
        f"<td>{_escape(ammeter.title())}</td>"
        f'<td dir="ltr">{_escape(format_timestamp(record["saved_at"]))}</td>'
        f"<td>{status}</td>"
        f'<td dir="ltr">{len(result["measurements"])}</td>'
        f'<td dir="ltr">{_escape(mean + " A" if mean else "—")}</td>'
        f"<td>{details}</td>"
        "</tr>"
    )


def _comparison_options(records: list[HistoryRecord]) -> str:
    options = []
    for record in records:
        statistics = record["result"]["statistics"] or {}
        attrs = " ".join(
            f'data-{key.replace("_", "-")}="{_escape(statistics.get(key, ""))}"'
            for key, _ in STATISTICS
        )
        title = (
            f'{record["result"]["ammeter"].title()} · '
            f'{"Failed (partial) · " if record["result"]["stop_reason"] == "error" else ""}'
            f'{format_timestamp(record["saved_at"])} · {record["id"][:8]}'
        )
        options.append(
            f'<option value="{_escape(record["id"])}" {attrs}>{_escape(title)}</option>'
        )
    return "".join(options)


def _render_html(records: list[HistoryRecord]) -> str:
    ammeters = sorted({record["result"]["ammeter"] for record in records})
    meter_options = "".join(
        f'<option value="{_escape(ammeter)}">{_escape(ammeter.title())}</option>'
        for ammeter in ammeters
    )
    rows = "".join(_run_row(record) for record in records)
    latest = format_timestamp(records[0]["saved_at"]) if records else "—"
    empty_state = (
        ""
        if records
        else (
            '<div class="empty-state"><div class="empty-icon" aria-hidden="true">↗</div>'
            "<h2>No history yet</h2>"
            "<p>Run your first test to see measurements and a summary here.</p>"
            "<code dir=\"ltr\">python main.py</code></div>"
        )
    )
    disabled = " disabled" if len(records) < 2 else ""
    compare_note = (
        ""
        if len(records) >= 2
        else '<p class="muted">Save at least two runs to compare them.</p>'
    )
    values = {
        "TOTAL_RUNS": str(len(records)),
        "AMMETER_COUNT": str(len(ammeters)),
        "LATEST": _escape(latest),
        "EMPTY_STATE": empty_state,
        "HISTORY_HIDDEN": " hidden" if not records else "",
        "METER_OPTIONS": meter_options,
        "ROWS": rows,
        "DISABLED": disabled,
        "COMPARISON_OPTIONS": _comparison_options(records),
        "COMPARE_NOTE": compare_note,
    }
    template = Path(__file__).with_name("history_template.html").read_text(encoding="utf-8")
    return re.sub(r"@@([A-Z_]+)@@", lambda match: values[match.group(1)], template)


def generate_report(database_path: Path) -> Path:
    from src.testing.history import HistoryStore

    store = HistoryStore(database_path)
    records = store.list_records()
    database_path = Path(database_path)
    report_path = database_path.with_suffix(".html")
    if report_path.resolve() == database_path.resolve():
        report_path = database_path.with_name(database_path.name + ".report.html")
    if report_path.exists() and database_path.exists() and report_path.samefile(database_path):
        raise ValueError("Report path refers to the history database; refusing to overwrite it")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_html(records), encoding="utf-8")
    return report_path


def open_report(database_path: Path) -> str:
    report_path = generate_report(database_path)
    try:
        opened = webbrowser.open(report_path.resolve().as_uri())
    except (OSError, webbrowser.Error) as error:
        return (
            f"Report saved to {report_path}, but the browser could not be opened: {error}"
        )
    if opened:
        return f"History report opened in your browser: {report_path}"
    return f"History report saved to {report_path}. Open this file in a browser to view it."
