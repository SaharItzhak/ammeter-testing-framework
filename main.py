import argparse
import sqlite3
from pathlib import Path
from typing import Optional

from src.testing.config import AMMETER_TYPES, DEFAULT_CONFIG, load_runtime_config
from src.testing.report import generate_report, open_report
from src.testing.runner import run


def main(
    ammeter_type: Optional[str] = None,
    count: Optional[int] = None,
    duration: Optional[float] = None,
    frequency: Optional[float] = None,
    database: Optional[Path] = None,
    config_path: Path = DEFAULT_CONFIG,
    simulate_error_after: Optional[int] = None,
) -> Path:
    return run(
        ammeter_type,
        count,
        duration,
        frequency,
        database,
        config_path,
        simulate_error_after,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample current from ammeter emulators.")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="configuration file"
    )
    parser.add_argument("--ammeter", choices=("all", *AMMETER_TYPES), default=None)
    parser.add_argument(
        "--count", type=int, default=None, help="override configured measurement count"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="override configured duration in seconds",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=None,
        help="override configured frequency in Hz",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="override configured history database",
    )
    parser.add_argument(
        "--simulate-error-after",
        type=int,
        default=None,
        metavar="N",
        help="simulate a connection failure after N successful readings",
    )
    parser.add_argument(
        "--open-report",
        action="store_true",
        help="open the history report after sampling",
    )
    args = parser.parse_args()
    try:
        database = main(
            args.ammeter,
            args.count,
            args.duration,
            args.frequency,
            args.database,
            args.config,
            args.simulate_error_after,
        )
        if args.open_report:
            print(open_report(database))
        else:
            report_path = generate_report(database)
            print(
                f"History report saved to {report_path}. "
                "Open this file in a browser to view it."
            )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Run failed: {error}\n")
