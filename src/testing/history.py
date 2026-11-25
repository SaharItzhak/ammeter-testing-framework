import argparse
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.testing.test_framework import TestResult

DEFAULT_DATABASE = Path("results") / "history.sqlite3"


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
            raise FileNotFoundError(f"History database not found: {self.path}")
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)

    def list_runs(self) -> list[dict[str, str]]:
        with closing(self._connect_readonly()) as connection:
            rows = connection.execute(
                "SELECT id, saved_at, ammeter FROM runs ORDER BY saved_at DESC, id"
            ).fetchall()
        return [
            {"id": run_id, "saved_at": saved_at, "ammeter": ammeter}
            for run_id, saved_at, ammeter in rows
        ]

    def get(self, run_id: str) -> HistoryRecord:
        with closing(self._connect_readonly()) as connection:
            row = connection.execute(
                "SELECT payload FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect saved ammeter runs.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List saved runs")
    show = commands.add_parser("show", help="Show a saved run")
    show.add_argument("run_id")
    compare = commands.add_parser("compare", help="Compare two saved runs")
    compare.add_argument("first_id")
    compare.add_argument("second_id")
    args = parser.parse_args()

    store = HistoryStore(args.database)
    try:
        if args.command == "list":
            output = store.list_runs()
        elif args.command == "show":
            output = store.get(args.run_id)
        else:
            output = store.compare(args.first_id, args.second_id)
    except (OSError, sqlite3.Error, KeyError, ValueError) as error:
        parser.exit(2, f"History error: {error}\n")
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
