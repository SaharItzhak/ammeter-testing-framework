import socket
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import main
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter

class TestServerReadiness:
    @pytest.mark.usefixtures("configured_runner")
    @patch("src.testing.runner.ThreadPoolExecutor")
    @patch("threading.Event.wait", return_value=False)
    def test_startup_timeout_is_reported(self, wait, executor_factory):
        executor = executor_factory.return_value.__enter__.return_value
        executor.submit.return_value.done.return_value = False
        with pytest.raises(RuntimeError, match="greenlee ammeter on port 5001 did not start"):
            main.main()

        assert executor.submit.call_count == 3
        assert executor.submit.call_args.args[2].is_set()
        wait.assert_called_once_with(timeout=5)

    @pytest.mark.usefixtures("configured_runner")
    @patch("src.testing.runner.ThreadPoolExecutor")
    def test_invalid_sampling_is_rejected_before_startup(self, executor_factory):
        with pytest.raises(ValueError, match="measurements_count"):
            main.main(count=0)

        executor_factory.assert_not_called()

    @pytest.mark.usefixtures("configured_runner")
    @patch("src.testing.runner.ThreadPoolExecutor")
    def test_unreachable_simulation_is_rejected_before_startup(
        self, executor_factory
    ):
        with pytest.raises(ValueError, match="less than measurements_count"):
            main.main(count=1, simulate_error_after=1)
        executor_factory.assert_not_called()

    @pytest.mark.usefixtures("configured_runner")
    @patch("src.testing.runner.ThreadPoolExecutor")
    @patch("threading.Event.wait", return_value=False)
    def test_port_conflict_names_ammeter_and_port(self, wait, executor_factory):
        executor = executor_factory.return_value.__enter__.return_value
        executor.submit.return_value.done.return_value = True
        executor.submit.return_value.result.side_effect = OSError("address in use")

        with pytest.raises(
            RuntimeError, match="greenlee ammeter could not start on port 5001: address in use"
        ):
            main.main()

    @pytest.mark.integration
    def test_occupied_port_stops_run_without_saving_history(
        self, tmp_path, monkeypatch, runtime_config
    ):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("localhost", 0))
            listener.listen()
            port = listener.getsockname()[1]
            config = {
                **runtime_config,
                "ports": {**runtime_config["ports"], "greenlee": port},
            }
            monkeypatch.setattr("src.testing.runner.load_runtime_config", lambda path: config)
            database = tmp_path / "history.sqlite3"

            with pytest.raises(RuntimeError, match=f"greenlee ammeter could not start on port {port}"):
                main.main("greenlee", count=1, database=database)

            assert not database.exists()

    @pytest.mark.usefixtures("configured_runner")
    @patch(
        "src.testing.runner.request_current_from_ammeter",
        side_effect=OSError("request failed"),
    )
    @patch("Ammeters.base_ammeter.AmmeterEmulatorBase.start_server")
    def test_request_failure_stops_and_joins_workers(self, start_server, request):
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

    @pytest.mark.parametrize("timeout", [False, True])
    @patch("Ammeters.base_ammeter.socket.socket")
    def test_invalid_command_or_timeout_is_logged(self, socket_factory, timeout, caplog):
        server = socket_factory.return_value.__enter__.return_value
        connection = MagicMock()
        server.accept.return_value = (connection, ("localhost", 1234))
        stop = threading.Event()

        def receive(size):
            stop.set()
            if timeout:
                raise socket.timeout()
            return b"WRONG"

        connection.recv.side_effect = receive
        GreenleeAmmeter(5001).start_server(stop=stop)

        expected = "timed out waiting for a command" if timeout else "invalid or incomplete command"
        assert "GreenleeAmmeter on port 5001" in caplog.text
        assert expected in caplog.text

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
