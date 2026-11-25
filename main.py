import threading
from concurrent.futures import ThreadPoolExecutor

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter


def main():
    stop = threading.Event()
    servers = [
        (GreenleeAmmeter(5001), threading.Event()),
        (EntesAmmeter(5002), threading.Event()),
        (CircutorAmmeter(5003), threading.Event()),
    ]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        try:
            for ammeter, ready in servers:
                futures.append(executor.submit(ammeter.start_server, ready, stop))
            for (ammeter, ready), future in zip(servers, futures):
                if not ready.wait(timeout=5):
                    if future.done():
                        future.result()
                    raise RuntimeError(
                        f"{ammeter.__class__.__name__} did not start within 5 seconds"
                    )
            for ammeter, _ in servers:
                request_current_from_ammeter(ammeter.port, ammeter.get_current_command)
        finally:
            stop.set()
    for future in futures:
        future.result()


if __name__ == "__main__":
    main()
