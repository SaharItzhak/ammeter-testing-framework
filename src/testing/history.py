import argparse
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from src.testing.config import PROJECT_ROOT
from src.testing.test_framework import (
    TestResult,
    coefficient_of_variation,
    timing_summary,
)

DEFAULT_DATABASE = PROJECT_ROOT / "results" / "history.sqlite3"


class SamplingParameters(TypedDict):
    measurements_count: int
    total_duration_seconds: float
    sampling_frequency_hz: float


class HistoryRecord(TypedDict):
    id: str
    started_at: str
    saved_at: str
    parameters: SamplingParameters
    result: TestResult


class HistoryStore:
    def __init__(self, path: Path = DEFAULT_DATABASE):
        self.path = Path(path)

    def save(
        self, result: TestResult, parameters: SamplingParameters, started_at: str
    ) -> HistoryRecord:
        record: HistoryRecord = {
            "id": str(uuid.uuid4()),
            "started_at": started_at,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "parameters": parameters,
            "result": result,
        }
        payload = json.dumps(record, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "id TEXT PRIMARY KEY, saved_at TEXT NOT NULL, "
                "ammeter TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO runs (id, saved_at, ammeter, payload) VALUES (?, ?, ?, ?)",
                (record["id"], record["saved_at"], result["ammeter"], payload),
            )
        return record

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(
                f"No history database at {self.path}. Run `python main.py` first."
            )
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)

    @staticmethod
    def _has_runs_table(connection: sqlite3.Connection) -> bool:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_sequence'"
        ).fetchall()
        if not rows:
            return False
        if not any(row[0] == "runs" for row in rows):
            raise ValueError("History database does not contain the expected runs table")
        return True

    def list_runs(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        with closing(self._connect_readonly()) as connection:
            if not self._has_runs_table(connection):
                return []
            rows = connection.execute(
                "SELECT id, saved_at, ammeter, payload FROM runs ORDER BY saved_at DESC, id"
            ).fetchall()
        return [
            {
                "id": run_id,
                "saved_at": saved_at,
                "ammeter": ammeter,
                "status": "failed" if json.loads(payload)["result"]["stop_reason"] == "error" else "completed",
            }
            for run_id, saved_at, ammeter, payload in rows
        ]

    def get(self, run_id: str) -> HistoryRecord:
        if not self.path.is_file():
            raise KeyError(
                f"No saved runs yet. Run `python main.py` before requesting run {run_id}."
            )
        with closing(self._connect_readonly()) as connection:
            if not self._has_runs_table(connection):
                raise KeyError(
                    f"No saved runs yet. Run `python main.py` before requesting run {run_id}."
                )
            row = connection.execute(
                "SELECT payload FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(
                f"Run {run_id} was not found. Use `list` to see saved run IDs."
            )
        return json.loads(row[0])

    def compare(self, first_id: str, second_id: str) -> dict:
        first = self.get(first_id)
        second = self.get(second_id)
        first_stats = first["result"]["statistics"]
        second_stats = second["result"]["statistics"]
        differences = None
        if first_stats is not None and second_stats is not None:
            differences = {
                key: second_stats[key] - first_stats[key]
                for key in ("mean", "median", "standard_deviation", "minimum", "maximum")
            }
        return {"first": first, "second": second, "second_minus_first": differences}


def _format_timestamp(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", " UTC")


def _format_statistics(statistics: Optional[dict]) -> list[str]:
    if statistics is None:
        return ["  Statistics: unavailable (no measurements)"]
    labels = (
        ("mean", "Mean"),
        ("median", "Median"),
        ("standard_deviation", "Population standard deviation"),
        ("minimum", "Minimum"),
        ("maximum", "Maximum"),
    )
    lines = [f"  {label}: {statistics[key]:.6g} A" for key, label in labels]
    variation = coefficient_of_variation(statistics)
    if variation is None:
        lines.append("  Coefficient of variation: unavailable (mean is zero)")
    else:
        lines.append(f"  Coefficient of variation: {variation:.6g}%")
    return lines


def format_timing(result: TestResult, frequency: float) -> str:
    timing = timing_summary(result["measurements"], frequency)
    if timing is None:
        return "Timing: unavailable (at least two measurements required)"
    return (
        f"Timing between request starts: target {timing['target_interval_seconds']:.6g} s; "
        f"mean {timing['mean_interval_seconds']:.6g} s; "
        f"mean absolute deviation {timing['mean_absolute_deviation_seconds']:.6g} s; "
        f"max absolute deviation {timing['max_absolute_deviation_seconds']:.6g} s"
    )


def _format_run(record: HistoryRecord) -> str:
    result = record["result"]
    parameters = record["parameters"]
    measurements = result["measurements"]
    lines = [
        f"Run {record['id']}",
        f"Ammeter: {result['ammeter']}",
        f"Started: {_format_timestamp(record['started_at'])}",
        f"Saved: {_format_timestamp(record['saved_at'])}",
        (
            f"Sampling settings: up to {parameters['measurements_count']} measurements, "
            f"{parameters['total_duration_seconds']:g} s, "
            f"{parameters['sampling_frequency_hz']:g} Hz"
        ),
        (
            f"Result: {len(measurements)} measurement(s) in "
            f"{result['elapsed_seconds']:.3f} s; stopped by {result['stop_reason']}"
        ),
    ]
    if result.get("error"):
        lines.append(f"Failure: {result['error']} (partial results)")
    if measurements:
        lines.append("Measurements:")
        lines.extend(
            f"  {index:>3}. {measurement['elapsed_seconds']:>8.3f} s  "
            f"{measurement['current_amperes']:.6g} A"
            for index, measurement in enumerate(measurements, 1)
        )
    lines.extend(["Statistics:", *_format_statistics(result["statistics"])])
    lines.append(format_timing(result, parameters["sampling_frequency_hz"]))
    return "\n".join(lines)


def _format_runs(runs: list[dict[str, str]]) -> str:
    if not runs:
        return "No saved runs yet. Run `python main.py` to collect measurements."
    id_width = max(len("RUN ID"), *(len(run["id"]) for run in runs))
    ammeter_width = max(len("AMMETER"), *(len(run["ammeter"]) for run in runs))
    timestamps = [_format_timestamp(run["saved_at"]) for run in runs]
    timestamp_width = max(len("SAVED (UTC)"), *(len(value) for value in timestamps))
    lines = [
        f"{'RUN ID':<{id_width}}  {'SAVED (UTC)':<{timestamp_width}}  {'AMMETER':<{ammeter_width}}  STATUS",
        f"{'-' * id_width}  {'-' * timestamp_width}  {'-' * ammeter_width}  ---------",
    ]
    lines.extend(
        f"{run['id']:<{id_width}}  {saved_at:<{timestamp_width}}  "
        f"{run['ammeter']:<{ammeter_width}}  {run['status']}"
        for run, saved_at in zip(runs, timestamps)
    )
    return "\n".join(lines)


def _format_comparison(comparison: dict) -> str:
    first = comparison["first"]
    second = comparison["second"]
    first_stats = first["result"]["statistics"]
    second_stats = second["result"]["statistics"]
    lines = [
        "Run comparison (second minus first)",
        f"First:  {first['id']} ({first['result']['ammeter']})",
        f"Second: {second['id']} ({second['result']['ammeter']})",
    ]
    differences = comparison["second_minus_first"]
    if differences is None:
        lines.append("Statistics comparison unavailable (one or both runs have no measurements).")
        return "\n".join(lines)

    labels = (
        ("mean", "Mean"),
        ("median", "Median"),
        ("standard_deviation", "Population standard deviation"),
        ("minimum", "Minimum"),
        ("maximum", "Maximum"),
    )
    label_width = max(len(label) for _, label in labels)
    lines.extend(
        [
            "",
            f"{'METRIC':<{label_width}}  {'FIRST':>12}  {'SECOND':>12}  {'DIFFERENCE':>12}",
            f"{'-' * label_width}  {'-' * 12}  {'-' * 12}  {'-' * 12}",
        ]
    )
    lines.extend(
        f"{label:<{label_width}}  {first_stats[key]:>12.6g}  "
        f"{second_stats[key]:>12.6g}  {differences[key]:>12.6g} A"
        for key, label in labels
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect saved ammeter runs.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List saved runs")
    commands.add_parser("report", help="Open the visual run-history report")
    show = commands.add_parser("show", help="Show a saved run")
    show.add_argument("run_id")
    compare = commands.add_parser("compare", help="Compare two saved runs")
    compare.add_argument("first_id")
    compare.add_argument("second_id")
    args = parser.parse_args()

    store = HistoryStore(args.database)
    try:
        if args.command == "list":
            runs = store.list_runs()
            output = _format_runs(runs)
        elif args.command == "report":
            from src.testing.report import open_report

            output = open_report(args.database)
        elif args.command == "show":
            output = _format_run(store.get(args.run_id))
        else:
            output = _format_comparison(store.compare(args.first_id, args.second_id))
    except (OSError, sqlite3.Error, KeyError, ValueError) as error:
        message = error.args[0] if isinstance(error, KeyError) else str(error)
        parser.exit(2, f"History error: {message}\n")
    print(output)


if __name__ == "__main__":
    main()
