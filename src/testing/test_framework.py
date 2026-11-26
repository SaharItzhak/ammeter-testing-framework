import logging
import statistics
import time
from collections.abc import Callable, Mapping
from typing import Optional, TypedDict

from Ammeters.base_ammeter import AmmeterEmulatorBase
from Ammeters.client import request_current_from_ammeter
from src.testing.config import validate_sampling_options, validate_simulate_error_after


class Measurement(TypedDict):
    elapsed_seconds: float
    current_amperes: float


class MeasurementStatistics(TypedDict):
    mean: float
    median: float
    standard_deviation: float
    minimum: float
    maximum: float


class _TestResultRequired(TypedDict):
    ammeter: str
    measurements: list[Measurement]
    elapsed_seconds: float
    stop_reason: str
    statistics: Optional[MeasurementStatistics]


class TestResult(_TestResultRequired, total=False):
    error: str


class SamplingFailure(RuntimeError):
    def __init__(self, message: str, partial_result: TestResult):
        super().__init__(message)
        self.partial_result = partial_result


def coefficient_of_variation(
    summary: Optional[MeasurementStatistics],
) -> Optional[float]:
    if summary is None or summary["mean"] == 0:
        return None
    return summary["standard_deviation"] / abs(summary["mean"]) * 100


def timing_summary(measurements: list[Measurement], frequency: float) -> Optional[dict[str, float]]:
    if len(measurements) < 2:
        return None
    intervals = [
        second["elapsed_seconds"] - first["elapsed_seconds"]
        for first, second in zip(measurements, measurements[1:])
    ]
    target = 1 / frequency
    deviations = [abs(interval - target) for interval in intervals]
    return {
        "target_interval_seconds": target,
        "mean_interval_seconds": statistics.mean(intervals),
        "mean_absolute_deviation_seconds": statistics.mean(deviations),
        "max_absolute_deviation_seconds": max(deviations),
    }


class AmmeterTestFramework:
    def __init__(
        self,
        ammeters: Mapping[str, AmmeterEmulatorBase],
        request: Callable[..., float] = request_current_from_ammeter,
    ):
        self.ammeters = ammeters
        self.request = request

    def run_test(
        self,
        ammeter_type: str,
        measurements_count: int,
        total_duration_seconds: float,
        sampling_frequency_hz: float,
        simulate_error_after: Optional[int] = None,
    ) -> TestResult:
        if ammeter_type not in self.ammeters:
            raise ValueError(f"Unknown ammeter: {ammeter_type}")
        interval = validate_sampling_options(
            measurements_count, total_duration_seconds, sampling_frequency_hz
        )
        validate_simulate_error_after(simulate_error_after, measurements_count)

        ammeter = self.ammeters[ammeter_type]
        start = time.monotonic()
        deadline = start + total_duration_seconds
        measurements: list[Measurement] = []
        next_sample = start

        def result(stop_reason: str) -> TestResult:
            values = [measurement["current_amperes"] for measurement in measurements]
            summary: Optional[MeasurementStatistics] = None
            if values:
                summary = {
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "standard_deviation": statistics.pstdev(values),
                    "minimum": min(values),
                    "maximum": max(values),
                }
            return {
                "ammeter": ammeter_type,
                "measurements": measurements,
                "elapsed_seconds": time.monotonic() - start,
                "stop_reason": stop_reason,
                "statistics": summary,
            }

        while len(measurements) < measurements_count:
            now = time.monotonic()
            if now >= deadline or next_sample >= deadline:
                break
            if now < next_sample:
                time.sleep(next_sample - now)
                now = time.monotonic()
            if now >= deadline:
                break
            try:
                if (
                    simulate_error_after is not None
                    and len(measurements) >= simulate_error_after
                ):
                    raise ConnectionError(
                        f"Simulated connection failure after {simulate_error_after} readings"
                    )
                current = self.request(
                    ammeter.port, ammeter.get_current_command, timeout=deadline - now
                )
                if time.monotonic() > deadline:
                    raise TimeoutError("Measurement exceeded the test duration")
            except (OSError, ValueError, RuntimeError) as error:
                if not measurements:
                    raise
                partial = result("error")
                partial["error"] = f"{type(error).__name__}: {error}"
                raise SamplingFailure(partial["error"], partial) from error
            measurements.append({"elapsed_seconds": now - start, "current_amperes": current})
            next_sample = max(next_sample + interval, now + interval)

        if simulate_error_after is not None:
            logging.getLogger(__name__).warning(
                "Simulation did not trigger before the test ended "
                "(%s readings collected; failure requested after %s)",
                len(measurements), simulate_error_after,
            )
        return result("count" if len(measurements) == measurements_count else "duration")
