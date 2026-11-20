# Procurement Intelligence Engine v0.2: contracts

The plan is `../procurement-intelligence-engine-plan.md`. It says what the
engine is for and in which order it is built, and it asks for one thing
before any code: its statements checked against the merged source, the open
decisions settled, and the contract frozen (plan §23). This folder is that
step, and holds documents only.

**Nothing in this folder is implemented.** There is no rule, table, migration
or route for intelligence in the repository.

| Document | Task | What it settles | Status |
|---|---|---|---|
| `entry-gate.md` | — | Whether engine code may start (plan §0.2) | Gate **not passed** |
| `canonical-input-mapping.md` | T-A-01 | Where every input of the rules lives, what the database guarantees, where a fact came from, and where the plan and the source differ | Done, awaiting sign-off |
| `policy-v1.md` | T-A-02 | A value for each of the 28 decisions; the policy document | Proposed, **not signed** |
| `finding-contract.md` | T-A-03 | The rules step by step, evidence, lifecycle, runs, storage, API | Proposed, **not frozen** |
| `task-cards.md` | — | The tasks, their files, tests and dependencies | Proposed |

Read in this order: the entry gate, then the mapping (section 4 lists every
point where the plan had to be made exact), then the policy, then the
contract.

## What the lead is asked for

1. **A decision on PR #28** (`entry-gate.md`). It cannot be merged as it is.
2. **A signature under `policy-v1.md`.** Fifteen decisions come from the plan
   and thirteen from reconciling it with the source. Each has a proposed
   value and a reason. Those that change what the product reports are D-01
   (five days for an acknowledgement), D-06 (no severity yet), D-16 and D-17
   (when a delivery counts as complete), D-18 (cancelled and draft records),
   D-26 and D-27 (what the list of findings will contain).
3. **A look at `canonical-input-mapping.md` §5**: what the engine would say
   about the demo dataset. It reports six findings, three of them milestone
   slippages where the dataset names one, and no commitment threat at all.

## Record of this step

2026-11-20, on a branch from `main` at `3fe1d1c`.

| Done | Result |
|---|---|
| Read the plan, `AGENTS.md`, the architecture and engineering documents, the models, migration `0001`, the services and repositories behind the World State and the ingestion ledger | The mapping |
| Migrated a PostgreSQL 16.2 database to revision `0001` and read `information_schema.columns` | Every column, type and nullability in the mapping agrees with the ORM models |
| Compared the inputs between `main` and the head of PR #28 | No difference in models, migrations, schemas, repositories, the World State service or the demo data |
| Derived by hand what the five rules report for the demo dataset as of 2026-11-19, then confirmed it with one SQL query per rule on a seeded database | Mapping §5: six findings both ways |
| Ran the checks of `AGENTS.md` on `main` | Lint, format, mypy and the OpenAPI snapshot pass; 414 unit, 238 API, 134 integration tests |
| Repeated the verification of PR #28 at its head and read crafted workbooks with both readers | `entry-gate.md` |

Not done, on purpose: no code, no test, no migration, and no change to a
v0.1 contract document apart from a paragraph in `AGENTS.md` that points to
this folder and its gate. The changes those documents need are listed in
`finding-contract.md` §13 and are made with the implementation.

## Deviations from the plan in this step

| Plan | Here | Why |
|---|---|---|
| §23: start A-01 when the entry gate is satisfied | The three document tasks were done while the gate is open | The sixth condition of the gate is this very check, and none of it depends on PR #28 |
| §23: the first pull request holds the signed decisions and the frozen contract | It holds them as proposals until the lead signs | Only the lead can sign |
| §17: task ids `D-01` to `D-04` | Written `T-D-01` to `T-D-04`, and every task with a leading `T-` | The plan uses `D-01` to `D-15` for decisions as well |
| §11: six routes | Nine | Diagnostics of a run, occurrences of a run, one occurrence with its evidence (`finding-contract.md` §11) |
| §8.1: four tables and an optional policy table | Five tables, no policy table | Outcomes that cannot be evaluated need a place (D-20); the policy is a document (D-09) |
