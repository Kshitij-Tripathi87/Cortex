# Known limitations

Cortex Nexus v0.1 is a local engineering prototype of the data foundation.
It is not production-ready, and nothing below is hidden by a default or a
dashboard. Severity uses the scale of the playbook (P0 blocker to P3 polish);
No P0 is open. One P1 limitation remains open: XLSX parsing still lacks OS-enforced per-import resource isolation (L-35).

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
| L-10 | XLSX previews at the full row/column limits are expensive | P2 | The previous implementation measured 41–59 seconds for a workbook at both limits because it opened the workbook twice (values and formulas). The hardening branch now loads openpyxl once and obtains formula coordinates from the bounded XML scan. The new timing and memory figures are not yet measured; do not claim a speedup until the same benchmark is rerun in CI or on a controlled build machine |
| L-11 | A commit locks every record its rows refer to | P2 | Two imports that touch the same records run one after the other. An import takes its locks in one fixed order (record type, then the columns of the natural key), which is meant to keep two imports from deadlocking each other; that is reasoned from the design and not shown by a test. A writer that takes locks in another order can still deadlock with an import. PostgreSQL then ends one transaction after `deadlock_timeout` (1 s by default). The commit answers 409 `CONFLICT`, nothing is written, the batch stays `PREVIEWED`, and the same commit request can be sent again. The API does not retry by itself |
| L-30 | Two files that create the same new records, committed at the same moment | P2 | One commits. The other meets the unique key, answers 409 `COMMIT_CONFLICT` and its batch is `FAILED` with nothing written. Uploading that file again validates it against the records that now exist |
| L-31 | Whole numbers and offsets end at 2,147,483,647 | P3 | `sequence_no` and every `offset`. Larger values are refused (422, or `INVALID_INTEGER` on an import row), never truncated |
| L-32 | Text cannot contain the NUL character | P3 | PostgreSQL text cannot hold it. JSON requests are refused with 422 on the field; a CSV with NUL bytes is refused as a file (415) |
| L-33 | Digits of other scripts are read in numbers and refused in dates | P3 | `१२३.४५` is stored as `123.45`. A date such as `२०२६-११-१९` is `INVALID_DATE`, because a date written in another script may be of another calendar and the calendar is never guessed |
| L-34 | History is append-only in the service, not in the database | P2 | No service operation and no route changes or removes a plan or commitment version, and the tests check that. Nothing in PostgreSQL forbids it: a client with SQL access can `UPDATE` or `DELETE` a version row. Before the history is relied on as an audit record it needs a trigger or revoked privileges |
| L-35 | XLSX parsing is bounded in-process, but not isolated by an OS resource boundary | P1 | The reader preflights workbook-level XML, caps shared strings at 250,000 entries and 8,000,000 decoded text characters, caps the selected worksheet's physical row number at the scan envelope, bounds package size/archive entries, and scans only the selected worksheet. CI run #275 verifies these limits with synthetic regression tests and the 43-case mutation suite. It did not replay the exact previously measured 2.2-million-shared-string or million-empty-row crafted files, and it did not measure post-change peak RSS or wall time. The historical measurements in the implementation log are pre-hardening. Parsing still runs inside the API process without a cgroup/RLIMIT memory or wall-clock deadline. Keep the route on loopback/operator-only use; do not accept untrusted uploads until parsing runs in an isolated worker with enforced memory and time limits |
| L-36 | Unselected worksheet contents are not inspected during an import | P3 | Implemented and verified by CI run #275. Package preflight scans workbook-level XML only; the selected worksheet is scanned and read, while other visible or hidden worksheet XML is not walked. A workbook still requires a unique, valid worksheet directory entry; callers must explicitly select when multiple visible worksheets exist. Independent human review remains pending |
| L-38 | A workbook with more than one visible worksheet requires explicit selection | P3 | Without `sheet_name`, the API accepts exactly one visible worksheet; multiple visible worksheets return `AMBIGUOUS_WORKSHEET`. This avoids probing unselected tabs just to guess the user's intent |
| L-39 | Import admission control is process-local | P2 | `MAX_CONCURRENT_IMPORTS` defaults to 1 and returns HTTP 429 with `Retry-After: 2` when the worker is occupied. It is not a distributed limit across multiple Uvicorn workers or replicas. Use one worker or a shared queue/admission service until a job runner is introduced |

| L-37 | An error value or a time in a text column is imported as text | P3 | A cell that shows `#N/A` is stored as the text `#N/A`; a time of day becomes `12:30:00`, a duration `1 day, 6:00:00`. In a date or number column the same cells are rejected |
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
| V-01 | Docker Compose was never run on the machine the code was written on | That machine has no Docker. The Compose file, the named volume and the container restart are exercised by the CI workflow only, on a GitHub runner; `docs/engineering/implementation-log.md` records the first run, which passed. Nobody has run `make db-up` on a developer machine |
| V-02 | Local evidence was produced on PostgreSQL 16.2 started from binaries, on `127.0.0.2` | The Compose file pins 16.16 on `127.0.0.1`; CI uses that, and the tests and the end-to-end demonstration pass there too. See `artifacts/sprint/README.md` |
| V-03 | One contributor, working the three lanes in sequence | No independent review took place. The tests were written by the author of the code, and so was the review after the gate that found the defects in the workbook reader |
| V-04 | No load test, no long-running soak | Concurrency is tested with held row locks (the writer under test is seen waiting in `pg_stat_activity`) and with races of up to six simultaneous writers. The timings in L-10 were taken once by hand |
| V-05 | No file produced by a real source system was imported | The dataset is synthetic. It is imported as CSV and, in one test, as an Excel workbook with typed date and number cells. Every workbook in the tests is written by openpyxl or by hand, not by Excel or a supplier portal. Once, outside the tests, 36 workbooks written by Microsoft Excel and LibreOffice (the test data of the pandas project) were read with `scripts/compare_workbooks.py`: the 27 worksheets the reader accepts were identical, cell by cell, to an independent reading, and none was refused for a reason other than its layout. Those files are not in this repository, and none of them is procurement data |
| V-06 | Coverage is not measured in CI | `make coverage` exists; the gates are scenario tests, not a percentage. It was read once, after gate G3 had passed (97 % of statements and branches then): the branches it named were probed, and that is how the defects in the workbook reader were found. A passing gate did not mean that every branch had been exercised |
| V-07 | One deadlock is tested, and it depends on a default | The test builds a deadlock between an import and one other writer and relies on PostgreSQL's default `deadlock_timeout` of one second |
| V-08 | Defect-detection script covers a selected set, not every behavior | `scripts/defect_detection.py` contains 43 hand-selected mutations. CI run #275 detected 43 of 43; the unchanged baseline passed 380 selected tests, and the source restoration check passed. This is targeted mutation evidence, not exhaustive mutation testing |
