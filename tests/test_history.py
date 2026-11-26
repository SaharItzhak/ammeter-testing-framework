from contextlib import closing
import sqlite3
import subprocess
import sys
import uuid
from unittest.mock import patch

import pytest

import main
from src.testing.history import HistoryStore
from src.testing.test_framework import SamplingFailure

def result(ammeter, value):
    return {
        "ammeter": ammeter,
        "measurements": [{"elapsed_seconds": 0.0, "current_amperes": value}],
        "elapsed_seconds": 0.1,
        "stop_reason": "count",
        "statistics": {
            "mean": value,
            "median": value,
            "standard_deviation": 0.0,
            "minimum": value,
            "maximum": value,
        },
    }

@pytest.mark.integration
class TestHistory:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.path = tmp_path / "runs.sqlite3"
        self.store = HistoryStore(self.path)
        self.parameters = {
            "measurements_count": 1,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 1.0,
        }

    def save(self, ammeter, value):
        return self.store.save(
            result(ammeter, value), self.parameters, "2026-01-01T00:00:00+00:00"
        )

    def test_runs_persist_with_metadata_and_measurements(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        reopened = HistoryStore(self.path)
        assert first["id"] != second["id"]
        assert reopened.get(first["id"]) == first
        assert first["parameters"] == self.parameters
        assert first["result"]["measurements"][0]["current_amperes"] == 1.0
        assert {run["id"] for run in reopened.list_runs()} == {first["id"], second["id"]}

    def test_comparison_preserves_both_runs_and_calculates_differences(self):
        first = self.save("greenlee", 1.0)
        second = self.save("entes", 3.0)
        comparison = self.store.compare(first["id"], second["id"])
        assert comparison["first"] == first
        assert comparison["second"] == second
        assert comparison["second_minus_first"]["mean"] == 2.0
        assert comparison["second_minus_first"]["standard_deviation"] == 0.0

    def test_comparison_without_statistics_does_not_invent_differences(self):
        first = self.save("greenlee", 1.0)
        empty_result = result("entes", 3.0)
        empty_result["measurements"] = []
        empty_result["statistics"] = None
        second = self.store.save(
            empty_result, self.parameters, "2026-01-01T00:00:00+00:00"
        )
        assert self.store.compare(first["id"], second["id"])["second_minus_first"] is None

    def test_missing_database_and_run_are_reported(self):
        assert self.store.list_runs() == []
        assert not self.path.exists()
        with pytest.raises(KeyError, match="No saved runs"):
            self.store.get("missing")

    def test_list_command_explains_empty_history(self):
        base = [
            sys.executable,
            "-B",
            "-m",
            "src.testing.history",
            "--database",
            str(self.path),
        ]
        completed = subprocess.run(
            base + ["list"], capture_output=True, text=True, timeout=10
        )
        assert completed.returncode == 0
        assert "No saved runs yet" in completed.stdout
        assert "python main.py" in completed.stdout
        assert not self.path.exists()

    def test_show_and_compare_without_history_give_actionable_errors(self):
        base = [
            sys.executable,
            "-B",
            "-m",
            "src.testing.history",
            "--database",
            str(self.path),
        ]
        for args in (['show', 'missing'], ['compare', 'first', 'second']):
            completed = subprocess.run(
                base + args, capture_output=True, text=True, timeout=10
            )
            assert completed.returncode == 2
            assert 'No saved runs yet' in completed.stderr
            assert 'Traceback' not in completed.stderr

    def test_empty_database_is_reported_as_no_runs(self):
        self.save('greenlee', 1.0)
        self.path.unlink()
        with closing(sqlite3.connect(self.path)):
            pass
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "src.testing.history",
                "--database",
                str(self.path),
                "list",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 0
        assert 'No saved runs yet' in completed.stdout

    def test_corrupt_database_has_a_concise_error(self):
        self.path.write_bytes(b'not a SQLite database')
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "src.testing.history",
                "--database",
                str(self.path),
                "list",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 2
        assert 'History error:' in completed.stderr
        assert 'Traceback' not in completed.stderr

    def test_duplicate_id_does_not_overwrite_existing_run(self):
        with patch('src.testing.history.uuid.uuid4', return_value=uuid.UUID(int=1)):
            first = self.save('greenlee', 1.0)
            with pytest.raises(sqlite3.IntegrityError):
                self.save('entes', 3.0)
        assert self.store.get(first['id']) == first
        assert len(self.store.list_runs()) == 1

    @pytest.mark.usefixtures("configured_runner")
    @patch('src.testing.runner.AmmeterTestFramework')
    @patch('src.testing.runner.GreenleeAmmeter.start_server')
    def test_main_saves_successful_run(self, start_server, framework_factory):

        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError('Server was not stopped')
        start_server.side_effect = serve
        framework_factory.return_value.run_test.return_value = result('greenlee', 1.0)
        main.main('greenlee', count=1, duration=5, frequency=1, database=self.path)
        runs = self.store.list_runs()
        assert len(runs) == 1
        saved = self.store.get(runs[0]['id'])
        assert saved['result'] == result('greenlee', 1.0)
        assert saved['parameters'] == self.parameters

    @pytest.mark.usefixtures("configured_runner")
    @patch(
        'src.testing.runner.request_current_from_ammeter',
        side_effect=[1.0, 3.0, TimeoutError('lost connection')],
    )
    @patch('src.testing.runner.GreenleeAmmeter.start_server')
    def test_main_saves_partial_failed_run_and_preserves_history(
        self, start_server, request
    ):
        earlier = self.save('entes', 4.0)

        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError('Server was not stopped')
        start_server.side_effect = serve
        with pytest.raises(RuntimeError, match='partial results saved as run') as raised:
            main.main('greenlee', count=3, duration=5, frequency=100, database=self.path)
        runs = self.store.list_runs()
        failed = next((run for run in runs if run['status'] == 'failed'))
        record = self.store.get(failed['id'])
        assert failed['id'] in str(raised.value)
        assert self.store.get(earlier['id']) == earlier
        assert record['result']['stop_reason'] == 'error'
        assert 'lost connection' in record['result']['error']
        assert len(record['result']['measurements']) == 2
        base = [sys.executable, '-B', '-m', 'src.testing.history', '--database', str(self.path)]
        listed = subprocess.run(base + ['list'], capture_output=True, text=True, timeout=10)
        shown = subprocess.run(
            base + ['show', failed['id']], capture_output=True, text=True, timeout=10
        )
        assert listed.returncode == 0
        assert 'failed' in listed.stdout
        assert shown.returncode == 0
        assert 'Failure: TimeoutError: lost connection (partial results)' in shown.stdout
        assert 'max absolute deviation' in shown.stdout

    def test_cli_returns_failure_and_saves_partial_results(self):
        run_cli = "\n".join(
            [
                "import runpy",
                "from unittest.mock import patch",
                "def serve(self, ready, stop):",
                "    ready.set()",
                "    stop.wait(3)",
                "with patch('Ammeters.Greenlee_Ammeter.GreenleeAmmeter.start_server', serve), "
                "patch('Ammeters.client.request_current_from_ammeter', return_value=1.0):",
                "    runpy.run_path('main.py', run_name='__main__')",
            ]
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                run_cli,
                "--ammeter",
                "greenlee",
                "--database",
                str(self.path),
                "--count",
                "3",
                "--frequency",
                "100",
                "--simulate-error-after",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 1
        assert 'partial results saved as run' in completed.stderr
        assert 'Simulated connection failure' in completed.stderr
        runs = self.store.list_runs()
        assert len(runs) == 1
        assert runs[0]['status'] == 'failed'
        assert len(self.store.get(runs[0]['id'])['result']['measurements']) == 1

    @pytest.mark.usefixtures("configured_runner")
    @patch('src.testing.runner.HistoryStore.save', side_effect=OSError('disk full'))
    @patch('src.testing.runner.AmmeterTestFramework')
    @patch('src.testing.runner.GreenleeAmmeter.start_server')
    def test_partial_save_failure_reports_original_and_storage_errors(
        self, start_server, framework_factory, save
    ):

        def serve(ready, stop):
            ready.set()
            stop.wait(3)
        start_server.side_effect = serve
        partial = result('greenlee', 1.0)
        partial['stop_reason'] = 'error'
        partial['error'] = 'TimeoutError: connection lost'
        framework_factory.return_value.run_test.side_effect = SamplingFailure(
            partial['error'], partial
        )
        with pytest.raises(
            RuntimeError,
            match='connection lost.*could not save partial results: disk full',
        ):
            main.main('greenlee', count=3, duration=5, frequency=1, database=self.path)

    def test_history_cli_lists_shows_and_compares_runs(self):
        first = self.save('greenlee', 1.0)
        second = self.save('entes', 3.0)
        base = [sys.executable, '-B', '-m', 'src.testing.history', '--database', str(self.path)]
        outputs = {}
        for args in (['list'], ['show', first['id']], ['compare', first['id'], second['id']]):
            completed = subprocess.run(base + args, capture_output=True, text=True, timeout=10)
            assert completed.returncode == 0
            assert completed.stdout.strip()
            outputs[args[0]] = completed.stdout
        assert first['id'] in outputs['list']
        assert 'Statistics:' in outputs['show']
        assert 'Run comparison' in outputs['compare']
        assert 'DIFFERENCE' in outputs['compare']
        missing = subprocess.run(
            base + ['show', 'missing'], capture_output=True, text=True, timeout=10
        )
        assert missing.returncode != 0
        assert 'Use `list`' in missing.stderr

    @pytest.mark.usefixtures("configured_runner")
    @patch('src.testing.runner.AmmeterTestFramework')
    @patch('src.testing.runner.GreenleeAmmeter.start_server')
    def test_main_does_not_save_a_run_without_measurements(
        self, start_server, framework_factory
    ):

        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=3):
                raise RuntimeError('Server was not stopped')
        start_server.side_effect = serve
        empty_result = result('greenlee', 1.0)
        empty_result['measurements'] = []
        empty_result['statistics'] = None
        framework_factory.return_value.run_test.return_value = empty_result
        with pytest.raises(RuntimeError, match='no history record was saved'):
            main.main('greenlee', count=1, duration=5, frequency=1, database=self.path)
        assert not self.path.exists()
