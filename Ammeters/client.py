import math
import time
from socket import socket, AF_INET, SOCK_STREAM


def request_current_from_ammeter(port: int, command: bytes, timeout: float = 5) -> float:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    deadline = time.monotonic() + timeout

    def set_remaining_timeout(s):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Measurement request to port {port} timed out")
        s.settimeout(remaining)

    with socket(AF_INET, SOCK_STREAM) as s:
        set_remaining_timeout(s)
        s.connect(('localhost', port))
        set_remaining_timeout(s)
        s.sendall(command)
        data = bytearray()
        while True:
            set_remaining_timeout(s)
            chunk = s.recv(1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > 1024:
                raise ValueError(f"Measurement response from port {port} is too long")

    if not data:
        raise ConnectionError(f"No measurement received from port {port}")
    try:
        measurement = float(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"Invalid measurement received from port {port}") from error
    if not math.isfinite(measurement):
        raise ValueError(f"Non-finite measurement received from port {port}")
    return measurement

