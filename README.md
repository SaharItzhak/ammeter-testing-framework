# Ammeter Testing Framework

Python emulators for Greenlee, ENTES, and CIRCUTOR meters, plus a shared
sampling, analysis, and history workflow. See the [exercise
specification](Exam/ammeter-test-specification.md) and
[design decisions](DECISIONS.md).

## Setup

Use Python 3.9 or newer. From the repository directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, activate with `source .venv/bin/activate`.

## Run a test

```sh
python main.py
python main.py --ammeter greenlee --count 5 --frequency 2 --duration 3
```

The default test samples each emulator in turn. It waits for the selected
servers, prints a summary, and saves each run. CLI values
override the defaults in `config/config.yaml`; invalid sampling values are
rejected before any server starts. Configuration includes each meter's port
and command. The default configuration and history database resolve relative
to the repository, so `main.py` can be launched from another working directory.

To exercise the failure path after one successful reading:

```sh
python main.py --ammeter greenlee --simulate-error-after 1
```

The command exits with an error and saves the partial readings as a failed run.
This option is for testing error handling; it does not change normal runs.

## Results

Runs are stored in `results/history.sqlite3`; the HTML dashboard is
`results/history.html`. Open the report from the command line with:

```sh
python -m src.testing.history report
```

`python main.py --open-report` opens the report after a successful run;
without that flag, the command only prints the report path.

Other history commands:

```sh
python -m src.testing.history list
python -m src.testing.history show RUN_ID
python -m src.testing.history compare FIRST_RUN_ID SECOND_RUN_ID
```

The dashboard shows readings, summary statistics, timing, and run comparisons.
It reports coefficient of variation as a measure of within-run consistency.
To assess accuracy, expand a run and enter a known reference current measured
under the same conditions; the report calculates signed error, mean absolute
error, and RMSE. The random emulators do not provide a shared known input, so
their results cannot establish which meter is more accurate.

If a request fails after readings have been collected, the history keeps those
partial results and the error. A failure before the first reading does not
create a run. Existing completed runs are retained.

## Example output

The emulators generate random values; these sample readings are illustrative,
not accuracy claims.

| Ammeter | Readings (A) | Mean | Median | Std. dev. | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Greenlee | 0.348055, 0.349531, 1.262272, 0.500402, 0.080923 | 0.508237 | 0.349531 | 0.400518 | 0.080923 | 1.262272 |
| ENTES | 27.703703, 130.482656, 30.132014, 142.984111, 165.967718 | 99.454040 | 130.482656 | 58.711780 | 27.703703 | 165.967718 |
| CIRCUTOR | 0.016365, 0.018602, 0.020084, 0.026193, 0.020610 | 0.020371 | 0.020084 | 0.003262 | 0.016365 | 0.026193 |

## Tests

Run the exercise tests:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

These tests cover the exercise requirements and bonus challenges, including
sampling, analysis, result history, error handling, and configuration.

The optional dashboard-specific checks are separate from the exercise tests:

```sh
python -m pip install -r requirements-dashboard-tests.txt
python -m playwright install chromium
python -m pytest checks/dashboard
```

They include JavaScript checks in headless Chromium; those checks are skipped
if Chromium is unavailable. CI runs both groups on Windows and Ubuntu 24.04.
