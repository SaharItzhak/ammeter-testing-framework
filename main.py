import threading

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter


def run_greenlee_emulator(ready):
    greenlee = GreenleeAmmeter(5001)
    greenlee.start_server(ready)

def run_entes_emulator(ready):
    entes = EntesAmmeter(5002)
    entes.start_server(ready)

def run_circutor_emulator(ready):
    circutor = CircutorAmmeter(5003)
    circutor.start_server(ready)

if __name__ == "__main__":
    servers = [
        ("Greenlee", run_greenlee_emulator, threading.Event()),
        ("ENTES", run_entes_emulator, threading.Event()),
        ("CIRCUTOR", run_circutor_emulator, threading.Event()),
    ]
    for _, run_server, ready in servers:
        threading.Thread(target=run_server, args=(ready,), daemon=True).start()

    for name, _, ready in servers:
        if not ready.wait(timeout=5):
            raise RuntimeError(f"{name} ammeter did not start within 5 seconds")

    request_current_from_ammeter(5001, b'MEASURE_GREENLEE -get_measurement')
    request_current_from_ammeter(5002, b'MEASURE_ENTES -get_data')
    request_current_from_ammeter(5003, b'MEASURE_CIRCUTOR -get_measurement -current')
