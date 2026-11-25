import socket
import time
import random
from abc import ABC, abstractmethod
from threading import Event
from typing import Optional

NotImplementedErrorMsg = "Subclasses must implement this property."

class AmmeterEmulatorBase(ABC):
    def __init__(self, port: int):
        self.port = port
        random.seed(time.time())  # Seed the random number generator for each instance

    def start_server(self, ready: Optional[Event] = None, stop: Optional[Event] = None):
        """
        Starts the server to listen for client requests.
        Handles one client at a time until the optional stop event is set.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', self.port))
            s.listen()
            s.settimeout(0.2)
            print(f"{self.__class__.__name__} is running on port {self.port}")
            if ready is not None:
                ready.set()
            while stop is None or not stop.is_set():
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(1)
                    print(f"Connected by {addr}")
                    try:
                        data = conn.recv(1024)
                    except socket.timeout:
                        print(f"Client {addr} timed out waiting for a command")
                        continue
                    if data == self.get_current_command:
                        # Call the specific measure_current() method defined in subclasses
                        current = self.measure_current()
                        conn.sendall(str(current).encode('utf-8'))

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

