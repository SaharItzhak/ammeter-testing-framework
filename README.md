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
    - `test_framework.py`: Timed sampling and statistical summaries.
  - `utils/`
    - `config.py`: Configuration settings.
    - `logger.py`: Logging setup.
    - `Utils.py`: Utility functions, including `generate_random_float`.

## Usage

Read the [exercise specification](Exam/ammeter-test-specification.md) before
starting. Use Python 3.9 or newer. The emulators use the Python standard
library; the configuration loader requires PyYAML.

To create an isolated environment, run `python -m venv .venv` from the project
root, then activate it:

- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- macOS or Linux: `source .venv/bin/activate`

Install the project's runtime dependency:

```sh
python -m pip install -r requirements.txt
```

The default ammeter ports, sampling count, duration, and frequency are read
from `config/config.yaml`. Edit that file for repeatable settings. Command-line
options such as `--count` and `--frequency` override the corresponding
configuration value for one run; `--config path` selects another YAML file.

`main.py` starts the selected emulators, waits until each is listening (up to
five seconds per emulator), and samples each one before exiting. By default it
requests up to five measurements from each at 5 Hz, within five seconds per
ammeter.
Servers are stopped and their worker threads are joined on exit, including when
a request fails. Socket timeouts prevent idle clients from blocking shutdown.
On Unix-like systems, the listening sockets allow immediate reuse after
shutdown, so consecutive runs do not fail because of TCP `TIME_WAIT`.
Greenlee prints resistance in `ohms` to avoid output encoding errors on
terminals that cannot display the ohm symbol.
After a successful run, the project creates `results/history.html` and prints
its path without opening a browser. Use `python main.py --open-report` to open
it automatically, or run `python -m src.testing.history report` later. The
report stays local and is excluded from Git.

If a configured port is already in use, change its value in
`config/config.yaml` before running the emulators.

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

For a one-time override, sample Greenlee up to five times at two measurements
per second, with a three-second maximum duration:

```sh
python main.py --ammeter greenlee --count 5 --frequency 2 --duration 3
```

`--ammeter` accepts `all`, `greenlee`, `entes`, or `circutor`. For `all`, each
ammeter is sampled sequentially with its own duration limit. Sampling stops at
the requested count or when the next measurement cannot start within the
duration. A request that times out or exceeds the duration raises an error
instead of returning a partial success.
Scheduling uses a monotonic clock, but OS scheduling and network latency can
introduce jitter; this is not a real-time timing guarantee.
Timing reports the target and mean intervals between consecutive request
starts, along with their mean and maximum absolute deviations from the target.
These measurements describe request scheduling, not hardware acquisition
times. At least two readings are required to calculate timing.
The framework returns measurement values, elapsed times, and mean, median,
minimum, maximum, and population standard deviation in amperes. For a single
measurement the population standard deviation is zero; if there are no
measurements, the statistics are `None`. The command prints the measurements,
count, stop reason, and statistics.

Example from one successful default run (five emulator readings per ammeter;
all currents are in amperes):

| Ammeter | Measurements |
| --- | --- |
| Greenlee | 0.348055, 0.349531, 1.262272, 0.500402, 0.080923 |
| ENTES | 27.703703, 130.482656, 30.132014, 142.984111, 165.967718 |
| CIRCUTOR | 0.016365, 0.018602, 0.020084, 0.026193, 0.020610 |

| Ammeter | Mean | Median | Population std. dev. | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Greenlee | 0.508237 | 0.349531 | 0.400518 | 0.080923 | 1.262272 |
| ENTES | 99.454040 | 130.482656 | 58.711780 | 27.703703 | 165.967718 |
| CIRCUTOR | 0.020371 | 0.020084 | 0.003262 | 0.016365 | 0.026193 |

Values are rounded for display and generated randomly; they are not accuracy
claims. New runs produce different readings.

### Run history

Each completed ammeter run is saved to `results/history.sqlite3` and its
unique ID is printed. The database contains UTC start/save times,
sampling parameters, raw measurements, and statistics. The default database is
local and ignored by Git. Set `--database path` on `main.py` to use another
location; custom database paths are not necessarily ignored by Git.

From the project root, inspect the default database using:

```sh
python -m src.testing.history report
python -m src.testing.history list
python -m src.testing.history show RUN_ID
python -m src.testing.history compare FIRST_RUN_ID SECOND_RUN_ID
```

`report` refreshes and opens the complete visual history without starting a new
measurement. It includes search, ammeter filtering, per-run details, a plot of
current over time, and comparison of two runs. For a custom database, the
report is saved beside that database with an `.html` extension. If the
database itself ends in `.html`, the report uses `.html.report.html` instead;
an existing hard link to the database is never overwritten. `list`, `show`, and `compare` remain
available as terminal alternatives. If no run has been saved yet, the report
explains how to start; terminal commands give clear messages for empty history
or missing IDs.

For a custom database, add `--database path` before the command. Comparison
shows both records and statistical differences (second minus first); those
differences alone do not establish device accuracy. If a measurement request
fails after earlier readings, those readings and the error are saved as a
**failed, partial** run; the command exits nonzero and prints its run ID.
Refresh the report command above to see it. An error before the first reading
does not create a run. Previously completed runs remain saved. Unexpected
process termination or a storage failure cannot guarantee partial results.

For a run measured against a known constant reference current under the same
conditions, expand its details and enter that reference to calculate mean
signed error, mean absolute error, and root mean square error. The entered
reference is not saved. The supplied emulators generate independent random
values and do not provide a known reference, so comparing their results does
not identify the most accurate or reliable meter. A defensible accuracy
assessment requires controlled common inputs, traceable reference measurements,
and appropriate uncertainty analysis.

The example can also be run from the project root using:

```sh
python -m examples.run_tests
```

Run the test suite with:

```sh
python -m unittest discover -s tests -v
```

The test suite reports pass or fail in the terminal. It uses temporary data
and does not open a visible browser or create a persistent HTML test report.
The HTML history dashboard contains measurement results from `python main.py`;
it is not a report of the automated test suite.

The browser tests require Playwright and its headless Chromium. Install these
test-only dependencies before running the suite; otherwise the browser tests
are explicitly skipped:

```sh
python -m pip install -r requirements-dev.txt
```

In Windows PowerShell, install Chromium while preserving other Playwright
browser caches:

```powershell
$env:PLAYWRIGHT_SKIP_BROWSER_GC = "1"
python -m playwright install chromium
```

On macOS or Linux, use
`PLAYWRIGHT_SKIP_BROWSER_GC=1 python -m playwright install chromium`.
Linux may also require the system packages documented by Playwright; CI uses
`python -m playwright install --with-deps chromium`.