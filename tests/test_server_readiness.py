import socket
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

import main
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

TEST_RUNTIME_CONFIG = {
    "sampling": {
        "measurements_count": 1,
        "total_duration_seconds": 5.0,
        "sampling_frequency_hz": 1.0,
    },
    "ports": {"greenlee": 5001, "entes": 5002, "circutor": 5003},
    "history_database": Path("unused-history.sqlite3"),
}


class TestServerReadiness:
    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.ThreadPoolExecutor")
    @patch("threading.Event.wait", return_value=False)
    def test_startup_timeout_is_reported(self, wait, executor_factory, runtime_config):
        executor = executor_factory.return_value.__enter__.return_value
        executor.submit.return_value.done.return_value = False
        with pytest.raises(RuntimeError, match="GreenleeAmmeter did not start"):
            main.main()

        assert executor.submit.call_count == 3
        assert executor.submit.call_args.args[2].is_set()
        wait.assert_called_once_with(timeout=5)

    @patch("main.load_runtime_config", return_value=TEST_RUNTIME_CONFIG)
    @patch("main.request_current_from_ammeter", side_effect=OSError("request failed"))
    @patch("Ammeters.base_ammeter.AmmeterEmulatorBase.start_server")
    def test_request_failure_stops_and_joins_workers(self, start_server, request, runtime_config):
        stopped = []

        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=2):
                raise RuntimeError("worker was not stopped")
            stopped.append(threading.current_thread())

        start_server.side_effect = serve
        with pytest.raises(OSError, match="request failed"):
            main.main()

        assert len(stopped) == 3
        assert all(not worker.is_alive() for worker in stopped)

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_idle_listener_stops_and_closes_socket(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        stop = threading.Event()

        def stop_on_accept():
            stop.set()
            raise socket.timeout()

        server.accept.side_effect = stop_on_accept
        GreenleeAmmeter(5001).start_server(stop=stop)
        socket_factory.return_value.__exit__.assert_called_once()

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_idle_client_does_not_block_shutdown(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        connection = MagicMock()
        server.accept.return_value = (connection, ("localhost", 1234))
        stop = threading.Event()

        def stop_on_recv(size):
            stop.set()
            raise socket.timeout()

        connection.recv.side_effect = stop_on_recv
        GreenleeAmmeter(5001).start_server(stop=stop)
        connection.settimeout.assert_called_once()
        connection.__exit__.assert_called_once()
        socket_factory.return_value.__exit__.assert_called_once()

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_ready_is_set_after_listening(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        ready = threading.Event()

        def stop_after_ready():
            assert ready.is_set()
            server.listen.assert_called_once_with()
            raise RuntimeError("stop server")

        server.accept.side_effect = stop_after_ready
        with pytest.raises(RuntimeError, match="stop server"):
            GreenleeAmmeter(5001).start_server(ready)

    @patch("Ammeters.base_ammeter.os", SimpleNamespace(name="posix"))
    @patch("Ammeters.base_ammeter.socket.socket")
    def test_unix_listener_allows_immediate_restart(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        server.accept.side_effect = RuntimeError("stop server")

        with pytest.raises(RuntimeError, match="stop server"):
            GreenleeAmmeter(5001).start_server()

        server.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_bind_failure_does_not_signal_readiness(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        server.bind.side_effect = OSError("address in use")
        ready = threading.Event()

        with pytest.raises(OSError, match="address in use"):
            GreenleeAmmeter(5001).start_server(ready)

        assert not ready.is_set()
        server.listen.assert_not_called()
