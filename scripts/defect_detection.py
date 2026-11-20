"""Show that the tests notice when the behaviour they guard is removed.

Usage (from services/api, with the test database running):
    uv run python ../../scripts/defect_detection.py
    uv run python ../../scripts/defect_detection.py --only 6 --only 18

A test that cannot fail proves nothing. Each entry of DEFECTS removes one
behaviour by replacing a few lines of the service, runs the tests that are
meant to guard it, and puts the file back. The defect counts as DETECTED when
those tests ran and at least one failed. A defect that leaves every test
green is reported as NOT DETECTED, and the exit code is 1.

This is not an automated mutation run: the defects are chosen by hand, one
per behaviour that matters (row locks, workspace filters, bounds, the
handling of a deadlock). When the code around a defect changes, the text it
replaces no longer matches and the entry must be updated; the run says so
instead of passing.

The script edits source files while it runs. Each file is restored in a
`finally` block, also when the run is interrupted; if the process is killed
outright, `git checkout -- services/api/app` restores everything. For that
reason it is not part of `make verify`. CI runs it in a job of its own, on a
checkout that is thrown away afterwards.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from app.core.config import REPO_ROOT

API_DIR = REPO_ROOT / "services" / "api"
CONCURRENCY = "tests/integration/test_concurrency.py"
UNSTORABLE = "tests/api/test_unstorable_values.py"
ISOLATION = "tests/api/test_workspace_isolation_http.py"
NORMALIZATION = "tests/unit/test_normalization.py"
LIFECYCLE = "tests/integration/test_import_preview_commit.py"
WORKBOOKS = "tests/unit/test_workbook_safety.py"
READERS = "tests/unit/test_readers.py"
IMPORT_ADMISSION = "tests/unit/test_import_concurrency.py"

_SUMMARY = re.compile(r"(\d+) failed")


@dataclass(frozen=True)
class Defect:
    """One behaviour removed: `old` is replaced by `new` in `file`."""

    label: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


DEFECTS: tuple[Defect, ...] = (
    Defect(
        "readiness borrows a pooled connection",
        "app/db/session.py",
        "        with self._probe_engine.connect() as connection:\n",
        "        with self.engine.connect() as connection:\n",
        ("tests/api/test_health.py",),
    ),
    Defect(
        "import commit reads purchase orders without a row lock",
        "app/services/ingestion_service.py",
        "            session, workspace_id, po_numbers, for_update=for_update\n",
        "            session, workspace_id, po_numbers, for_update=False\n",
        (CONCURRENCY,),
    ),
    Defect(
        "appending a commitment through the API does not lock the purchase order",
        "app/services/purchase_order_service.py",
        "        purchase_order = purchase_order_repository.lock_by_id(\n"
        "            session, workspace_id, purchase_order_id\n",
        "        purchase_order = purchase_order_repository.get_by_id(\n"
        "            session, workspace_id, purchase_order_id\n",
        (CONCURRENCY,),
    ),
    Defect(
        "import commit reads milestones without a row lock",
        "app/services/ingestion_service.py",
        "            session, workspace_id, set(identities), for_update=for_update\n",
        "            session, workspace_id, set(identities), for_update=False\n",
        (CONCURRENCY,),
    ),
    Defect(
        "appending a plan version through the API does not lock the milestone",
        "app/services/milestone_service.py",
        "            for_update=True,\n"
        "        )\n"
        "        if milestone is None:\n"
        "            raise _not_found()\n"
        "        _, created = record_plan(\n",
        "            for_update=False,\n"
        "        )\n"
        "        if milestone is None:\n"
        "            raise _not_found()\n"
        "        _, created = record_plan(\n",
        (CONCURRENCY,),
    ),
    Defect(
        "commit does not lock the batch row",
        "app/repositories/ingestion_repository.py",
        "IngestionBatch.id == batch_id)\n        .with_for_update()\n",
        "IngestionBatch.id == batch_id)\n",
        (CONCURRENCY, LIFECYCLE),
    ),
    Defect(
        "preview does not look again after losing the race for a new file",
        "app/services/ingestion_service.py",
        "        if not _is_checksum_collision(exc):\n            raise\n",
        "        raise\n",
        (CONCURRENCY,),
    ),
    Defect(
        "World State reads the current commitment with one query per purchase order",
        "app/services/world_state_service.py",
        "    current_commitments = purchase_order_repository.latest_commitments(\n"
        "        session, workspace_id, order_ids\n"
        "    )\n",
        "    current_commitments = {\n"
        "        order_id: version\n"
        "        for order_id in order_ids\n"
        "        if (\n"
        "            version := purchase_order_repository.latest_commitment(\n"
        "                session, workspace_id, order_id\n"
        "            )\n"
        "        )\n"
        "    }\n",
        ("tests/integration/test_world_state_queries.py",),
    ),
    Defect(
        "text with a NUL character passes the request schema",
        "app/schemas/common.py",
        "    if limits.UNSTORABLE_CHARACTER in value:\n",
        "    if False:\n",
        (UNSTORABLE,),
    ),
    Defect(
        "imports do not bound whole numbers",
        "app/ingestion/normalization.py",
        "    if abs(number) > maximum:\n",
        "    if False:\n",
        (UNSTORABLE, NORMALIZATION),
    ),
    Defect(
        "sequence_no has no upper bound in the API",
        "app/schemas/milestone.py",
        "gt=0, le=limits.SEQUENCE_NO_MAX",
        "gt=0",
        (UNSTORABLE,),
    ),
    Defect(
        "offset of the lists has no upper bound",
        "app/api/deps.py",
        "Query(ge=0, le=OFFSET_MAX, description",
        "Query(ge=0, description",
        (UNSTORABLE,),
    ),
    Defect(
        "offsets of the project World State have no upper bound",
        "app/api/v1/endpoints/world_state.py",
        "Query(ge=0, le=OFFSET_MAX)",
        "Query(ge=0)",
        (UNSTORABLE,),
    ),
    Defect(
        "the stored file name keeps control characters",
        "app/services/ingestion_service.py",
        "if character.isprintable()",
        "if True",
        (UNSTORABLE,),
    ),
    Defect(
        "no handler for a value the database refuses",
        "app/core/errors.py",
        "    app.add_exception_handler(DataError, _handle_data_error)\n",
        "",
        (UNSTORABLE,),
    ),
    Defect(
        "decimal places are counted after rounding to the arithmetic precision",
        "app/core/decimals.py",
        "    _, digits, exponent = value.as_tuple()\n"
        "    if not isinstance(exponent, int) or exponent >= 0 or not value:\n"
        "        return 0\n"
        "    places = -exponent\n"
        "    for digit in reversed(digits):\n"
        "        if digit != 0 or places == 0:\n"
        "            break\n"
        "        places -= 1\n"
        "    return places\n",
        "    exponent = value.normalize().as_tuple().exponent\n"
        "    return -exponent if isinstance(exponent, int) and exponent < 0 else 0\n",
        (NORMALIZATION,),
    ),
    Defect(
        "commit has no branch for a value the database refuses",
        "app/services/ingestion_service.py",
        "    except DataError as exc:\n",
        "    except ZeroDivisionError as exc:\n",
        (LIFECYCLE,),
    ),
    Defect(
        "a deadlock during commit is treated like an outage",
        "app/services/ingestion_service.py",
        "        if not ended_to_resolve_a_conflict(exc):\n",
        "        if True:\n",
        (CONCURRENCY,),
    ),
    Defect(
        "a deadlock on a JSON route is answered 503",
        "app/core/errors.py",
        "    if ended_to_resolve_a_conflict(exc):\n",
        "    if False:\n",
        ("tests/api/test_error_envelope.py",),
    ),
    Defect(
        "sequence_no accepts text, fractions and booleans",
        "app/schemas/milestone.py",
        ", strict=True)",
        ")",
        (UNSTORABLE,),
    ),
    Defect(
        "project lookup by id ignores the workspace",
        "app/repositories/project_repository.py",
        "where(Project.workspace_id == workspace_id, Project.id == project_id)",
        "where(Project.id == project_id)",
        (ISOLATION,),
    ),
    Defect(
        "purchase-order lock by id ignores the workspace",
        "app/repositories/purchase_order_repository.py",
        ".where(PurchaseOrder.workspace_id == workspace_id, "
        "PurchaseOrder.id == purchase_order_id)\n        .with_for_update()",
        ".where(PurchaseOrder.id == purchase_order_id)\n        .with_for_update()",
        (ISOLATION,),
    ),
    Defect(
        "milestone lookup by id ignores the workspace",
        "app/repositories/milestone_repository.py",
        "Milestone.workspace_id == workspace_id, Milestone.id == milestone_id",
        "Milestone.id == milestone_id",
        (ISOLATION,),
    ),
    Defect(
        "batch lock for commit ignores the workspace",
        "app/repositories/ingestion_repository.py",
        ".where(IngestionBatch.workspace_id == workspace_id, IngestionBatch.id == batch_id)\n"
        "        .with_for_update()",
        ".where(IngestionBatch.id == batch_id)\n        .with_for_update()",
        (ISOLATION,),
    ),
    Defect(
        "equipment list ignores the workspace",
        "app/repositories/equipment_repository.py",
        "statement = select(Equipment).where(Equipment.workspace_id == workspace_id)",
        "statement = select(Equipment).where(Equipment.id.is_not(None))",
        (ISOLATION,),
    ),
    Defect(
        "World State counts ignore the workspace",
        "app/repositories/world_state_repository.py",
        "select(func.count()).select_from(model).where(model.workspace_id == workspace_id)",
        "select(func.count()).select_from(model)",
        (ISOLATION,),
    ),
    Defect(
        "a worksheet is read only as far as the range it claims",
        "app/ingestion/readers.py",
        "    values_sheet.reset_dimensions()\n    formulas_sheet.reset_dimensions()\n",
        "",
        (WORKBOOKS,),
    ),
    Defect(
        "workbook-level XML is not checked before openpyxl materializes it",
        "app/ingestion/readers.py",
        "            scan_parts(\n"
        "                archive,\n"
        "                global_xml_parts,\n"
        "                cell_elements=content_budget(limits, _scanned_rows(limits)),\n"
        "                max_rows=_scanned_rows(limits),\n"
        "                max_shared_string_items=limits.max_shared_string_items,\n"
        "                max_shared_string_chars=limits.max_shared_string_chars,\n"
        "            )\n",
        "            pass\n",
        (WORKBOOKS,),
    ),
    Defect(
        "the reader loads without the hardened XML parser",
        "app/ingestion/readers.py",
        "if not DEFUSEDXML:\n",
        "if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "an over-wide worksheet row is silently truncated",
        "app/ingestion/readers.py",
        '    bounds = {"max_col": limits.max_columns + 1}\n',
        '    bounds = {"max_col": limits.max_columns}\n',
        (READERS,),
    ),
    Defect(
        "two rows of a worksheet may carry the same number",
        "app/ingestion/workbook_scan.py",
        "        if number <= self._row_number or number > SHEET_MAX_ROW:\n",
        "        if number > SHEET_MAX_ROW:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "two cells of a row may carry the same reference",
        "app/ingestion/workbook_scan.py",
        " or column <= self._column or column > SHEET_MAX_COLUMN:\n",
        " or column > SHEET_MAX_COLUMN:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "formats and structure of a workbook are not counted",
        "app/ingestion/workbook_scan.py",
        "            if self._structure > MAX_STRUCTURE_ELEMENTS:\n",
        "            if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "a single tag or text of any length is handed to the parser",
        "app/ingestion/workbook_scan.py",
        "                parser.ParseFile(_BoundedRuns(part))\n",
        "                parser.ParseFile(part)\n",
        (WORKBOOKS,),
    ),
    Defect(
        "an error message quotes every worksheet name in full",
        "app/ingestion/readers.py",
        "        if len(printable) > SHEET_NAME_SHOWN_CHARS:\n",
        "        if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "a worksheet name of any length is passed on to the ledger",
        "app/ingestion/readers.py",
        "    if len(selected) > SHEET_NAME_MAX:\n",
        "    if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "two worksheets of a workbook may share a name",
        "app/ingestion/readers.py",
        "    if len(set(available)) != len(available):\n",
        "    if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "shared-string count is not bounded before openpyxl loads it",
        "app/ingestion/workbook_scan.py",
        "            if self._shared_string_items > self._max_shared_string_items:\n",
        "            if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "aggregate shared-string text is not bounded before materialization",
        "app/ingestion/workbook_scan.py",
        "            if self._shared_string_chars > self._max_shared_string_chars:\n",
        "            if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "a selected worksheet can exceed the physical row scan limit",
        "app/ingestion/workbook_scan.py",
        "        if number > self._max_rows:\n",
        "        if False:\n",
        (WORKBOOKS,),
    ),
    Defect(
        "unselected worksheet XML is scanned with the selected worksheet",
        "app/ingestion/readers.py",
        "            global_xml_parts = [\n"
        "                name for name in (\n"
        "                    CONTENT_TYPES_PART,\n"
        '                    "_rels/.rels",\n'
        "                    WORKBOOK_PART,\n"
        '                    "xl/_rels/workbook.xml.rels",\n'
        '                    "xl/styles.xml",\n'
        '                    "xl/sharedStrings.xml",\n'
        '                    "xl/theme/theme1.xml",\n'
        "                )\n"
        "                if name in names\n"
        "            ]",
        "            global_xml_parts = [name for name in names if name.lower().endswith("
        '                (".xml", ".rels"))]',
        (WORKBOOKS,),
    ),
    Defect(
        "formula locations from the bounded scan are ignored",
        "app/ingestion/readers.py",
        "                formula_bitmap.contains(row_number, column) if formula_bitmap is not None "
        "                else False",
        "                False",
        (WORKBOOKS,),
    ),
    Defect(
        "the import admission limit is removed",
        "app/api/import_concurrency.py",
        "        if not self._slots.acquire(blocking=False):",
        "        if False:",
        (IMPORT_ADMISSION,),
    ),
)


def run_tests(tests: tuple[str, ...]) -> tuple[int, str, str]:
    """Exit code and last output line of pytest for the given files."""
    # A bytecode cache of its own: bytecode compiled from a broken file must
    # never be found again once the file is restored.
    with tempfile.TemporaryDirectory(prefix="nexus-defect-") as cache:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
            cwd=API_DIR,
            env={**os.environ, "PYTHONPYCACHEPREFIX": cache},
            capture_output=True,
            text=True,
            check=False,
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    detail = "\\n".join(completed.stdout.splitlines()[-80:])
    if completed.stderr:
        detail += "\\nSTDERR:\\n" + "\\n".join(completed.stderr.splitlines()[-40:])
    return completed.returncode, lines[-1] if lines else "(no output)", detail


def check(number: int, defect: Defect) -> bool:
    """Apply the defect, run its tests, restore the file. True when it was detected."""
    path = API_DIR / defect.file
    original = path.read_text(encoding="utf-8")
    if original.count(defect.old) != 1:
        print(
            f"{number:02d}  STALE         {defect.label}: the text to replace occurs "
            f"{original.count(defect.old)} times in {defect.file}; update the entry"
        )
        return False
    try:
        path.write_text(original.replace(defect.old, defect.new), encoding="utf-8")
        exit_code, summary, _ = run_tests(defect.tests)
    finally:
        path.write_text(original, encoding="utf-8")
    # pytest exits with 1 when tests ran and some failed. Any other code means
    # the tests passed (0) or could not run (collection error, usage error).
    failed = _SUMMARY.search(summary)
    detected = exit_code == 1 and failed is not None
    verdict = "DETECTED    " if detected else ("NOT DETECTED" if exit_code == 0 else "ERROR       ")
    print(f"{number:02d}  {verdict}  {defect.label}  [{summary.strip('= ')}]", flush=True)
    return detected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only", type=int, action="append", help="number of a defect to run; may be repeated"
    )
    arguments = parser.parse_args()

    baseline_code, baseline, baseline_detail = run_tests(
        tuple(sorted({t for d in DEFECTS for t in d.tests}))
    )
    print(f"00  unchanged code: {baseline.strip('= ')}")
    if baseline_code != 0:
        print("The tests do not pass on the unchanged code; nothing can be concluded.")
        print(baseline_detail)
        return 1

    chosen = [
        (number, defect)
        for number, defect in enumerate(DEFECTS, start=1)
        if not arguments.only or number in arguments.only
    ]
    detected = sum(check(number, defect) for number, defect in chosen)
    print(f"\n{detected} of {len(chosen)} deliberate defects were detected by the tests.")
    return 0 if detected == len(chosen) else 1


if __name__ == "__main__":
    sys.exit(main())
