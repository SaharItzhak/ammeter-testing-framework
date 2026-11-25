import math
import statistics
import time
from collections.abc import Callable, Mapping
from typing import Optional, TypedDict

from Ammeters.base_ammeter import AmmeterEmulatorBase
from Ammeters.client import request_current_from_ammeter


class Measurement(TypedDict):
    elapsed_seconds: float
    current_amperes: float


class MeasurementStatistics(TypedDict):
    mean: float
    median: float
    standard_deviation: float
    minimum: float
    maximum: float


class TestResult(TypedDict):
    ammeter: str
    measurements: list[Measurement]
    elapsed_seconds: float
    stop_reason: str
    statistics: Optional[MeasurementStatistics]


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
    ) -> TestResult:
        if ammeter_type not in self.ammeters:
            raise ValueError(f"Unknown ammeter: {ammeter_type}")
        if (
            isinstance(measurements_count, bool)
            or not isinstance(measurements_count, int)
            or measurements_count <= 0
        ):
            raise ValueError("measurements_count must be a positive integer")
        for name, value in (
            ("total_duration_seconds", total_duration_seconds),
            ("sampling_frequency_hz", sampling_frequency_hz),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive finite number")
            try:
                valid = math.isfinite(value) and value > 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be a positive finite number")
        interval = 1 / sampling_frequency_hz
        if not math.isfinite(interval):
            raise ValueError("sampling_frequency_hz is too small")

        ammeter = self.ammeters[ammeter_type]
        start = time.monotonic()
        deadline = start + total_duration_seconds
        measurements: list[Measurement] = []
        next_sample = start
        while len(measurements) < measurements_count:
            now = time.monotonic()
            if now >= deadline or next_sample >= deadline:
                break
            if now < next_sample:
                time.sleep(next_sample - now)
                now = time.monotonic()
            if now >= deadline:
                break
            current = self.request(
                ammeter.port, ammeter.get_current_command, timeout=deadline - now
            )
            if time.monotonic() > deadline:
                raise TimeoutError("Measurement exceeded the test duration")
            measurements.append({"elapsed_seconds": now - start, "current_amperes": current})
            next_sample = max(next_sample + interval, now + interval)

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
            "stop_reason": "count" if len(measurements) == measurements_count else "duration",
            "statistics": summary,
        }
