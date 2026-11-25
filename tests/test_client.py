import socket
import unittest
from unittest.mock import patch

from Ammeters.client import request_current_from_ammeter


class ClientTests(unittest.TestCase):
    @patch("Ammeters.client.socket")
    def test_fragmented_response_returns_measurement(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.side_effect = [b"12.", b"34", b""]

        result = request_current_from_ammeter(5001, b"MEASURE")

        self.assertEqual(result, 12.34)
        connection.connect.assert_called_once_with(("localhost", 5001))
        connection.sendall.assert_called_once_with(b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_empty_response_is_an_error(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.return_value = b""

        with self.assertRaisesRegex(ConnectionError, "No measurement.*5001"):
            request_current_from_ammeter(5001, b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_invalid_responses_are_rejected(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        for chunks in ([b"not a number", b""], [b"\xff", b""],
                       [b"nan", b""], [b"inf", b""], [b"1" * 1024, b"1"]):
            with self.subTest(response=chunks[0][:20]):
                connection.recv.side_effect = chunks
                with self.assertRaises(ValueError):
                    request_current_from_ammeter(5001, b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_socket_timeout_is_not_silenced(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.side_effect = socket.timeout("timed out")

        with self.assertRaises(socket.timeout):
            request_current_from_ammeter(5001, b"MEASURE")


if __name__ == "__main__":
    unittest.main()
