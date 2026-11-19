"""Paging helper shared by the repositories."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def fetch_page[RowT](
    session: Session,
    statement: Select[RowT],
    *,
    order_by: Sequence[Any],
    limit: int,
    offset: int,
) -> tuple[list[RowT], int]:
    """Run ``statement`` as one bounded page and return it with the total count.

    The total is counted over the same filters, never over the page.
    """
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = session.scalars(statement.order_by(*order_by).limit(limit).offset(offset)).all()
    return list(rows), int(total or 0)
