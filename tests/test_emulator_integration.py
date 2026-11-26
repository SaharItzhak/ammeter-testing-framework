import math
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework

pytestmark = pytest.mark.integration


@pytest.fixture(params=[GreenleeAmmeter, EntesAmmeter, CircutorAmmeter])
def running_ammeter(request):
    sockets = []

    def create_socket(*args):
        server_socket = socket.socket(*args)
        sockets.append(server_socket)
        return server_socket

    socket_module = SimpleNamespace(
        socket=create_socket,
        AF_INET=socket.AF_INET,
        SOCK_STREAM=socket.SOCK_STREAM,
        SOL_SOCKET=socket.SOL_SOCKET,
        SO_REUSEADDR=socket.SO_REUSEADDR,
        timeout=socket.timeout,
    )
    ready = threading.Event()
    stop = threading.Event()
    ammeter = request.param(0)
    with patch("Ammeters.base_ammeter.socket", socket_module):
        with ThreadPoolExecutor(max_workers=1) as executor:
            server = executor.submit(ammeter.start_server, ready, stop)
            try:
                if not ready.wait(timeout=3):
                    if server.done():
                        server.result()
                    pytest.fail("Emulator did not start")
                ammeter.port = sockets[0].getsockname()[1]
                yield ammeter
            finally:
                stop.set()
        server.result()


def test_each_emulator_returns_measurements_over_tcp(running_ammeter):
    ammeter = running_ammeter
    measurement = request_current_from_ammeter(ammeter.port, ammeter.get_current_command)
    assert math.isfinite(measurement)
    assert measurement > 0
    with socket.create_connection(("localhost", ammeter.port), timeout=3) as client:
        command = ammeter.get_current_command
        split = len(command) // 2
        client.sendall(command[:split])
        client.settimeout(0.1)
        with pytest.raises(socket.timeout):
            client.recv(1024)
        client.sendall(command[split:])
        client.settimeout(3)
        assert float(client.recv(1024)) > 0
    framework = AmmeterTestFramework({"meter": ammeter})
    result = framework.run_test("meter", 2, 3, 50)
    assert result["stop_reason"] == "count"
    assert len(result["measurements"]) == 2
