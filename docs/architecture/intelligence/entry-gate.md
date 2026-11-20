# Entry gate of the Procurement Intelligence Engine

The plan (`../procurement-intelligence-engine-plan.md`, §0.2) blocks every
line of engine code until six conditions hold. This is the record of where
each stands. It is rewritten when one of them changes.

**State on 2026-11-20: NOT PASSED.** Work on this phase is limited to the
documents of this folder (tasks T-A-01 to T-A-03).

## The six conditions

| # | Condition (plan §0.2) | State | Evidence |
|---|---|---|---|
| 1 | PR #28 has an independent human review by someone other than its author | **Not met** | PR #28 is open at `5e2def7` with no review. The automatic review that was requested did not run (the reviewing service answered that its usage limit was reached). An agent review exists (below); it is not a human review |
| 2 | Every review finding is resolved, or accepted by the lead with a reason | **Not met** | The agent review has four blocking findings and four more to settle. None is resolved |
| 3 | PR #28 is merged and `main` is green after the merge | **Not met** | Not merged. `main` itself is green at `3fe1d1c` (CI run #279, both jobs) |
| 4 | The release-gate items of PR #28 are signed off or carried as accepted limitations | **Not met** | Its body lists four open items. One of them, the re-measurement, is done (below) |
| 5 | The lead confirms the baseline commit for the implementation branch | **Not met** | To be given once 3 holds |
| 6 | The plan is checked against the merged models and schemas | **Done, awaiting sign-off** | `canonical-input-mapping.md`. PR #28 changes none of the inputs, so the check holds before and after its merge |

The plan also says: do not merge PR #28 as part of this work, and do not
branch engine work from its unmerged head. Neither was done. This branch
starts from `main`.

## The baseline

| | |
|---|---|
| `main` | `3fe1d1c53daaeb487a492b7037c43dc1bc305c86`: the v0.1 merge `2bb2809` plus the plan. No code differs between the two |
| Checks on `main`, repeated here | Ruff lint and format, mypy strict and the OpenAPI snapshot pass; 414 unit, 238 API and 134 integration tests pass (Python 3.12.16, PostgreSQL 16.2) |
| CI on `main` | Run #279: both jobs passed |

## PR #28 as it stands

"Harden XLSX imports and bound concurrent ingestion", branch
`fix/xlsx-resource-guards`, head `5e2def7c7bfc04405e2b59698eed39eee03cdf6f`,
63 commits, 20 files, based on `2bb2809`.

**What it states is true.** Repeated at its head on a second machine: lint,
format, mypy and the OpenAPI snapshot pass; 428 unit, 238 API and 134
integration tests pass; `scripts/defect_detection.py` detects 43 of 43 with a
baseline of 380 tests.

**What a green run does not show.** The agent review read crafted workbooks
with the reader of `main` and with the reader of the PR, one process per
reading, with the limits of the default configuration. "read" means that the
import of the `Projects` worksheet succeeded.

| Upload | The workbook holds | `main` | PR #28 |
|---|---|---|---|
| 2.7 MB | A hidden worksheet whose root element has 1.2 million attributes | refused, 0.01 s, 85 MB | read, 3.3 s, 416 MB |
| 22 kB | A hidden worksheet nested 3 million elements deep | refused, 0.00 s, 80 MB | read, 7.9 s, 978 MB |
| 332 kB | 8 million shared strings in a part named `xl/strings.xml` | refused, 4.2 s, 80 MB | read, 80.1 s, 815 MB |
| 2.6 MB | The workbook part under another name, with 1 million defined names | refused, 0.35 s, 82 MB | read, 15.7 s, 782 MB |
| 17 kB | `docProps/core.xml` with 4 million elements | refused, 0.15 s, 80 MB | read, 7.5 s, 463 MB |
| 1.5 kB | Rows numbered 1, 2, 2, 3 under a root element that is not `<worksheet>` | refused | read, one row missing, no warning |
| 93 kB | 2.2 million shared strings in `xl/sharedStrings.xml` | read, 55.9 s, 335 MB | refused, 0.5 s, 80 MB |

The last row is the improvement the PR was written for, and it holds. The
others are protections of `main` that the PR loses:

1. It opens the workbook before it weighs the worksheets, and it never weighs
   a worksheet that is not imported. The library parses every worksheet when
   it opens a workbook.
2. It looks for the parts to weigh under fixed file names. The library finds
   them through `[Content_Types].xml`, under any name, and it also reads the
   document properties.
3. It checks the numbering of rows only under a root element named
   `worksheet`. The library reads rows under any root.
4. The tests and the deliberate defects that would have failed were changed
   to fit: one of the new deliberate defects treats the weighing of
   unselected worksheets as the defect.

Further findings to settle: the limit of 250,000 shared strings refuses an
ordinary worksheet of 10,000 rows and 30 text columns, which is inside the
documented limits; a workbook with one worksheet of data and empty ones
beside it now needs `sheet_name`; one client that opens an upload and stays
silent blocks every other import; and three points of documentation.

**The open item "re-measure" of the PR is closed by the same readings.** With
one load instead of two, a workbook of 10,000 rows and 20 columns is read in
4.2 s at 115 MB (`main`: 6.7 s, 124 MB), and one of 10,000 rows and 100
columns with ten text columns in 13.8 s at 170 MB (`main`: 20.8 s, 179 MB).
The reader alone, one reading each.

The review, with the files, the figures and the scripts to repeat them, is
REVIEW_LOCATION.

**PR #27** ("Harden XLSX ingestion resource limits and reader isolation",
`fix/xlsx-resource-admission`) is an earlier attempt at the same work. It is
still open and its checks fail. It is not part of the gate; the lead may want
to close it.

## What passes the gate

1. PR #28 is corrected, or replaced, so that the library cannot reach a part
   that was not weighed; the findings are resolved or accepted in writing.
2. A person who did not write it reviews it.
3. It is merged, and CI on `main` is green.
4. The lead names the commit of `main` to build on.
5. The lead signs `policy-v1.md` and freezes `finding-contract.md`.

Nothing in this folder depends on the code of PR #28. If its correction
touches a model, a migration or the ingestion ledger, `canonical-input-mapping.md`
is checked again before the first task after the gate.
