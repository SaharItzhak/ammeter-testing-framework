# Design Decisions

## Structure and configuration

- `main.py` handles command-line arguments; configuration loading and run
  orchestration live in `src/testing/`.
- Sampling validation is shared by the configuration loader and test
  framework, so invalid CLI overrides are rejected before servers start.
- Ports, protocol commands, sampling defaults, and the history location are
  configurable in `config/config.yaml`. The default config and history paths
  are anchored to the repository, not the caller's working directory.
- The unused logger was removed. Console output is reserved for run summaries
  and errors; emulator internals do not print per-request diagnostics.

## Sampling and error handling

- One framework serves every ammeter and returns readings, elapsed times,
  summary statistics, and a stop reason.
- Sampling uses a monotonic clock and is bounded by the requested count and
  duration. Timing deviation describes request-start intervals, not hardware
  acquisition accuracy.
- `--simulate-error-after N` injects a connection failure after N successful
  readings. It exercises the same failure path as a real request error.
- Partial results from a failed run are saved when possible; the CLI still
  exits unsuccessfully. Failures before the first reading create no run.
- A startup error identifies the meter and port. Worker threads are stopped
  and joined even if startup or measurement fails.

## Results and analysis

- SQLite stores run IDs, UTC timestamps, settings, readings, and statistics.
  It is built into Python and keeps history local without adding a service.
- The HTML report is generated locally and does not upload data. It supports
  filtering, plots, run comparisons, and calculations against a user-supplied
  reference current. Its HTML, CSS, and JavaScript live in
  `src/testing/history_template.html`; Python prepares the data separately.
- Standard deviation and coefficient of variation describe variation within a
  run. They do not establish accuracy. Accuracy requires a known reference;
  the independent random emulators do not provide a common controlled input.
- The report avoids overwriting the history database. The database and report
  are excluded from Git.

## Dependencies and tests

- Runtime dependencies are PyYAML; tests use pytest and Playwright.
- Pytest covers configuration, sampling, networking, failure handling,
  history, and the report. Playwright runs the report JavaScript in Chromium.
- CI runs tests on Windows and Ubuntu 24.04.
- The original emulator formulas and default wire commands remain unchanged.
