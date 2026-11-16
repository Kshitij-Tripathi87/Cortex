"""Guard: every ORM timestamp column must be timezone-aware.

The application writes timezone-aware values everywhere (``datetime.now(UTC)``)
and every migration creates ``TIMESTAMP WITH TIME ZONE`` columns. A model column
typed as plain ``DateTime()`` -- which is also what SQLAlchemy infers for a bare
``Mapped[datetime] = mapped_column(...)`` -- is bound by asyncpg as
``TIMESTAMP WITHOUT TIME ZONE`` and the INSERT is rejected before it reaches the
server::

    invalid input for query argument $9: datetime.datetime(..., tzinfo=UTC)
    (can't subtract offset-naive and offset-aware datetimes)

SQLite accepts such values, so the default test database cannot show it. This
guard needs no database and therefore runs in every test job.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import DateTime

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

_TIMESTAMP_TYPES = {"DateTime", "TIMESTAMP"}
_COLUMN_FACTORIES = {"mapped_column", "Column"}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _timestamp_type_is_aware(node: ast.AST) -> bool | None:
    """``True``/``False`` for a DateTime/TIMESTAMP expression, ``None`` for anything else."""
    if _name(node) in _TIMESTAMP_TYPES:  # the bare class, e.g. ``Column(DateTime)``
        return False
    if isinstance(node, ast.Call) and _name(node.func) in _TIMESTAMP_TYPES:
        for keyword in node.keywords:
            if keyword.arg == "timezone":
                return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        if node.args:  # ``DateTime(True)``
            first = node.args[0]
            return isinstance(first, ast.Constant) and first.value is True
        return False
    return None


def _offenders_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(APP_ROOT.parent).as_posix()
    annotated_calls: dict[int, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.value, ast.Call)
            and _name(node.value.func) in _COLUMN_FACTORIES
        ):
            target = _name(node.target) or "?"
            annotated_calls[id(node.value)] = (target, ast.unparse(node.annotation))

    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node.func) in _COLUMN_FACTORIES):
            continue
        verdicts = [v for v in map(_timestamp_type_is_aware, node.args) if v is not None]
        target, annotation = annotated_calls.get(id(node), ("?", ""))
        if any(v is False for v in verdicts):
            found.append(f"{rel}:{node.lineno} {target}: timestamp type without timezone=True")
        elif not verdicts and "datetime" in annotation:
            found.append(
                f"{rel}:{node.lineno} {target}: {annotation} has no explicit column type "
                "(SQLAlchemy infers a timezone-naive DateTime)"
            )
    return found


def test_no_model_declares_a_timezone_naive_timestamp_column() -> None:
    """Static check over every source file, including modules nothing imports yet."""
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        offenders.extend(_offenders_in(path))

    assert offenders == [], (
        "Declare these columns as mapped_column(DateTime(timezone=True), ...):\n  "
        + "\n  ".join(offenders)
    )


def test_registered_models_bind_timestamps_with_time_zone() -> None:
    """Semantic check over the models the running API registers."""
    import app.main  # noqa: F401  (imports every mounted router and its models)
    from app.infrastructure.database import Base

    offenders = sorted(
        f"{table.fullname}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime) and not column.type.timezone
    )
    assert offenders == [], f"timezone-naive timestamp columns: {offenders}"
