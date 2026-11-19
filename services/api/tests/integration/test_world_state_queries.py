"""The World State costs the same number of queries whatever the size of the page.

Nested collections are fetched for a whole page of parents at once. A query
per equipment record or per purchase order would make the number of
statements grow with the data; these tests count the statements PostgreSQL
receives and compare a small workspace with a larger one.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import Project, Workspace
from app.models.enums import IngestionEntityType
from app.services import world_state_service
from tests.importing import (
    COMMITMENT_HEADERS,
    EQUIPMENT_HEADERS,
    ITEM_HEADERS,
    MILESTONE_HEADERS,
    ORDER_HEADERS,
    Importer,
    import_small_dataset,
)

pytestmark = pytest.mark.db

E = IngestionEntityType

# Statements that open or shape the transaction rather than read data.
_NOT_A_READ = ("BEGIN", "ROLLBACK", "COMMIT", "SET ", "SHOW ")

# A generous ceiling: the project World State issues about thirty statements.
# The point of the ceiling is to notice a per-record query, not to pin a number.
STATEMENT_CEILING = 40

MORE_ORDERS = 20
EQUIPMENT_PER_ORDER = 2
MILESTONE_TYPES = ("PO_ACKNOWLEDGEMENT", "MANUFACTURING_START", "DELIVERY")


@contextmanager
def counted_statements(db: Database) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if not statement.lstrip().upper().startswith(_NOT_A_READ):
            statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


def statements_of(db: Database, call: Callable[[Session], Any]) -> int:
    with db.session() as own_session, counted_statements(db) as statements:
        call(own_session)
    return len(statements)


def grow(importer: Importer) -> None:
    """Twenty more purchase orders, each with two line items, three milestones, a commitment."""
    orders = [f"PO-X{index:02d}" for index in range(MORE_ORDERS)]
    equipment = [
        (order, f"EQ-X{index:02d}-{part}")
        for index, order in enumerate(orders)
        for part in range(EQUIPMENT_PER_ORDER)
    ]
    importer.run(
        E.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [[code, "DC-1", f"Equipment {code}", "UPS", "2027-02-01", "HIGH"] for _, code in equipment],
    )
    importer.run(
        E.PURCHASE_ORDER,
        ORDER_HEADERS,
        [[order, "DC-1", "SUP-1", "INR", "ISSUED"] for order in orders],
    )
    importer.run(
        E.PURCHASE_ORDER_ITEM,
        ITEM_HEADERS,
        [[order, code, "1", "100.00"] for order, code in equipment],
    )
    importer.run(
        E.MILESTONE,
        MILESTONE_HEADERS,
        [
            [order, milestone_type, "1", "2026-12-01", "", ""]
            for order in orders
            for milestone_type in MILESTONE_TYPES
        ],
    )
    importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [[order, "2027-01-10", "", ""] for order in orders],
    )
    # A second commitment for every order, so there is history to list.
    importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [[order, "2027-01-24", "", ""] for order in orders],
    )


@pytest.fixture
def importer(session: Session, workspace: Workspace) -> Importer:
    return Importer(session, workspace.id)


def project_id_of(session: Session) -> UUID:
    session.rollback()
    project = session.scalar(select(Project).where(Project.code == "DC-1"))
    assert project is not None
    return project.id


def test_project_world_state_issues_the_same_statements_for_two_or_twenty_two_orders(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    workspace_id, project_id = importer.workspace_id, project_id_of(session)

    def read(own: Session) -> Any:
        return world_state_service.get_project_world_state(
            own, workspace_id, project_id, equipment_limit=200, po_limit=200, include_history=True
        )

    small = statements_of(db, read)
    with db.session() as own_session:
        before = read(own_session)

    grow(importer)
    session.rollback()

    large = statements_of(db, read)
    with db.session() as own_session:
        after = read(own_session)

    # The data grew ...
    assert (before.purchase_orders.total, after.purchase_orders.total) == (2, 2 + MORE_ORDERS)
    assert after.equipment.total == 3 + MORE_ORDERS * EQUIPMENT_PER_ORDER
    assert len(after.purchase_orders.items) == 2 + MORE_ORDERS
    grown = next(order for order in after.purchase_orders.items if order.po_number == "PO-X07")
    assert (grown.line_item_count, grown.milestone_count, grown.commitment_version_count) == (
        EQUIPMENT_PER_ORDER,
        len(MILESTONE_TYPES),
        2,
    )
    assert grown.commitment_history is not None
    assert len(grown.commitment_history) == 2
    # ... and the number of statements did not.
    assert large == small
    assert large <= STATEMENT_CEILING


def test_workspace_world_state_issues_the_same_statements_whatever_it_holds(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    workspace_id = importer.workspace_id
    session.rollback()

    def summary(own: Session) -> Any:
        return world_state_service.get_workspace_world_state_summary(own, workspace_id)

    def workspace_state(own: Session) -> Any:
        return world_state_service.get_workspace_world_state(own, workspace_id, limit=200)

    small = (statements_of(db, summary), statements_of(db, workspace_state))
    grow(importer)
    session.rollback()
    large = (statements_of(db, summary), statements_of(db, workspace_state))

    assert large == small
    assert max(large) <= STATEMENT_CEILING
