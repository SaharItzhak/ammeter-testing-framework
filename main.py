import argparse
import math
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.history import DEFAULT_DATABASE, HistoryStore
from src.testing.report import open_report
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

DEFAULT_CONFIG = Path("config") / "config.yaml"
AMMETER_TYPES = ("greenlee", "entes", "circutor")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section '{name}' must be a mapping")
    return value


def load_runtime_config(path: Path) -> dict[str, Any]:
    config = load_config(str(path))
    testing = _require_mapping(config.get("testing"), "testing")
    sampling = _require_mapping(testing.get("sampling"), "testing.sampling")
    ammeters = _require_mapping(config.get("ammeters"), "ammeters")
    result_management = _require_mapping(
        config.get("result_management"), "result_management"
    )

    count = sampling.get("measurements_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("testing.sampling.measurements_count must be a positive integer")
    for key in ("total_duration_seconds", "sampling_frequency_hz"):
        value = sampling.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"testing.sampling.{key} must be a positive finite number")
        try:
            valid = math.isfinite(value) and value > 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"testing.sampling.{key} must be a positive finite number")

    ports = {}
    for name in AMMETER_TYPES:
        settings = _require_mapping(ammeters.get(name), f"ammeters.{name}")
        port = settings.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"ammeters.{name}.port must be an integer from 1 to 65535")
        if port in ports.values():
            raise ValueError(f"Duplicate ammeter port: {port}")
        ports[name] = port

    history_database = result_management.get("history_database")
    if not isinstance(history_database, str) or not history_database.strip():
        raise ValueError("result_management.history_database must be a non-empty path")

    return {
        "sampling": sampling,
        "ports": ports,
        "history_database": Path(history_database),
    }


def main(
    ammeter_type=None,
    count=None,
    duration=None,
    frequency=None,
    database=None,
    config_path=DEFAULT_CONFIG,
) -> Path:
    config = load_runtime_config(Path(config_path))
    sampling = config["sampling"]
    count = sampling["measurements_count"] if count is None else count
    duration = sampling["total_duration_seconds"] if duration is None else duration
    frequency = sampling["sampling_frequency_hz"] if frequency is None else frequency
    database = config["history_database"] if database is None else Path(database)
    ammeter_type = "all" if ammeter_type is None else ammeter_type
    if ammeter_type != "all" and ammeter_type not in AMMETER_TYPES:
        raise ValueError(f"Unknown ammeter: {ammeter_type}")

    stop = threading.Event()
    ammeters = {
        "greenlee": GreenleeAmmeter(config["ports"]["greenlee"]),
        "entes": EntesAmmeter(config["ports"]["entes"]),
        "circutor": CircutorAmmeter(config["ports"]["circutor"]),
    }
    selected = ammeters if ammeter_type == "all" else {ammeter_type: ammeters[ammeter_type]}
    servers = [(ammeter, threading.Event()) for ammeter in selected.values()]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        try:
            for ammeter, ready in servers:
                futures.append(executor.submit(ammeter.start_server, ready, stop))
            for (ammeter, ready), future in zip(servers, futures):
                if not ready.wait(timeout=5):
                    if future.done():
                        future.result()
                    raise RuntimeError(
                        f"{ammeter.__class__.__name__} did not start within 5 seconds"
                    )
            framework = AmmeterTestFramework(selected, request=request_current_from_ammeter)
            history = HistoryStore(database)
            for name in selected:
                started_at = datetime.now(timezone.utc).isoformat()
                result = framework.run_test(name, count, duration, frequency)
                if not result["measurements"]:
                    raise RuntimeError(
                        f"{name} produced no measurements; no history record was saved"
                    )
                record = history.save(
                    result,
                    {
                        "measurements_count": count,
                        "total_duration_seconds": duration,
                        "sampling_frequency_hz": frequency,
                    },
                    started_at,
                )
                print(f"{name}: {len(result['measurements'])} measurements ({result['stop_reason']})")
                print(f"  Saved run: {record['id']}")
                summary = result["statistics"]
                if summary is None:
                    print("  No measurements available for statistics.")
                else:
                    print(
                        f"  Mean: {summary['mean']:.6g} A; "
                        f"median: {summary['median']:.6g} A; "
                        f"population standard deviation: {summary['standard_deviation']:.6g} A; "
                        f"min: {summary['minimum']:.6g} A; max: {summary['maximum']:.6g} A"
                    )
        finally:
            stop.set()
    for future in futures:
        future.result()
    return database


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample current from ammeter emulators.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="configuration file")
    parser.add_argument("--ammeter", choices=("all", *AMMETER_TYPES), default=None)
    parser.add_argument("--count", type=int, default=None, help="override configured measurement count")
    parser.add_argument("--duration", type=float, default=None, help="override configured duration in seconds")
    parser.add_argument("--frequency", type=float, default=None, help="override configured frequency in Hz")
    parser.add_argument("--database", type=Path, default=None, help="override configured history database")
    args = parser.parse_args()
    try:
        database = main(
            args.ammeter,
            args.count,
            args.duration,
            args.frequency,
            args.database,
            args.config,
        )
        print(open_report(database))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Run failed: {error}\n")
