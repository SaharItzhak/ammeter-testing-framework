import argparse
import threading
from concurrent.futures import ThreadPoolExecutor

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.testing.test_framework import AmmeterTestFramework


def main(ammeter_type="all", count=1, duration=5.0, frequency=1.0):
    stop = threading.Event()
    ammeters = {
        "greenlee": GreenleeAmmeter(5001),
        "entes": EntesAmmeter(5002),
        "circutor": CircutorAmmeter(5003),
    }
    selected = ammeters if ammeter_type == "all" else {ammeter_type: ammeters[ammeter_type]}
    servers = [(ammeter, threading.Event()) for ammeter in selected.values()]
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
            framework = AmmeterTestFramework(selected, request=request_current_from_ammeter)
            for name in selected:
                result = framework.run_test(name, count, duration, frequency)
                print(f"{name}: {len(result['measurements'])} measurements ({result['stop_reason']})")
        finally:
            stop.set()
    for future in futures:
        future.result()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample current from ammeter emulators.")
    parser.add_argument("--ammeter", choices=("all", "greenlee", "entes", "circutor"), default="all")
    parser.add_argument("--count", type=int, default=1, help="maximum measurements per ammeter")
    parser.add_argument("--duration", type=float, default=5.0, help="maximum seconds per ammeter")
    parser.add_argument("--frequency", type=float, default=1.0, help="maximum measurements per second")
    args = parser.parse_args()
    main(args.ammeter, args.count, args.duration, args.frequency)
