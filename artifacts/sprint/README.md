# Sprint evidence

Outputs captured while the gates were run. Each file is the unedited output
of the command named in it, with one normalisation: the absolute path of the
repository is shown as `<repo>`. No credential, database dump or uploaded
file is stored here.

## Where the evidence was produced

Two environments. Each file says which one it comes from.

**Build machine** (files `day1-*`, `day2-*`, `day3-*` unless marked `ci-`):

| Item | What was used | Difference from the project default |
|---|---|---|
| Python | 3.12.16, compiled from the official CPython source tag `v3.12.16` | None in version. uv could not download its managed build there |
| Dependencies | `uv sync --frozen` from the committed `uv.lock` (uv 0.13.9) | None |
| PostgreSQL | 16.2, two instances shaped like the Compose services: same user, passwords, database names and ports | Started directly from PostgreSQL binaries, **not through Docker**: the machine has no Docker. The Compose file pins 16.16 |
| Addresses | `127.0.0.2` for both databases and the API | The project default is `127.0.0.1`. That machine forwards every listener on `127.0.0.1` to an external interface, and neither a database nor an API without authentication may be reachable from outside |

**GitHub Actions** (files `ci-*`): a clean checkout on `ubuntu-24.04` with
the official Python 3.12, `uv sync --frozen`, and PostgreSQL 16.16 started by
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
