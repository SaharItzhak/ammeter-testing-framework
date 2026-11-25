import math
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework


class EmulatorIntegrationTests(unittest.TestCase):
    def test_each_emulator_returns_a_measurement_over_tcp(self):
        for ammeter_type in (GreenleeAmmeter, EntesAmmeter, CircutorAmmeter):
            with self.subTest(ammeter=ammeter_type.__name__):
                sockets = []

                def create_socket(*args):
                    server_socket = socket.socket(*args)
                    sockets.append(server_socket)
                    return server_socket

                socket_module = SimpleNamespace(
                    socket=create_socket,
                    AF_INET=socket.AF_INET,
                    SOCK_STREAM=socket.SOCK_STREAM,
                    timeout=socket.timeout,
                )
                ready = threading.Event()
                stop = threading.Event()
                ammeter = ammeter_type(0)
                with patch("Ammeters.base_ammeter.socket", socket_module):
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        server = executor.submit(ammeter.start_server, ready, stop)
                        try:
                            if not ready.wait(timeout=3):
                                if server.done():
                                    server.result()
                                self.fail("Emulator did not start")
                            port = sockets[0].getsockname()[1]
                            measurement = request_current_from_ammeter(
                                port, ammeter.get_current_command
                            )
                            self.assertTrue(math.isfinite(measurement))
                            self.assertGreater(measurement, 0)
                            ammeter.port = port
                            framework = AmmeterTestFramework({"meter": ammeter})
                            result = framework.run_test("meter", 2, 3, 50)
                            self.assertEqual(result["stop_reason"], "count")
                            self.assertEqual(len(result["measurements"]), 2)
                        finally:
                            stop.set()
                    server.result()


if __name__ == "__main__":
    unittest.main()
