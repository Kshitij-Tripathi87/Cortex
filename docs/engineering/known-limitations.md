# Known limitations

Cortex Nexus v0.1 is a local engineering prototype of the data foundation.
It is not production-ready, and nothing below is hidden by a default or a
dashboard. Severity uses the scale of the playbook (P0 blocker to P3 polish);
no P0 or P1 defect is open.

## Not built, by design of this sprint

| ID | Limitation | Before it matters |
|---|---|---|
| L-01 | **No authentication or authorisation.** The API serves one workspace named in the configuration and treats nobody as a user. It refuses to start with that configuration outside `development` and `test`, and must stay on loopback | Before any exposure beyond a developer machine: authenticated identity, workspace membership checked on every route, roles |
| L-02 | No intelligence of any kind: no lateness, risk, score, forecast or recommendation. The World State reports facts and what is not recorded | Phase 2 (deterministic findings over the World State) |
| L-03 | No agent, language model, vector store, queue or cache | Later phases, after L-02 |
| L-04 | No frontend | After the API contract has settled |
| L-05 | No deployment: no TLS, secrets manager, backup and restore, monitoring, rate limiting, malware scanning of uploads | A production-readiness phase of its own |
| L-06 | No integration with ERP, email, supplier portals or documents | Per integration |

## Limits of what was built

| ID | Limitation | Severity | Detail |
|---|---|---|---|
| L-10 | Preview and commit are synchronous and hold the request | P2 | Bounded by `MAX_UPLOAD_SIZE_MB` (20) and `MAX_IMPORT_ROWS` (10,000). Larger imports need a job runner |
| L-11 | A commit locks every record its rows refer to | P2 | Two imports that touch the same records run one after the other. If they take locks in an order that deadlocks, PostgreSQL ends one; that batch fails cleanly and the file can be submitted again |
| L-12 | CSV must be UTF-8 and comma-separated | P2 | Semicolon-separated or other encodings are rejected with a clear error, not guessed |
| L-13 | Dates must be `YYYY-MM-DD` or a spreadsheet date cell | P2 | No per-import locale. `03/04/26` is an error on purpose |
| L-14 | Currency is checked for its shape (three letters), not against the ISO 4217 list | P3 | `XYZ` is accepted |
| L-15 | Natural keys are compared exactly | P2 | `TR-001` and `tr-001` are two records |
| L-16 | A blank cell cannot clear a value | P3 | By policy: blank means "not supplied". Clearing is an API update |
| L-17 | An import cannot move a record to another project or supplier | P3 | By policy (`IMMUTABLE_FIELD_CONFLICT`). There is no route for it either |
| L-18 | Line items are created with a purchase order or by import; there is no route to add or remove one | P2 | |
| L-19 | Nothing can be deleted or archived | P2 | By design for the sprint: no procurement fact is hard-deleted |
| L-20 | Project status transitions are not restricted | P3 | Any status may follow any other |
| L-21 | Merged cells, hidden rows and several tables on one worksheet are not understood | P2 | The first non-empty row is the header; everything below is data |
| L-22 | A formula cell without a stored result cannot be imported | P3 | Reported per row; formulas are never evaluated |
| L-23 | Uploaded files are not kept | P3 | The ledger keeps every source row, the file name, size and checksum. A retention and deletion policy is needed before customer data is used |
| L-24 | The row ledger holds source data without a retention limit | P2 | Same as L-23 |
| L-25 | World State is assembled on every request | P3 | Fine at this size; no projection cache until a measured need |
| L-26 | Data-quality warnings in the World State cover completeness only | P3 | Validity, consistency, uniqueness and referential integrity are enforced on write and reported on rejected source rows |
| L-27 | `COMMITTING` is never visible | P3 | It exists only inside the commit transaction; other sessions wait on the row lock |
| L-28 | Request ids are accepted from callers | P3 | Bounded format, used for correlation only |
| L-29 | The equipment specification holds four text attributes | P3 | `description`, `manufacturer`, `model`, `notes` |

## Limits of the verification

| ID | Limitation | Detail |
|---|---|---|
| V-01 | Docker Compose was never run on the machine the code was written on | That machine has no Docker. The Compose file, the named volume and the container restart are exercised by the CI workflow; `docs/engineering/implementation-log.md` records the run |
| V-02 | Local evidence was produced on PostgreSQL 16.2 started from binaries, on `127.0.0.2` | The Compose file pins 16.16 on `127.0.0.1`; CI uses that. See `artifacts/sprint/README.md` |
| V-03 | One contributor, working the three lanes in sequence | No independent review took place. The tests were written by the author of the code |
| V-04 | No load test, no long-running soak | Concurrency is tested with up to four simultaneous commits |
| V-05 | No file produced by a real source system was imported | The dataset is synthetic; XLSX files in the tests are written by openpyxl |
| V-06 | Coverage is not measured in CI | `make coverage` exists; the gates are scenario tests, not a percentage |
