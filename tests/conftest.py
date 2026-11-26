import pytest


@pytest.fixture
def runtime_config(tmp_path):
    return {
        "sampling": {
            "measurements_count": 1,
            "total_duration_seconds": 5.0,
            "sampling_frequency_hz": 1.0,
        },
        "ports": {"greenlee": 5001, "entes": 5002, "circutor": 5003},
        "commands": {"greenlee": None, "entes": None, "circutor": None},
        "history_database": tmp_path / "history.sqlite3",
    }


@pytest.fixture
def configured_runner(monkeypatch, runtime_config):
    monkeypatch.setattr(
        "src.testing.runner.load_runtime_config", lambda path: runtime_config
    )
    return runtime_config
