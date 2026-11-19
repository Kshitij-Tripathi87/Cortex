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
| L-10 | Preview and commit are synchronous and hold the request; commit writes row by row | P2 | Bounded by `MAX_UPLOAD_SIZE_MB` (20) and `MAX_IMPORT_ROWS` (10,000). Measured once on the build machine (2 CPUs), not asserted by a test: a file of 5,000 equipment rows previews in 1.8 s and commits in 8.5 s; 5,000 line items 2.5 s and 11.3 s; 8,000 milestones 3.7 s and 26.2 s. A client with a shorter timeout sees no answer although the commit completes; sending the commit again returns the stored result. Larger imports need batched writes and a job runner |
| L-11 | A commit locks every record its rows refer to | P2 | Two imports that touch the same records run one after the other. An import takes its locks in one fixed order (record type, then the columns of the natural key), which is meant to keep two imports from deadlocking each other; that is reasoned from the design and not shown by a test. A writer that takes locks in another order can still deadlock with an import. PostgreSQL then ends one transaction after `deadlock_timeout` (1 s by default). The commit answers 409 `CONFLICT`, nothing is written, the batch stays `PREVIEWED`, and the same commit request can be sent again. The API does not retry by itself |
| L-30 | Two files that create the same new records, committed at the same moment | P2 | One commits. The other meets the unique key, answers 409 `COMMIT_CONFLICT` and its batch is `FAILED` with nothing written. Uploading that file again validates it against the records that now exist |
| L-31 | Whole numbers and offsets end at 2,147,483,647 | P3 | `sequence_no` and every `offset`. Larger values are refused (422, or `INVALID_INTEGER` on an import row), never truncated |
| L-32 | Text cannot contain the NUL character | P3 | PostgreSQL text cannot hold it. JSON requests are refused with 422 on the field; a CSV with NUL bytes is refused as a file (415) |
| L-33 | Digits of other scripts are read in numbers and refused in dates | P3 | `१२३.४५` is stored as `123.45`. A date such as `२०२६-११-१९` is `INVALID_DATE`, because a date written in another script may be of another calendar and the calendar is never guessed |
| L-34 | History is append-only in the service, not in the database | P2 | No service operation and no route changes or removes a plan or commitment version, and the tests check that. Nothing in PostgreSQL forbids it: a client with SQL access can `UPDATE` or `DELETE` a version row. Before the history is relied on as an audit record it needs a trigger or revoked privileges |
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
| V-04 | No load test, no long-running soak | Concurrency is tested with held row locks (the writer under test is seen waiting in `pg_stat_activity`) and with races of up to six simultaneous writers. The timings in L-10 were taken once by hand |
| V-05 | No file produced by a real source system was imported | The dataset is synthetic. It is imported as CSV and, in one test, as an Excel workbook with typed date and number cells, but every workbook in the tests is written by openpyxl, not by Excel or a supplier portal |
| V-06 | Coverage is not measured in CI | `make coverage` exists; the gates are scenario tests, not a percentage |
| V-07 | One deadlock is tested, and it depends on a default | The test builds a deadlock between an import and one other writer and relies on PostgreSQL's default `deadlock_timeout` of one second |
| V-08 | Tests were shown to fail for 27 chosen defects, not for all behaviour | `scripts/defect_detection.py` removes one behaviour at a time, 26 in all, and expects a failing test; one more defect was checked by hand (`docs/engineering/test-strategy.md`). Behaviour outside that list has ordinary tests only; no mutation tool was run |
