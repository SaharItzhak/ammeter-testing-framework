# Ammeter Emulators

This project provides emulators for different types of ammeters: Greenlee, ENTES, and CIRCUTOR. Each ammeter emulator runs on a separate thread and can respond to current measurement requests.

## Project Structure

- `main.py`: Script to start the ammeter emulators.
- `Ammeters/`
  - `Circutor_Ammeter.py`: Emulator for the CIRCUTOR ammeter.
  - `Entes_Ammeter.py`: Emulator for the ENTES ammeter.
  - `Greenlee_Ammeter.py`: Emulator for the Greenlee ammeter.
  - `base_ammeter.py`: Base class for all ammeter emulators.
  - `client.py`: Client to request current measurements from the ammeter emulators.
- `config/`
  - `config.yaml`: Configuration file for the ammeter emulators.
- `Exam/`
  - `ammeter-test-specification.md`: Exercise requirements.
- `examples/`
  - `run_tests.py`: Example of sampling from all three emulators.
- `src/`
  - `testing/`
    - `test_framework.py`: Timed sampling of ammeter measurements.
  - `utils/`
    - `config.py`: Configuration settings.
    - `logger.py`: Logging setup.
    - `Utils.py`: Utility functions, including `generate_random_float`.

## Usage

Read the [exercise specification](Exam/ammeter-test-specification.md) before
starting. The baseline emulators use the Python 3 standard library.

To create an isolated environment, run `python -m venv .venv` from the project
root, then activate it:

- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- macOS or Linux: `source .venv/bin/activate`

Additional packages are listed in `requirements.txt`; install them with
`python -m pip install -r requirements.txt` if needed for framework work.

`main.py` starts the selected emulators, waits until each is listening (up to
five seconds per emulator), and samples each one before exiting. By default it
requests one measurement from each.
Servers are stopped and their worker threads are joined on exit, including when
a request fails. Socket timeouts prevent idle clients from blocking shutdown.
Greenlee prints resistance in `ohms` to avoid output encoding errors on
terminals that cannot display the ohm symbol.

## Greenlee Ammeter

- **Port**: 5001
- **Command**: `MEASURE_GREENLEE -get_measurement`
- **Measurement Logic**: Calculates current using voltage (1V - 10V) and (0.1Ω - 100Ω).
- **Measurement method** : Ohm's Law: I = V / R

## ENTES Ammeter

- **Port**: 5002
- **Command**: `MEASURE_ENTES -get_data`
- **Measurement Logic**: Calculates current using magnetic field strength (0.01T - 0.1T) and calibration factor (500 - 2000).
- **Measurement method** : Hall Effect: I = B * K

## CIRCUTOR Ammeter

- **Port**: 5003
- **Command**: `MEASURE_CIRCUTOR -get_measurement -current`
- **Measurement Logic**: Calculates current using voltage values (0.1V - 1.0V) over a number of samples and a random time step (0.001s - 0.01s).
- **Measurement method** : Rogowski Coil Integration: I = ∫V dt

To start the emulators and request measurements, run:
```sh
python main.py
```

For example, sample Greenlee up to five times at two measurements per second,
with a three-second maximum duration:

```sh
python main.py --ammeter greenlee --count 5 --frequency 2 --duration 3
```

`--ammeter` accepts `all`, `greenlee`, `entes`, or `circutor`; the other
parameters must be positive. For `all`, each ammeter is sampled sequentially
with its own duration limit. Sampling stops at the requested count or when the
next measurement cannot start within the duration. A request that times out or
exceeds the duration raises an error instead of returning a partial success.
The framework returns measurement values and elapsed times; the command prints
the measurements and a count/stop-reason summary.

The original `config/config.yaml` is not used by this sampling interface yet.
The example can also be run from the project root using:

```sh
python -m examples.run_tests
```

Run the test suite with:

```sh
python -m unittest discover -s tests -v
```