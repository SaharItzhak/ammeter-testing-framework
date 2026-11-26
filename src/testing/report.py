from __future__ import annotations

import html
import webbrowser
from pathlib import Path

from typing import TYPE_CHECKING

from src.testing.history import format_timing

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


def _format_timestamp(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", " UTC")


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
    return "".join(
        f"<div><dt>{label}</dt><dd dir=\"ltr\">"
        f"{_format_number(statistics[key])} A</dd></div>"
        for key, label in STATISTICS
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
    status = "Failed (partial)" if result["stop_reason"] == "error" else "Completed"
    failure = (
        f'<p class="failure">Failed: {_escape(result["error"])}. Measurements below are partial.</p>'
        if result.get("error") else ""
    )
    details = (
        f'<details><summary>Run details</summary>'
        '<div class="run-meta">'
        f'<div><span>Started</span><strong dir="ltr">{_escape(_format_timestamp(record["started_at"]))}</strong></div>'
        f'<div><span>Elapsed</span><strong dir="ltr">{result["elapsed_seconds"]:.3f} s</strong></div>'
        f'<div><span>Stop reason</span><strong>{_escape(result["stop_reason"])}</strong></div>'
        f'<div><span>Sampling settings</span><strong dir="ltr">{parameters["measurements_count"]} measurements · '
        f'{parameters["total_duration_seconds"]:g} s · {parameters["sampling_frequency_hz"]:g} Hz</strong></div>'
        "</div>"
        f'{failure}<p class="muted">{_escape(format_timing(result, parameters["sampling_frequency_hz"]))}</p>'
        f'<dl class="stats">{_statistics_rows(record)}</dl>'
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
        f'<td dir="ltr">{_escape(_format_timestamp(record["saved_at"]))}</td>'
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
            f'{_format_timestamp(record["saved_at"])} · {record["id"][:8]}'
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
    latest = _format_timestamp(records[0]["saved_at"]) if records else "—"
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
    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Ammeter test history</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17243b;
      --muted: #64748b;
      --line: #e2e8f0;
      --surface: #ffffff;
      --background: #f3f6fb;
      --brand: #175cd3;
      --brand-dark: #1247a5;
      --green: #07805b;
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--background); color: var(--ink); }}
    .shell {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 38px 0 56px; }}
    .hero {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 26px; }}
    .eyebrow {{ color: var(--brand); font-size: .82rem; font-weight: 700; letter-spacing: .04em; }}
    h1 {{ margin: 7px 0 8px; font-size: clamp(1.7rem, 4vw, 2.4rem); letter-spacing: -.035em; }}
    .intro, .muted {{ color: var(--muted); line-height: 1.65; }}
    .local-badge {{ flex: 0 0 auto; padding: 9px 13px; border: 1px solid #b7ead8; border-radius: 999px; background: #eaf8f2; color: #075e43; font-size: .86rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 22px 0; }}
    .card, .panel {{ border: 1px solid var(--line); border-radius: 16px; background: var(--surface); box-shadow: 0 5px 18px #17243b08; }}
    .card {{ padding: 19px 21px; }}
    .card-label {{ color: var(--muted); font-size: .9rem; }}
    .card-value {{ display: block; margin-top: 9px; font-size: 1.65rem; font-weight: 750; }}
    .card-value.small {{ font-size: 1rem; line-height: 1.5; }}
    .panel {{ margin-top: 18px; padding: 22px; }}
    .panel-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
    h2 {{ margin: 0 0 5px; font-size: 1.2rem; }}
    .toolbar {{ display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin: 20px 0 14px; }}
    label {{ display: grid; gap: 6px; color: var(--muted); font-size: .86rem; font-weight: 600; }}
    input, select {{ min-height: 42px; min-width: 190px; padding: 8px 11px; border: 1px solid #cbd5e1; border-radius: 9px; background: #fff; color: var(--ink); font: inherit; }}
    input:focus, select:focus, button:focus-visible, summary:focus-visible {{ outline: 3px solid #93c5fd; outline-offset: 2px; }}
    button {{ min-height: 42px; border: 0; border-radius: 9px; padding: 9px 15px; background: var(--brand); color: #fff; font: inherit; font-weight: 700; cursor: pointer; }}
    button:hover:not(:disabled) {{ background: var(--brand-dark); }}
    button:disabled {{ opacity: .48; cursor: not-allowed; }}
    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; }}
    th {{ padding: 11px 12px; background: #f8fafc; color: #475569; font-size: .82rem; white-space: nowrap; }}
    td {{ padding: 13px 12px; border-top: 1px solid var(--line); vertical-align: top; }}
    tbody tr:hover {{ background: #fbfdff; }}
    .run-id {{ max-width: 210px; overflow-wrap: anywhere; color: #334155; font-size: .82rem; }}
    details summary {{ color: var(--brand); font-weight: 700; cursor: pointer; }}
    details[open] {{ min-width: 300px; }}
    .stats {{ display: grid; grid-template-columns: repeat(2, minmax(110px, 1fr)); gap: 7px 18px; margin: 14px 0; }}
    .stats div {{ display: flex; justify-content: space-between; gap: 8px; padding-bottom: 6px; border-bottom: 1px solid #edf1f6; }}
    .stats dt {{ color: var(--muted); }} .stats dd {{ margin: 0; font-weight: 650; }}
    .run-meta {{ display: grid; grid-template-columns: repeat(2, minmax(180px, 1fr)); gap: 10px 18px; margin: 14px 0; }}
    .run-meta div {{ display: grid; gap: 4px; }}
    .run-meta span {{ color: var(--muted); font-size: .84rem; }}
    .run-meta strong {{ font-weight: 650; }}
    .measurement-chart {{ margin: 18px 0; min-width: 280px; }}
    .measurement-chart figcaption {{ font-weight: 650; }}
    .measurement-chart svg {{ width: 100%; max-width: 520px; height: auto; overflow: visible; }}
    .measurement-chart text {{ fill: var(--muted); font-size: 10px; }}
    .reference-assessment {{ margin: 18px 0; }}
    .reference-assessment button {{ margin-top: 10px; }}
    h4 {{ margin: 14px 0 8px; }}
    .empty-cell {{ color: var(--muted); }}
    .failure {{ color: #b42318; font-weight: 650; }}
    .empty-state {{ padding: 46px 16px 30px; text-align: center; }}
    .empty-icon {{ display: inline-grid; width: 50px; height: 50px; place-items: center; border-radius: 15px; background: #eaf1ff; color: var(--brand); font-size: 1.6rem; }}
    .empty-state h2 {{ margin-top: 13px; }}
    code {{ display: inline-block; padding: 7px 10px; border-radius: 7px; background: #eef2f7; color: #24334d; }}
    .compare-grid {{ display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)) auto; align-items: end; gap: 12px; }}
    #compareResult {{ margin-top: 18px; }}
    .difference {{ color: var(--green); font-weight: 650; }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: .82rem; }}
    @media (max-width: 700px) {{
      .shell {{ width: min(100% - 20px, 1120px); padding-top: 24px; }}
      .hero {{ flex-direction: column; }}
      .cards {{ grid-template-columns: 1fr; gap: 9px; }}
      .card {{ padding: 15px 17px; }}
      .card-value {{ font-size: 1.35rem; }}
      .panel {{ padding: 16px 12px; }}
      .compare-grid {{ grid-template-columns: 1fr; }}
      .run-meta {{ grid-template-columns: 1fr; }}
      input, select, .compare-grid button {{ width: 100%; }}
    }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <span class="eyebrow">AMMETER TESTING FRAMEWORK</span>
        <h1>Ammeter test history</h1>
        <p class="intro">All your runs, measurements, and comparisons in one clear view.</p>
      </div>
      <span class="local-badge">● Stored locally on this computer</span>
    </header>
    <section class="cards" aria-label="History summary">
      <article class="card"><span class="card-label">Total runs</span><strong class="card-value">{len(records)}</strong></article>
      <article class="card"><span class="card-label">Ammeters tested</span><strong class="card-value">{len(ammeters)}</strong></article>
      <article class="card"><span class="card-label">Latest run</span><strong class="card-value small" dir="ltr">{_escape(latest)}</strong></article>
    </section>
    <section class="panel" aria-labelledby="history-heading">
      <div class="panel-heading">
        <div><h2 id="history-heading">Your runs</h2><p class="muted">Expand a run to review its measurements and statistics.</p></div>
      </div>
      {empty_state}
      <div id="historyContent"{' hidden' if not records else ''}>
        <div class="toolbar">
          <label for="searchRuns">Search by run ID<input id="searchRuns" type="search" placeholder="Enter a run ID..."></label>
          <label for="filterAmmeter">Filter by ammeter<select id="filterAmmeter"><option value="">All ammeters</option>{meter_options}</select></label>
          <span id="visibleCount" class="muted" aria-live="polite">{len(records)} runs</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead><tr><th scope="col">Run ID</th><th scope="col">Ammeter</th><th scope="col">Saved (UTC)</th><th scope="col">Status</th><th scope="col">Samples</th><th scope="col">Mean</th><th scope="col">Details</th></tr></thead>
            <tbody id="runRows">{rows}</tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="panel" aria-labelledby="compare-heading">
      <h2 id="compare-heading">Compare two runs</h2>
      <p class="muted">Difference is calculated as the second run minus the first.</p>
      <p class="muted">Differences between ammeters do not indicate accuracy without a known reference value.</p>
      <div class="compare-grid">
        <label for="firstRun">First run<select id="firstRun"{disabled}>{_comparison_options(records)}</select></label>
        <label for="secondRun">Second run<select id="secondRun"{disabled}>{_comparison_options(records)}</select></label>
        <button id="compareButton" type="button"{disabled}>Compare runs</button>
      </div>
      {compare_note}
      <div id="compareResult" aria-live="polite"></div>
    </section>
    <p class="footer">This report is generated from local history. It is not uploaded to GitHub or any external service.</p>
  </main>
  <script>
    const search = document.getElementById("searchRuns");
    const filter = document.getElementById("filterAmmeter");
    const rows = Array.from(document.querySelectorAll("#runRows tr[data-run-id]"));
    const visibleCount = document.getElementById("visibleCount");
    function filterRuns() {{
      const query = search.value.trim().toLowerCase();
      const ammeter = filter.value;
      let visible = 0;
      rows.forEach((row) => {{
        const matches = row.dataset.runId.toLowerCase().includes(query)
          && (!ammeter || row.dataset.ammeter === ammeter);
        row.hidden = !matches;
        if (matches) visible += 1;
      }});
      visibleCount.textContent = `${{visible}} runs`;
    }}
    search.addEventListener("input", filterRuns);
    filter.addEventListener("change", filterRuns);

    document.querySelectorAll(".reference-assessment").forEach((section) => {{
      section.querySelector(".assess-reference").addEventListener("click", () => {{
        const input = section.querySelector(".reference-current").value;
        const reference = Number(input);
        const output = section.querySelector(".reference-result");
        if (input === "" || !Number.isFinite(reference)) {{
          output.textContent = "Enter a finite reference current.";
          return;
        }}
        const errors = section.dataset.currents.split(",").map((value) => Number(value) - reference);
        if (!errors.every(Number.isFinite)) {{
          output.textContent = "The difference is too large to calculate.";
          return;
        }}
        const scale = errors.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
        const average = errors.reduce((sum, value) => sum + value / errors.length, 0);
        const absolute = errors.reduce((sum, value) => sum + Math.abs(value) / errors.length, 0);
        const rms = scale === 0 ? 0 : scale * Math.sqrt(
          errors.reduce((sum, value) => sum + (value / scale) ** 2 / errors.length, 0));
        if (![average, absolute, rms].every(Number.isFinite)) {{
          output.textContent = "The error is too large to calculate.";
          return;
        }}
        const format = (value) => value.toLocaleString("en-US", {{maximumSignificantDigits: 6}});
        output.textContent = `Mean error (measured − reference): ${{format(average)}} A; `
          + `mean absolute error: ${{format(absolute)}} A; RMSE: ${{format(rms)}} A.`;
      }});
    }});

    const labels = {{"mean": "Mean", "median": "Median", "standard-deviation": "Standard deviation", "minimum": "Minimum", "maximum": "Maximum"}};
    document.getElementById("compareButton").addEventListener("click", () => {{
      const first = document.getElementById("firstRun");
      const second = document.getElementById("secondRun");
      const output = document.getElementById("compareResult");
      output.replaceChildren();
      if (!first.value || !second.value || first.value === second.value) {{
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent = "Choose two different runs to compare.";
        output.append(note);
        return;
      }}
      const metrics = Object.keys(labels);
      const readValue = (option, key) => option.getAttribute(`data-${{key}}`);
      const available = metrics.every((key) => readValue(first.selectedOptions[0], key) !== null
        && readValue(first.selectedOptions[0], key) !== ""
        && readValue(second.selectedOptions[0], key) !== null
        && readValue(second.selectedOptions[0], key) !== "");
      if (!available) {{
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent = "Statistics cannot be compared because one run has no measurements.";
        output.append(note);
        return;
      }}
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      ["Metric", "First run", "Second run", "Difference"].forEach((text) => {{
        const cell = document.createElement("th");
        cell.scope = "col";
        cell.textContent = text;
        headerRow.append(cell);
      }});
      head.append(headerRow);
      const body = document.createElement("tbody");
      metrics.forEach((key) => {{
        const firstValue = Number(readValue(first.selectedOptions[0], key));
        const secondValue = Number(readValue(second.selectedOptions[0], key));
        const rawDifference = secondValue - firstValue;
        const tolerance = Number.EPSILON * Math.max(1, Math.abs(firstValue), Math.abs(secondValue)) * 8;
        const difference = Math.abs(rawDifference) < tolerance ? 0 : rawDifference;
        const row = document.createElement("tr");
        [labels[key], `${{firstValue.toLocaleString("en-US", {{maximumSignificantDigits: 6}})}} A`,
          `${{secondValue.toLocaleString("en-US", {{maximumSignificantDigits: 6}})}} A`,
          `${{difference.toLocaleString("en-US", {{maximumSignificantDigits: 6}})}} A`]
          .forEach((text, index) => {{
            const cell = document.createElement("td");
            cell.textContent = text;
            if (index > 0) cell.dir = "ltr";
            if (index === 3) cell.className = "difference";
            row.append(cell);
          }});
        body.append(row);
      }});
      table.append(head, body);
      output.append(table);
    }});
  </script>
</body>
</html>
"""


def generate_report(database_path: Path) -> Path:
    from src.testing.history import HistoryStore

    store = HistoryStore(database_path)
    records: list[HistoryRecord] = [
        store.get(run["id"]) for run in store.list_runs()
    ]
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
