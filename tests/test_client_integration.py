import socket
import unittest
from concurrent.futures import ThreadPoolExecutor

from Ammeters.client import request_current_from_ammeter


class ClientIntegrationTests(unittest.TestCase):
    def test_measurement_over_tcp(self):
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
                self.assertEqual(server.result(timeout=3), command)

        self.assertEqual(result, 12.5)


if __name__ == "__main__":
    unittest.main()
