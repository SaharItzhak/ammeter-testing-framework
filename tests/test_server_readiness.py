import runpy
import threading
import unittest
from unittest.mock import patch

from Ammeters.Greenlee_Ammeter import GreenleeAmmeter


class ServerReadinessTests(unittest.TestCase):
    @patch("threading.Thread.start")
    @patch("threading.Event.wait", return_value=False)
    def test_startup_timeout_is_reported(self, wait, start):
        with self.assertRaisesRegex(RuntimeError, "Greenlee ammeter did not start"):
            runpy.run_module("main", run_name="__main__")

        self.assertEqual(start.call_count, 3)
        wait.assert_called_once_with(timeout=5)

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
