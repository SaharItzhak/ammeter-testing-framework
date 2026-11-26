from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.testing.test_framework import AmmeterTestFramework, SamplingFailure, timing_summary


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TestSampling:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.clock = FakeClock()
        self.request = Mock(return_value=1.5)
        self.ammeter = SimpleNamespace(port=1234, get_current_command=b"MEASURE")
        self.framework = AmmeterTestFramework({"greenlee": self.ammeter}, self.request)

    def test_count_and_frequency_schedule(self):
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 3, 5, 2)

        assert result["stop_reason"] == "count"
        assert result["measurements"] == [
            {"elapsed_seconds": 0.0, "current_amperes": 1.5},
            {"elapsed_seconds": 0.5, "current_amperes": 1.5},
            {"elapsed_seconds": 1.0, "current_amperes": 1.5},
        ]
        assert self.clock.sleeps == [0.5, 0.5]
        assert self.request.call_count == 3
        self.request.assert_any_call(1234, b"MEASURE", timeout=5.0)
        assert result["statistics"] == {
            "mean": 1.5, "median": 1.5, "standard_deviation": 0.0,
            "minimum": 1.5, "maximum": 1.5,
        }

    def test_statistics_for_even_number_of_measurements(self):
        self.request.side_effect = [1.0, 3.0, 5.0, 7.0]
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 4, 5, 2)

        assert result["statistics"]["mean"] == 4.0
        assert result["statistics"]["median"] == 4.0
        assert result["statistics"]["standard_deviation"] == pytest.approx(5 ** 0.5)
        assert result["statistics"]["minimum"] == 1.0
        assert result["statistics"]["maximum"] == 7.0

    def test_statistics_for_odd_number_of_measurements(self):
        self.request.side_effect = [1.0, 3.0, 8.0]
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 3, 5, 2)

        assert result["statistics"]["mean"] == 4.0
        assert result["statistics"]["median"] == 3.0
        assert result["statistics"]["standard_deviation"] == pytest.approx((26 / 3) ** 0.5)

    def test_single_measurement_has_zero_population_deviation(self):
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 1, 5, 2)

        assert result["statistics"]["standard_deviation"] == 0.0

    def test_no_measurements_have_no_statistics(self):
        clock = SimpleNamespace(monotonic=Mock(side_effect=[0.0, 2.0, 2.0]))
        with patch("src.testing.test_framework.time", clock):
            result = self.framework.run_test("greenlee", 1, 1, 2)

        assert result["measurements"] == []
        assert result["stop_reason"] == "duration"
        assert result["statistics"] is None
        self.request.assert_not_called()

    def test_duration_limits_number_of_measurements(self):
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 10, 1, 2)

        assert result["stop_reason"] == "duration"
        assert len(result["measurements"]) == 2
        assert self.request.call_count == 2

    def test_slow_measurements_do_not_cause_burst(self):
        def request(*args, **kwargs):
            self.clock.now += 0.75
            return 1.0

        self.framework.request = request
        with patch("src.testing.test_framework.time", self.clock):
            result = self.framework.run_test("greenlee", 3, 4, 2)

        assert [item["elapsed_seconds"] for item in result["measurements"]] == [0.0, 0.75, 1.5]
        timing = timing_summary(result["measurements"], 2)
        assert timing["target_interval_seconds"] == 0.5
        assert timing["mean_interval_seconds"] == 0.75
        assert timing["mean_absolute_deviation_seconds"] == 0.25
        assert timing["max_absolute_deviation_seconds"] == 0.25
        assert timing_summary(result["measurements"][:1], 2) is None

    def test_partial_measurements_are_attached_to_failure(self):
        self.request.side_effect = [1.0, 3.0, TimeoutError("timed out")]
        with patch("src.testing.test_framework.time", self.clock):
            with pytest.raises(SamplingFailure) as raised:
                self.framework.run_test("greenlee", 3, 5, 2)
        partial = raised.value.partial_result
        assert partial["stop_reason"] == "error"
        assert "TimeoutError: timed out" in partial["error"]
        assert [m["current_amperes"] for m in partial["measurements"]] == [1.0, 3.0]
        assert partial["statistics"]["mean"] == 2.0
        assert isinstance(raised.value.__cause__, TimeoutError)

    def test_late_response_preserves_only_earlier_measurements(self):
        def request(*args, **kwargs):
            if self.request.call_count == 2:
                self.clock.now = 2.0
            return 1.0
        self.request.side_effect = request
        with patch("src.testing.test_framework.time", self.clock):
            with pytest.raises(SamplingFailure) as raised:
                self.framework.run_test("greenlee", 3, 1, 2)
        assert "exceeded" in raised.value.partial_result["error"]
        assert len(raised.value.partial_result["measurements"]) == 1

    @pytest.mark.parametrize(
        "args",
        [
            ("unknown", 1, 1, 1),
            ("greenlee", 0, 1, 1),
            ("greenlee", True, 1, 1),
            ("greenlee", 1, 0, 1),
            ("greenlee", 1, 1, float("nan")),
            ("greenlee", 1, 1, float("inf")),
            ("greenlee", 1, 1, 10 ** 400),
            ("greenlee", 1, 1, 5e-324),
        ],
    )
    def test_invalid_inputs_are_rejected(self, args):
        with pytest.raises(ValueError):
            self.framework.run_test(*args)
        self.request.assert_not_called()

    def test_request_failures_propagate(self):
        self.request.side_effect = TimeoutError("request timed out")
        with patch("src.testing.test_framework.time", self.clock):
            with pytest.raises(TimeoutError, match="request timed out"):
                self.framework.run_test("greenlee", 1, 1, 1)

    def test_late_response_is_not_reported_as_success(self):
        def request(*args, **kwargs):
            self.clock.now = 2
            return 1.0

        self.framework.request = request
        with patch("src.testing.test_framework.time", self.clock):
            with pytest.raises(TimeoutError, match="exceeded"):
                self.framework.run_test("greenlee", 1, 1, 1)
