import socket
from concurrent.futures import ThreadPoolExecutor

import pytest

from Ammeters.client import request_current_from_ammeter

pytestmark = pytest.mark.integration


def test_measurement_over_tcp():
    command = b"MEASURE_TEST"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        port = listener.getsockname()[1]

        def serve():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3)
                received = bytearray()
                while len(received) < len(command):
                    chunk = connection.recv(len(command) - len(received))
                    if not chunk:
                        raise ConnectionError("Client disconnected before sending the command")
                    received.extend(chunk)
                connection.sendall(b"12.5")
                return bytes(received)

        with ThreadPoolExecutor(max_workers=1) as executor:
            server = executor.submit(serve)
            result = request_current_from_ammeter(port, command)
            assert server.result(timeout=3) == command

    assert result == 12.5
