# Sprint evidence

Outputs captured while the gates were run. A `.txt` file is the output of
the command named in its first lines, with one normalisation: absolute paths
are shown as `<repo>` (the repository), `<evidence>` (the folder the run
wrote to) and `<tools>` (helper scripts of the build machine that are not
part of the repository). A `.json` file is a response of the API, or a file
a script wrote, unchanged. Where a file was put together from several
commands, it says so. No credential, database dump or uploaded file is
stored here.

The Day 3 files name the code they were produced on by the Git tree hashes
of `services/api`, `scripts` and `data`. Commits that change only documents,
the workflow or this folder leave those hashes as they are.

## Where the evidence was produced

Two environments.

**Build machine** (every file in this folder):

| Item | What was used | Difference from the project default |
|---|---|---|
| Python | 3.12.16, compiled from the official CPython source tag `v3.12.16` | None in version. uv could not download its managed build there |
| Dependencies | `uv sync --frozen` from the committed `uv.lock` (uv 0.13.9) | None |
| PostgreSQL | 16.2, two instances shaped like the Compose services: same user, passwords, database names and ports | Started directly from PostgreSQL binaries, **not through Docker**: the machine has no Docker. The Compose file pins 16.16 |
| Addresses | `127.0.0.2` for both databases and the API | The project default is `127.0.0.1`. That machine forwards every listener on `127.0.0.1` to an external interface, and neither a database nor an API without authentication may be reachable from outside |

**GitHub Actions**: a clean checkout on `ubuntu-24.04` with the official
Python 3.12, `uv sync --frozen`, and PostgreSQL 16.16 started by
`infra/docker-compose.yml`. This is the only place the Compose file, the
named volume and the container restart are exercised.

## Files

| File | Gate | Content |
|---|---|---|
| `day1-clean-install.txt` | G1 | `make setup` in an empty copy of the repository; application import; lockfile unchanged |
| `day1-health-live.json`, `day1-health-ready.json` | G1 | Health responses of the running API |
| `day1-health-ready-db-stopped.txt` | G1 | Readiness 503 and liveness 200 while PostgreSQL was stopped; readiness 200 again after it was started, without restarting the API |
| `day1-openapi.json` | G1 | The OpenAPI document served on Day 1 |
| `day1-alembic.txt` | G1 | Alembic reaches the database and sees the model metadata |
| `day1-test-results.txt` | G1 | The verification chain: configuration, lockfile, databases, migrations, Ruff, mypy, tests, OpenAPI |
| `day2-migration-review.txt` | G2 | The review checklist of migration 0001 and the SQL it executes |
| `day2-preview-equipment.json` | G2 | Preview response for `data/samples/validation_examples/equipment_with_issues.csv` |
| `day2-canonical-counts-before-after.txt` | G2 | Row counts of every table before and after that preview |
| `day2-test-results.txt` | G2 | The verification chain at the end of Day 2 (503 tests) |
| `day3-full-test-results.txt` | G3 | The verification chain and the end-to-end demonstration on the final code, from an empty migrated database: 689 tests, import over HTTP, repeat, seed, restart, compare |
| `day3-verify-summary.json` | G3 | The same run as a list of steps with their results |
| `day3-import-results.json` | G3 | Preview and commit response of each of the eight files, as the API returned them on the first import |
| `day3-world-state.json` | G3 | The World State after the import: the workspace view, and the project view with its history |
| `day3-commitment-history.json` | G3 | The two commitment versions of `PO-1007`, each with its source row |
| `day3-restart-proof.txt` | G3 | Timeline of the end-to-end run: the checksum of the World State before and after the restart of the API and of PostgreSQL |
| `day3-database-counts.txt` | G3 | Row counts in PostgreSQL next to the counts of the World State; the batches; the provenance links. Put together from `psql` queries and one API call |
| `day3-defect-detection.txt` | G3 | `scripts/defect_detection.py`: 26 deliberate defects, each detected by a failing test |
| `day3-commit-validation.txt` | G3 | Checks and tests at each of the thirteen commits of Day 3. Put together from one run per commit |
| `day3-known-limitations.md` | G3 | Copy of `docs/engineering/known-limitations.md` as it stood at the gate |

The results of the CI runs are not files in this folder. They are recorded
in `docs/engineering/implementation-log.md`, under "Continuous integration",
with the number of the run; the output files of a run are kept by GitHub as
artifacts of that run for 30 days.
