import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from main import DEFAULT_CONFIG, load_runtime_config
from src.testing.history import HistoryStore


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"
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

        self.assertEqual(config["sampling"]["measurements_count"], 5)
        self.assertEqual(config["ports"], {"greenlee": 5001, "entes": 5002, "circutor": 5003})
        self.assertEqual(config["history_database"], Path("results/history.sqlite3"))

    def test_loads_sampling_ports_and_history_path(self):
        config = self.write_config()

        self.assertEqual(config["sampling"]["measurements_count"], 2)
        self.assertEqual(config["sampling"]["sampling_frequency_hz"], 2.0)
        self.assertEqual(config["ports"], {"greenlee": 5101, "entes": 5102, "circutor": 5103})
        self.assertEqual(config["history_database"], Path("results/test.sqlite3"))

    def test_missing_ammeter_and_duplicate_ports_are_rejected(self):
        self.config["ammeters"].pop("entes")
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ammeters.entes"):
            load_runtime_config(self.path)

        self.config["ammeters"]["entes"] = {"port": 5101}
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_runtime_config(self.path)

    def test_invalid_sampling_values_are_rejected(self):
        for key, value in (
            ("measurements_count", True),
            ("measurements_count", 0),
            ("total_duration_seconds", float("nan")),
            ("sampling_frequency_hz", 0),
        ):
            with self.subTest(key=key, value=value):
                self.config["testing"]["sampling"][key] = value
                self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_runtime_config(self.path)
                self.config["testing"]["sampling"][key] = {
                    "measurements_count": 2,
                    "total_duration_seconds": 4.0,
                    "sampling_frequency_hz": 2.0,
                }[key]

    def test_invalid_port_and_history_path_are_rejected(self):
        self.config["ammeters"]["greenlee"]["port"] = True
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "port"):
            load_runtime_config(self.path)

        self.config["ammeters"]["greenlee"]["port"] = 5101
        self.config["result_management"]["history_database"] = ""
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "history_database"):
            load_runtime_config(self.path)

    def test_malformed_yaml_is_reported_as_configuration_error(self):
        self.path.write_text("testing: [unclosed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid YAML configuration"):
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
        database = Path(self.directory.name) / "history.sqlite3"
        self.config["result_management"]["history_database"] = str(database)
        self.path.write_text(yaml.safe_dump(self.config), encoding="utf-8")

        run_cli = (
            "import runpy, sys; from unittest.mock import patch\n"
            "with patch('webbrowser.open', return_value=True) as browser_open:\n"
            "    runpy.run_path('main.py', run_name='__main__')\n"
            "    if '--open-report' in sys.argv:\n"
            "        browser_open.assert_called_once()\n"
            "    else:\n"
            "        browser_open.assert_not_called()\n"
        )
        for extra in ([], ["--open-report"]):
            with self.subTest(extra=extra):
                completed = subprocess.run(
                    [sys.executable, "-B", "-c", run_cli, "--config", str(self.path), *extra],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(database.with_suffix(".html").is_file())
                for name in ("greenlee", "entes", "circutor"):
                    self.assertRegex(completed.stdout, rf"{name}: 2 measurements \(count\)")
        records = [HistoryStore(database).get(run["id"]) for run in HistoryStore(database).list_runs()]
        self.assertEqual(len(records), 6)
        self.assertTrue(all(record["parameters"]["measurements_count"] == 2 for record in records))


if __name__ == "__main__":
    unittest.main()
