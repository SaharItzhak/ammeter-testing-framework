import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from Ammeters.client import request_current_from_ammeter


class TestClient:
    @patch("Ammeters.client.socket")
    def test_fragmented_response_returns_measurement(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.side_effect = [b"12.", b"34", b""]

        result = request_current_from_ammeter(5001, b"MEASURE")

        assert result == 12.34
        connection.connect.assert_called_once_with(("localhost", 5001))
        connection.sendall.assert_called_once_with(b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_empty_response_is_an_error(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.return_value = b""

        with pytest.raises(ConnectionError, match="No measurement.*5001"):
            request_current_from_ammeter(5001, b"MEASURE")

    @pytest.mark.parametrize(
        "chunks",
        [
            [b"not a number", b""],
            [b"\xff", b""],
            [b"nan", b""],
            [b"inf", b""],
            [b"1" * 1024, b"1"],
        ],
    )
    @patch("Ammeters.client.socket")
    def test_invalid_responses_are_rejected(self, socket_factory, chunks):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.side_effect = chunks
        with pytest.raises(ValueError):
            request_current_from_ammeter(5001, b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_socket_timeout_is_not_silenced(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        connection.recv.side_effect = socket.timeout("timed out")

        with pytest.raises(socket.timeout):
            request_current_from_ammeter(5001, b"MEASURE")

    @patch("Ammeters.client.socket")
    def test_timeout_budget_is_shared_across_response_chunks(self, socket_factory):
        connection = socket_factory.return_value.__enter__.return_value
        clock = SimpleNamespace(now=0.0)

        def recv(size):
            clock.now += 3
            return b"1"

        connection.recv.side_effect = recv
        with patch("Ammeters.client.time.monotonic", side_effect=lambda: clock.now):
            with pytest.raises(TimeoutError, match="timed out"):
                request_current_from_ammeter(5001, b"MEASURE", timeout=5)

        assert connection.recv.call_count == 2
