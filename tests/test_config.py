import socket
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from main import DEFAULT_CONFIG, load_runtime_config
from src.testing.history import HistoryStore


class TestRuntimeConfig:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.path = tmp_path / "config.yaml"
        self.config = {
            "testing": {
                "sampling": {
                    "measurements_count": 2,
                    "total_duration_seconds": 4.0,
                    "sampling_frequency_hz": 2.0,
                }
            },
            "ammeters": {
                "greenlee": {"port": 5101},
                "entes": {"port": 5102},
                "circutor": {"port": 5103},
            },
            "result_management": {"history_database": "results/test.sqlite3"},
        }

    def write_config(self):
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        return load_runtime_config(self.path)

    def test_default_configuration_loads(self):
        config = load_runtime_config(DEFAULT_CONFIG)

        assert config["sampling"]["measurements_count"] == 5
        assert config["ports"] == {"greenlee": 5001, "entes": 5002, "circutor": 5003}
        assert config["commands"]["greenlee"] == b"MEASURE_GREENLEE -get_measurement"
        assert config["history_database"] == DEFAULT_CONFIG.parents[1] / "results/history.sqlite3"

    def test_loads_sampling_ports_and_history_path(self):
        self.config["ammeters"]["greenlee"]["command"] = "CUSTOM MEASURE"
        config = self.write_config()

        assert config["sampling"]["measurements_count"] == 2
        assert config["sampling"]["sampling_frequency_hz"] == 2.0
        assert config["ports"] == {"greenlee": 5101, "entes": 5102, "circutor": 5103}
        assert config["commands"]["greenlee"] == b"CUSTOM MEASURE"
        assert config["history_database"] == DEFAULT_CONFIG.parents[1] / "results/test.sqlite3"

    def test_default_config_loads_outside_the_repository(self, tmp_path):
        project_root = DEFAULT_CONFIG.parents[1]
        script = (
            "import sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "from main import DEFAULT_CONFIG, load_runtime_config; "
            "print(load_runtime_config(DEFAULT_CONFIG)['sampling']['measurements_count'])"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(project_root)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "5"

    def test_missing_ammeter_and_duplicate_ports_are_rejected(self):
        self.config["ammeters"].pop("entes")
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with pytest.raises(ValueError, match="ammeters.entes"):
            load_runtime_config(self.path)

        self.config["ammeters"]["entes"] = {"port": 5101}
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with pytest.raises(ValueError, match="Duplicate"):
            load_runtime_config(self.path)

    @pytest.mark.parametrize("command", ["", "   ", 17])
    def test_invalid_meter_commands_are_rejected(self, command):
        self.config["ammeters"]["greenlee"]["command"] = command
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")

        with pytest.raises(ValueError, match="ammeters.greenlee.command"):
            load_runtime_config(self.path)

    @pytest.mark.parametrize(
        "key,value",
        [
            ("measurements_count", True),
            ("measurements_count", 0),
            ("total_duration_seconds", float("nan")),
            ("sampling_frequency_hz", 0),
        ],
    )
    def test_invalid_sampling_values_are_rejected(self, key, value):
        self.config["testing"]["sampling"][key] = value
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with pytest.raises(ValueError):
            load_runtime_config(self.path)

    def test_invalid_port_and_history_path_are_rejected(self):
        self.config["ammeters"]["greenlee"]["port"] = True
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with pytest.raises(ValueError, match="port"):
            load_runtime_config(self.path)

        self.config["ammeters"]["greenlee"]["port"] = 5101
        self.config["result_management"]["history_database"] = ""
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with pytest.raises(ValueError, match="history_database"):
            load_runtime_config(self.path)

    def test_malformed_yaml_is_reported_as_configuration_error(self):
        self.path.write_text("testing: [unclosed", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid YAML configuration"):
            load_runtime_config(self.path)

    def test_application_uses_configured_ports_sampling_and_history(self):
        ports = []
        for _ in range(3):
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                ports.append(available.getsockname()[1])
        self.config["testing"]["sampling"] = {
            "measurements_count": 2,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 20.0,
        }
        for name, port in zip(("greenlee", "entes", "circutor"), ports):
            self.config["ammeters"][name]["port"] = port
        self.config["ammeters"]["greenlee"]["command"] = "CUSTOM_GREENLEE_MEASURE"
        database = self.path.parent / "history.sqlite3"
        self.config["result_management"]["history_database"] = str(database)
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")

        completed = subprocess.run(
            [sys.executable, "-B", "main.py", "--config", str(self.path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert completed.returncode == 0, completed.stderr
        for name in ("greenlee", "entes", "circutor"):
            assert f"{name}: 2 measurements (count)" in completed.stdout
        store = HistoryStore(database)
        records = [store.get(run["id"]) for run in store.list_runs()]
        assert len(records) == 3
        assert all(record["parameters"]["measurements_count"] == 2 for record in records)
