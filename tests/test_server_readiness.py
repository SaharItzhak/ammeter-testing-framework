import socket
import threading
import unittest
from unittest.mock import MagicMock, patch

import main
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter


class ServerReadinessTests(unittest.TestCase):
    @patch("main.ThreadPoolExecutor")
    @patch("threading.Event.wait", return_value=False)
    def test_startup_timeout_is_reported(self, wait, executor_factory):
        executor = executor_factory.return_value.__enter__.return_value
        executor.submit.return_value.done.return_value = False
        with self.assertRaisesRegex(RuntimeError, "GreenleeAmmeter did not start"):
            main.main()

        self.assertEqual(executor.submit.call_count, 3)
        self.assertTrue(executor.submit.call_args.args[2].is_set())
        wait.assert_called_once_with(timeout=5)

    @patch("main.request_current_from_ammeter", side_effect=OSError("request failed"))
    @patch("Ammeters.base_ammeter.AmmeterEmulatorBase.start_server")
    def test_request_failure_stops_and_joins_workers(self, start_server, request):
        stopped = []

        def serve(ready, stop):
            ready.set()
            if not stop.wait(timeout=2):
                raise RuntimeError("worker was not stopped")
            stopped.append(threading.current_thread())

        start_server.side_effect = serve
        with self.assertRaisesRegex(OSError, "request failed"):
            main.main()

        self.assertEqual(len(stopped), 3)
        self.assertTrue(all(not worker.is_alive() for worker in stopped))

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
        connection.settimeout.assert_called_once_with(1)
        connection.__exit__.assert_called_once()
        socket_factory.return_value.__exit__.assert_called_once()

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_ready_is_set_after_listening(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        ready = threading.Event()

        def stop_after_ready():
            self.assertTrue(ready.is_set())
            server.listen.assert_called_once_with()
            raise RuntimeError("stop server")

        server.accept.side_effect = stop_after_ready
        with self.assertRaisesRegex(RuntimeError, "stop server"):
            GreenleeAmmeter(5001).start_server(ready)

    @patch("Ammeters.base_ammeter.socket.socket")
    def test_bind_failure_does_not_signal_readiness(self, socket_factory):
        server = socket_factory.return_value.__enter__.return_value
        server.bind.side_effect = OSError("address in use")
        ready = threading.Event()

        with self.assertRaisesRegex(OSError, "address in use"):
            GreenleeAmmeter(5001).start_server(ready)

        self.assertFalse(ready.is_set())
        server.listen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
