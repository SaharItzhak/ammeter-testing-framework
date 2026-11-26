# Decisions and Change Log

This document records implementation choices and changes made after the
original project was uploaded. Commit IDs link decisions to their code changes.
Planned or optional work is not described as completed.

## `e5c243f` — Original project baseline

- The supplied exercise files were uploaded unchanged to preserve a baseline
  for comparison. Included files were checked byte-for-byte against the
  archive.
- `.idea`, `__pycache__`, and compiled files were excluded as local or generated
  artifacts. The exercise PDF was retained.
- Files were checked for secrets and sensitive local paths before publication.
  This reduces risk but cannot prove that no sensitive data exists.

## `c932284` — Local files and generated artifacts

- `.gitignore` excludes IDE settings, virtual environments, Python and pytest
  caches, `.env` files, and generated log files.
- Ignore rules do not remove tracked files and are not a substitute for
  reviewing changes before publication or storing secrets securely.

## `8882448`, `187100e` — Starting instructions

- README emulator filenames, ports, and the CIRCUTOR command were aligned with
  the code. The original startup behavior, which did not request measurements,
  was documented accurately.
- The exercise instructions, virtual environment steps, and dependency
  installation guidance were added. The baseline emulators use the Python
  standard library.

## `fa63d2b` — Request measurements from each emulator

- `main.py` was updated to send each emulator its documented measurement
  command, as required by the setup portion of the exercise.
- Greenlee's Ohm symbol was replaced with `ohms` after it caused an encoding
  error in the tested terminal. The calculation was unchanged.

## `a6a623b` — Wait for server readiness

- A readiness event replaced the fixed `sleep(5)`. Each server signals after
  listening, and the client waits for that signal before requesting a reading.
- Readiness has a five-second timeout so a failed startup is reported instead
  of waiting indefinitely. This is a practical limit, not a startup-time
  guarantee.

## `a7b8d87` — Stop servers and worker threads

- `ThreadPoolExecutor` replaced daemon threads. A stop event is set in
  `finally`, and leaving the executor waits for its workers.
- Socket timeouts let idle clients and listeners periodically check for the
  stop signal. Client connection and response waits are bounded.
- Worker exceptions are surfaced, and tests cover startup failure, idle
  clients, request failures, and shutdown. Tests do not prove every possible
  thread interleaving is safe.

## CI and test framework

- GitHub Actions runs `unittest` on Windows and Ubuntu with Python 3.12. The
  exercise does not require multiple Python versions, so the matrix was kept
  small while still checking two operating systems.
- `unittest` was chosen because it is included with Python and avoids another
  test dependency. CI has read-only repository permissions and runs tests; it
  does not deploy the application.

## Measurement client and TCP tests

- The shared client returns a numeric value for each emulator, reads until the
  response is complete, and rejects empty, non-numeric, non-finite, oversized,
  or timed-out responses.
- Integration tests use real local TCP sockets, including the three emulator
  implementations. The operating system chooses temporary ports for tests to
  reduce conflicts with other services.

## Sampling and statistics

- `AmmeterTestFramework` accepts a mapping of running emulators and returns a
  consistent result structure with current readings, elapsed times, and a
  stop reason.
- Sampling is bounded by the requested count and duration, and scheduled at a
  maximum frequency. A monotonic clock is used; this is not a real-time timing
  guarantee.
- Mean, median, minimum, maximum, and population standard deviation are
  computed with Python's standard `statistics` module. A single reading has
  zero population deviation. Empty results use `None` rather than invented
  statistics.

## `5e65fb9` — Local run history

- Completed emulator runs are stored transactionally in a local SQLite
  database. Each record includes a UUID, UTC timestamps, sampling settings,
  raw measurements, stop reason, and statistics.
- SQLite was selected because it is built into Python and supports local
  retrieval and comparison without an external service.
- The default database is `results/history.sqlite3`, which is ignored by Git.
  History is local, unencrypted, and not automatically backed up or shared
  between machines.
- `list`, `show`, and `compare` provide terminal alternatives for inspecting
  saved runs. Differences are second run minus first and do not establish
  measurement accuracy.

## `977dd61`, `5013e93` — Runtime configuration

- Emulator ports, sampling defaults, and the history database path are read
  from `config/config.yaml`. CLI options can override sampling values for one
  run, and `--config` selects another configuration file.
- PyYAML is the only external runtime dependency. The README documents
  installing it with `python -m pip install -r requirements.txt` in a virtual
  environment.
- Configuration values are validated, including port uniqueness and positive
  sampling parameters. Invalid YAML and missing or malformed settings produce
  actionable errors.

## `46b1399` — History error handling

- Empty or missing history is reported as an empty state. Missing run IDs and
  malformed databases produce concise errors instead of tracebacks.
- Runs with no measurements are not saved as successful results. Earlier
  completed runs remain stored if a later emulator fails.

## `d7c817b`, `9847c89` — Fresh-clone and Windows fixes

- The default configuration is tested directly, and the README gives explicit
  dependency installation and run instructions. Example measurements are
  labeled as emulator output, not accuracy claims.
- A Windows CI failure exposed an SQLite connection left open in the empty
  database test. The test now closes it explicitly before temporary-file
  cleanup.

## `a1b5f23` — Local browser history report

- A self-contained HTML report provides run summaries, search by run ID,
  ammeter filtering, expandable measurements and statistics, and comparisons
  between two runs.
- Successful CLI runs regenerate and open the report. The
  `python -m src.testing.history report` command opens it without starting a
  new measurement.
- The report is generated next to its SQLite database. The default output is
  `results/history.html`; generated HTML under `results` is ignored by Git.
- The report uses only the local database and standard-library browser support.
  It does not start a web server or upload results to GitHub Pages or another
  service. Its HTML escapes values read from the database.
- Comparisons show numeric differences only. Without a known reference value,
  they do not determine which ammeter is more accurate.

## Safer and more informative reports

- The default run requests five readings per ammeter at 5 Hz to make the
  statistics and time plot more informative. Timing uses a monotonic clock,
  but OS scheduling and request latency do not provide real-time guarantees.
- Runs generate the local report without opening a browser unless
  `--open-report` is requested. Automated tests mock browser launching.
- Report generation avoids overwriting the SQLite database, including when
  the database ends in `.html` or the report path is a hard link to it.
- The report plots current against elapsed time and can calculate errors
  against a user-supplied constant reference. This does not establish accuracy
  for the supplied independent random emulators without controlled inputs and
  a traceable reference.
