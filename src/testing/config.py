import math
from pathlib import Path
from typing import Any, Mapping

from src.utils.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yaml"
AMMETER_TYPES = ("greenlee", "entes", "circutor")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section '{name}' must be a mapping")
    return value


def validate_sampling_options(
    count: Any,
    duration: Any,
    frequency: Any,
    *,
    prefix: str = "",
) -> float:
    def field(name: str) -> str:
        return f"{prefix}.{name}" if prefix else name

    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError(f"{field('measurements_count')} must be a positive integer")
    for name, value in (
        ("total_duration_seconds", duration),
        ("sampling_frequency_hz", frequency),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field(name)} must be a positive finite number")
        try:
            valid = math.isfinite(value) and value > 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"{field(name)} must be a positive finite number")

    interval = 1 / frequency
    if not math.isfinite(interval):
        raise ValueError(f"{field('sampling_frequency_hz')} is too small")
    return interval


def validate_simulate_error_after(value: Any, count: int) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
    ):
        raise ValueError("simulate_error_after must be a positive integer")
    if value is not None and value >= count:
        raise ValueError("simulate_error_after must be less than measurements_count")


def load_runtime_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = load_config(str(path))
    testing = _require_mapping(config.get("testing"), "testing")
    sampling = _require_mapping(testing.get("sampling"), "testing.sampling")
    ammeters = _require_mapping(config.get("ammeters"), "ammeters")
    result_management = _require_mapping(
        config.get("result_management"), "result_management"
    )
    validate_sampling_options(
        sampling.get("measurements_count"),
        sampling.get("total_duration_seconds"),
        sampling.get("sampling_frequency_hz"),
        prefix="testing.sampling",
    )

    ports = {}
    commands = {}
    for name in AMMETER_TYPES:
        settings = _require_mapping(ammeters.get(name), f"ammeters.{name}")
        port = settings.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"ammeters.{name}.port must be an integer from 1 to 65535")
        if port in ports.values():
            raise ValueError(f"Duplicate ammeter port: {port}")
        ports[name] = port

        command = settings.get("command")
        if command is not None and (not isinstance(command, str) or not command.strip()):
            raise ValueError(f"ammeters.{name}.command must be a non-empty string")
        commands[name] = command.encode("utf-8") if command is not None else None

    history_database = result_management.get("history_database")
    if not isinstance(history_database, str) or not history_database.strip():
        raise ValueError("result_management.history_database must be a non-empty path")
    database_path = Path(history_database)
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    return {
        "sampling": sampling,
        "ports": ports,
        "commands": commands,
        "history_database": database_path,
    }
