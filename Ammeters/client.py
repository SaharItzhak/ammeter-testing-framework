import math
from socket import socket, AF_INET, SOCK_STREAM


def request_current_from_ammeter(port: int, command: bytes) -> float:
    with socket(AF_INET, SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(('localhost', port))
        s.sendall(command)
        data = bytearray()
        while True:
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
    print(f"Received current measurement from port {port}: {measurement} A")
    return measurement

