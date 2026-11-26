import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.config import (
    AMMETER_TYPES,
    DEFAULT_CONFIG,
    load_runtime_config,
    validate_sampling_options,
    validate_simulate_error_after,
)
from src.testing.history import HistoryStore, format_timing
from src.testing.test_framework import (
    AmmeterTestFramework,
    SamplingFailure,
    coefficient_of_variation,
)


def run(
    ammeter_type: Optional[str] = None,
    count: Optional[int] = None,
    duration: Optional[float] = None,
    frequency: Optional[float] = None,
    database: Optional[Path] = None,
    config_path: Path = DEFAULT_CONFIG,
    simulate_error_after: Optional[int] = None,
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
    validate_sampling_options(count, duration, frequency)
    validate_simulate_error_after(simulate_error_after)

    meter_types = {
        "greenlee": GreenleeAmmeter,
        "entes": EntesAmmeter,
        "circutor": CircutorAmmeter,
    }
    ammeters = {
        name: meter(config["ports"][name], config["commands"][name])
        for name, meter in meter_types.items()
    }
    selected = (
        ammeters
        if ammeter_type == "all"
        else {ammeter_type: ammeters[ammeter_type]}
    )
    stop = threading.Event()
    servers = [(name, ammeter, threading.Event()) for name, ammeter in selected.items()]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        try:
            for _, ammeter, ready in servers:
                futures.append(executor.submit(ammeter.start_server, ready, stop))
            for (name, ammeter, ready), future in zip(servers, futures):
                if not ready.wait(timeout=5):
                    if future.done():
                        try:
                            future.result()
                        except OSError as error:
                            raise RuntimeError(
                                f"{name} ammeter could not start on port "
                                f"{ammeter.port}: {error}"
                            ) from error
                    raise RuntimeError(
                        f"{name} ammeter on port {ammeter.port} did not start "
                        "within 5 seconds"
                    )

            framework = AmmeterTestFramework(
                selected, request=request_current_from_ammeter
            )
            history = HistoryStore(database)
            for name in selected:
                started_at = datetime.now(timezone.utc).isoformat()
                parameters = {
                    "measurements_count": count,
                    "total_duration_seconds": duration,
                    "sampling_frequency_hz": frequency,
                }
                if simulate_error_after is not None:
                    parameters["simulate_error_after"] = simulate_error_after
                try:
                    result = framework.run_test(
                        name, count, duration, frequency, simulate_error_after
                    )
                except SamplingFailure as error:
                    try:
                        partial = history.save(error.partial_result, parameters, started_at)
                    except (OSError, sqlite3.Error, ValueError) as save_error:
                        raise RuntimeError(
                            f"{name} failed: {error}; could not save partial results: "
                            f"{save_error}"
                        ) from save_error
                    raise RuntimeError(
                        f"{name} failed: {error}; partial results saved as run "
                        f"{partial['id']}"
                    ) from error
                if not result["measurements"]:
                    raise RuntimeError(
                        f"{name} produced no measurements; no history record was saved"
                    )
                record = history.save(result, parameters, started_at)
                print(
                    f"{name}: {len(result['measurements'])} measurements "
                    f"({result['stop_reason']})"
                )
                print(f"  Saved run: {record['id']}")
                summary = result["statistics"]
                if summary is None:
                    print("  No measurements available for statistics.")
                else:
                    print(
                        f"  Mean: {summary['mean']:.6g} A; "
                        f"median: {summary['median']:.6g} A; "
                        f"population standard deviation: "
                        f"{summary['standard_deviation']:.6g} A; "
                        f"min: {summary['minimum']:.6g} A; "
                        f"max: {summary['maximum']:.6g} A"
                    )
                    variation = coefficient_of_variation(summary)
                    if variation is None:
                        print("  Coefficient of variation: unavailable (mean is zero)")
                    else:
                        print(
                            f"  Coefficient of variation: {variation:.6g}% "
                            "(lower means more consistent, not more accurate)"
                        )
                print(f"  {format_timing(result, frequency)}")
        finally:
            stop.set()
    for future in futures:
        future.result()
    return Path(database)
