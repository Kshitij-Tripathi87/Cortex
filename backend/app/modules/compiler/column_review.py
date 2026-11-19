"""Review a source file one column at a time.

Every cell of an uploaded file (one row, one column) is a claim that waits for
a decision, and only accepted cells are published. A file of 300 suppliers
with seven columns is 2,100 cells. Reviewing them one by one took 2,100
decisions, each with the kind of record typed by hand, so a file could only be
published by a script.

What a reviewer decides is what a column means. This module

* describes each column of a file: the field it is published under, whether it
  identifies the record or links it to another one, a few of its values and
  how many of them wait, and
* applies one recorded decision to every waiting value of the columns named.

The names come from the registries that publishing reads
(``infer_entity_type`` and ``canonical_column_name``), so what is shown here
is what gets published. A value that belongs to an open conflict is left to
the conflict: it is decided there, with the competing values in view.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.compiler.service import detect_conflicts
from app.modules.graph.entity_keys import (
    ENTITY_FOREIGN_KEYS,
    ENTITY_PRIMARY_KEYS,
    canonical_column_name,
    infer_entity_type,
)
from app.modules.sources.models import SourceColumnProfile, SourceFile

# How many of a column's values are shown beside it, and in how many rows
# from the top of the file they are looked for.
EXAMPLES_PER_COLUMN = 3
EXAMPLE_ROWS = 25

# A statement takes a limited number of parameters; identifiers are passed in
# portions of this size.
_ID_PORTION = 2000

_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,127}")

_PENDING = ClaimState.PENDING_REVIEW.value
_ACCEPTED = ClaimState.ACCEPTED.value
_REJECTED = ClaimState.REJECTED.value
_SUPERSEDED = ClaimState.SUPERSEDED.value


class ColumnReviewError(ValueError):
    """A column decision that cannot be applied; nothing was changed.

    ``status_code`` is 422 when the request itself has to change and 409 when
    the state of the file does not allow the decision.
    """

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ColumnReview:
    """One column of a file, as it stands."""

    source_column: str
    # The field its values are published under.
    canonical_field: str
    # "key": identifies the record of each row. "link": names another record.
    # "value": a plain field of the record.
    role: str
    links_to: str | None
    examples: list[str]
    pending: int
    accepted: int
    rejected: int
    superseded: int
    # Waiting values that belong to an open conflict and are decided there.
    in_conflict: int


@dataclass(frozen=True)
class FileReview:
    """A file of a batch: what its rows are and how each column is published."""

    file_id: str
    name: str
    rows: int | None
    # The kind of record each row describes; None when it is not known yet.
    entity: str | None
    # "columns": recognised from the column names, as publishing does.
    # "review": set by an accepted decision on the identifying column.
    # "proposed": asked for by the caller, nothing accepted yet.
    entity_source: str | None
    key_field: str | None
    key_column: str | None
    # Why the file cannot be reviewed by column, when it cannot.
    problem: str | None
    columns: list[ColumnReview]


@dataclass(frozen=True)
class ColumnDecisionResult:
    decision: str
    canonical_entity: str | None
    # Column -> field it was accepted under; for a rejection, the columns only.
    columns: dict[str, str | None]
    claims_decided: int
    claims_left_in_conflict: int
    conflicts_detected: int


@dataclass
class _FileFacts:
    """What is known about a file: its columns and how their values stand.

    Built in two ways that must agree. Showing the columns counts in the
    database, because a file can hold a quarter of a million values and the
    view is drawn every time the page is opened. Deciding columns reads the
    values it is about to change and counts those.
    """

    file: SourceFile
    columns: list[str]
    # Values the profiler kept for a column, used when no claim gives one.
    samples: dict[str, list[str]]
    # Values of each column from the top of the file, in file order.
    examples: dict[str, list[str]]
    # Column -> state -> how many values.
    tallies: dict[str, dict[str, int]]
    # Column -> waiting values that belong to an open conflict.
    in_conflict: dict[str, int]
    recognised: str | None
    reviewed: list[str]
    accepted_fields: dict[str, set[str]]

    @property
    def column_index(self) -> dict[str, int]:
        return {column: index for index, column in enumerate(self.columns)}


@dataclass
class _FileState(_FileFacts):
    """The facts of a file together with the claims a decision will change."""

    claims: list[EvidenceClaim] = field(default_factory=list)
    conflicted_ids: set[str] = field(default_factory=set)


async def _profiled_columns(
    db: AsyncSession, workspace_id: str, file: SourceFile
) -> tuple[list[str], dict[str, list[str]]]:
    """The columns of a file in file order, with the values the profiler kept."""
    profile_result = await db.execute(
        select(SourceColumnProfile)
        .where(SourceColumnProfile.file_id == file.file_id)
        .where(SourceColumnProfile.workspace_id == workspace_id)
        .order_by(SourceColumnProfile.column_index)
    )
    profiles = list(profile_result.scalars().all())
    columns = [str(profile.column_name) for profile in profiles]
    samples = {
        str(profile.column_name): [str(value) for value in (profile.sample_values or [])]
        for profile in profiles
    }
    return columns, samples


async def _conflicted_claim_ids(db: AsyncSession, workspace_id: str, batch_id: str) -> set[str]:
    """Claims that belong to a conflict nobody has decided yet."""
    conflict_result = await db.execute(
        select(EvidenceConflict.claim_ids)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
        .where(EvidenceConflict.status.in_(["open", "escalated"]))
    )
    return {
        str(claim_id)
        for claim_ids in conflict_result.scalars().all()
        for claim_id in claim_ids or []
    }


def _with_unprofiled(
    columns: list[str], samples: dict[str, list[str]], claimed: Iterable[str]
) -> None:
    """A column that only the claims know still has to be decidable."""
    for column in sorted(set(claimed) - set(samples)):
        columns.append(column)
        samples[column] = []


def _examples_of(cells: Iterable[tuple[str, str | None]]) -> dict[str, list[str]]:
    """The first distinct values of each column, from cells in file order."""
    examples: dict[str, list[str]] = defaultdict(list)
    for column, raw_value in cells:
        shown = examples[column]
        value = (raw_value or "").strip()
        if value and value not in shown and len(shown) < EXAMPLES_PER_COLUMN:
            shown.append(value)
    return dict(examples)


def _accepted_mappings(
    mappings: Iterable[tuple[str, str | None, str | None]],
) -> tuple[dict[str, set[str]], list[str]]:
    """From (column, entity, field) of accepted values: the field names each
    column is published under, and the kinds of record they identify."""
    accepted_fields: dict[str, set[str]] = defaultdict(set)
    reviewed: set[str] = set()
    for column, entity, canonical_field in mappings:
        if not canonical_field:
            continue
        accepted_fields[column].add(canonical_field)
        # The same test publishing applies: an accepted mapping onto the
        # primary key of a kind of record says what the rows are.
        if entity in ENTITY_PRIMARY_KEYS and canonical_field == ENTITY_PRIMARY_KEYS[entity]:
            reviewed.add(entity)
    return dict(accepted_fields), sorted(reviewed)


def _claims_of_file(
    workspace_id: str, batch_id: str, file: SourceFile
) -> tuple[ColumnElement[bool], ...]:
    return (
        EvidenceClaim.workspace_id == workspace_id,
        EvidenceClaim.batch_id == batch_id,
        EvidenceClaim.source_file_id == file.file_id,
    )


async def _facts_from_database(
    db: AsyncSession, workspace_id: str, batch_id: str, file: SourceFile
) -> _FileFacts:
    """The facts of a file, counted where the claims are stored."""
    columns, samples = await _profiled_columns(db, workspace_id, file)
    of_file = _claims_of_file(workspace_id, batch_id, file)

    tally_result = await db.execute(
        select(
            EvidenceClaim.source_column,
            EvidenceClaim.claim_state,
            func.count(EvidenceClaim.claim_id),
        )
        .where(*of_file)
        .group_by(EvidenceClaim.source_column, EvidenceClaim.claim_state)
    )
    tallies: dict[str, dict[str, int]] = defaultdict(dict)
    for column, claim_state, count in tally_result.all():
        tallies[str(column)][str(claim_state)] = int(count)
    _with_unprofiled(columns, samples, tallies)

    mapping_result = await db.execute(
        select(
            EvidenceClaim.source_column,
            EvidenceClaim.canonical_entity,
            EvidenceClaim.canonical_field,
        )
        .where(*of_file)
        .where(EvidenceClaim.claim_state == _ACCEPTED)
        .distinct()
    )
    accepted_fields, reviewed = _accepted_mappings(
        (str(column), entity, canonical_field)
        for column, entity, canonical_field in mapping_result.all()
    )

    in_conflict: dict[str, int] = defaultdict(int)
    conflicted_ids = sorted(await _conflicted_claim_ids(db, workspace_id, batch_id))
    for start in range(0, len(conflicted_ids), _ID_PORTION):
        conflict_result = await db.execute(
            select(EvidenceClaim.source_column, func.count(EvidenceClaim.claim_id))
            .where(*of_file)
            .where(EvidenceClaim.claim_state == _PENDING)
            .where(EvidenceClaim.claim_id.in_(conflicted_ids[start : start + _ID_PORTION]))
            .group_by(EvidenceClaim.source_column)
        )
        for column, count in conflict_result.all():
            in_conflict[str(column)] += int(count)

    example_result = await db.execute(
        select(EvidenceClaim.source_column, EvidenceClaim.raw_value)
        .where(*of_file)
        .where(EvidenceClaim.row_number <= EXAMPLE_ROWS)
        .order_by(EvidenceClaim.row_number, EvidenceClaim.claim_id)
    )
    examples = _examples_of((str(column), raw_value) for column, raw_value in example_result.all())

    return _FileFacts(
        file=file,
        columns=columns,
        samples=samples,
        examples=examples,
        tallies=dict(tallies),
        in_conflict=dict(in_conflict),
        recognised=infer_entity_type(columns) if columns else None,
        reviewed=reviewed,
        accepted_fields=accepted_fields,
    )


async def _load_file_state(
    db: AsyncSession, workspace_id: str, batch_id: str, file: SourceFile
) -> _FileState:
    """The facts of a file and its claims, locked for the decision that follows."""
    columns, samples = await _profiled_columns(db, workspace_id, file)

    # Locked: a second decision on the same file waits for this one and then
    # sees what it left, instead of deciding the same values again.
    claim_result = await db.execute(
        select(EvidenceClaim)
        .where(*_claims_of_file(workspace_id, batch_id, file))
        .with_for_update()
    )
    claims = list(claim_result.scalars().all())
    _with_unprofiled(columns, samples, (claim.source_column for claim in claims))
    column_index = {column: index for index, column in enumerate(columns)}
    claims.sort(
        key=lambda claim: (
            claim.row_number,
            column_index.get(claim.source_column, len(columns)),
            claim.claim_id,
        )
    )
    conflicted_ids = await _conflicted_claim_ids(db, workspace_id, batch_id)

    tallies: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    in_conflict: dict[str, int] = defaultdict(int)
    for claim in claims:
        tallies[claim.source_column][claim.claim_state] += 1
        if claim.claim_state == _PENDING and claim.claim_id in conflicted_ids:
            in_conflict[claim.source_column] += 1
    accepted_fields, reviewed = _accepted_mappings(
        (claim.source_column, claim.canonical_entity, claim.canonical_field)
        for claim in claims
        if claim.claim_state == _ACCEPTED
    )
    # In file order within a column: by row, then in the order read.
    in_file_order = sorted(
        (claim for claim in claims if claim.row_number <= EXAMPLE_ROWS),
        key=lambda claim: (claim.row_number, claim.claim_id),
    )
    examples = _examples_of((claim.source_column, claim.raw_value) for claim in in_file_order)

    return _FileState(
        file=file,
        columns=columns,
        samples=samples,
        examples=examples,
        tallies={column: dict(by_state) for column, by_state in tallies.items()},
        in_conflict=dict(in_conflict),
        recognised=infer_entity_type(columns) if columns else None,
        reviewed=reviewed,
        accepted_fields=accepted_fields,
        claims=claims,
        conflicted_ids=conflicted_ids,
    )


def _entity_as_it_stands(
    state: _FileFacts, proposed: str | None
) -> tuple[str | None, str | None, str | None]:
    """(entity, where it comes from, problem) in the order publishing resolves it."""
    if state.recognised:
        return state.recognised, "columns", None
    if len(state.reviewed) == 1:
        return state.reviewed[0], "review", None
    if len(state.reviewed) > 1:
        kinds = ", ".join(state.reviewed)
        return (
            None,
            None,
            f"Accepted values of this file identify more than one kind of record ({kinds}). "
            "It cannot be published or reviewed by column until only one remains.",
        )
    if proposed in ENTITY_PRIMARY_KEYS:
        return proposed, "proposed", None
    return None, None, None


def _field_of(
    state: _FileFacts, column: str, entity: str | None, renames: dict[str, str] | None = None
) -> str:
    """The field a column is published under: a rename asked for now, else the
    name its accepted values already carry, else the name its header gives."""
    explicit = (renames or {}).get(column)
    if explicit:
        return explicit
    accepted = state.accepted_fields.get(column)
    if accepted:
        return sorted(accepted)[0]
    return canonical_column_name(column, entity)


def _describe(state: _FileFacts, proposed: str | None) -> FileReview:
    entity, entity_source, problem = _entity_as_it_stands(state, proposed)
    key_field = ENTITY_PRIMARY_KEYS.get(entity) if entity else None
    fields = {column: _field_of(state, column, entity) for column in state.columns}
    key_column = (
        next((column for column in state.columns if fields[column] == key_field), None)
        if key_field
        else None
    )

    columns: list[ColumnReview] = []
    for column in state.columns:
        canonical_field = fields[column]
        link = ENTITY_FOREIGN_KEYS.get((entity, canonical_field)) if entity else None
        if column == key_column:
            role = "key"
        elif link is not None:
            role = "link"
        else:
            role = "value"
        tally = state.tallies.get(column, {})
        columns.append(
            ColumnReview(
                source_column=column,
                canonical_field=canonical_field,
                role=role,
                links_to=link[0] if role == "link" and link is not None else None,
                examples=state.examples.get(column) or state.samples[column][:EXAMPLES_PER_COLUMN],
                pending=tally.get(_PENDING, 0),
                accepted=tally.get(_ACCEPTED, 0),
                rejected=tally.get(_REJECTED, 0),
                superseded=tally.get(_SUPERSEDED, 0),
                in_conflict=state.in_conflict.get(column, 0),
            )
        )

    return FileReview(
        file_id=state.file.file_id,
        name=state.file.original_name,
        rows=state.file.row_count,
        entity=entity,
        entity_source=entity_source,
        key_field=key_field,
        key_column=key_column,
        problem=problem,
        columns=columns,
    )


async def describe_file(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
    file: SourceFile,
    proposed_entity: str | None = None,
) -> FileReview:
    """How the file stands: what its rows are and how each column is published.

    ``proposed_entity`` is used only while nothing else says what the rows
    are; it shows how the columns would be named for that kind of record.
    """
    facts = await _facts_from_database(db, workspace_id, batch_id, file)
    return _describe(facts, proposed_entity)


def _live(column: ColumnReview) -> int:
    """Values of a column that are published or may still be."""
    return column.pending + column.accepted


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


async def decide_columns(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
    file: SourceFile,
    *,
    decision: str,
    source_columns: list[str] | None = None,
    canonical_entity: str | None = None,
    canonical_fields: dict[str, str] | None = None,
) -> ColumnDecisionResult:
    """Accept or reject every waiting value of the named columns of one file.

    Without ``source_columns`` the decision covers every column. Values that
    belong to an open conflict are left to the conflict. Raises
    :class:`ColumnReviewError` before anything is changed when the decision
    cannot be applied.
    """
    if decision not in {_ACCEPTED, _REJECTED}:
        raise ColumnReviewError("A column is either accepted or rejected")
    state = await _load_file_state(db, workspace_id, batch_id, file)
    renames = dict(canonical_fields or {})
    column_index = state.column_index

    if source_columns is not None:
        unknown = [column for column in source_columns if column not in column_index]
        if unknown:
            raise ColumnReviewError(
                f"{', '.join(sorted(set(unknown)))}: not a column of {file.original_name}"
            )
        if not source_columns:
            raise ColumnReviewError("Name at least one column, or leave the list out for all")
    selected = set(source_columns) if source_columns is not None else set(state.columns)

    waiting = [
        claim
        for claim in state.claims
        if claim.claim_state == _PENDING and claim.source_column in selected
    ]
    to_decide = [claim for claim in waiting if claim.claim_id not in state.conflicted_ids]
    left_in_conflict = len(waiting) - len(to_decide)
    if not to_decide:
        message = "No value of these columns waits for a decision."
        if left_in_conflict:
            message = (
                f"{_plural(left_in_conflict, 'value')} of these columns "
                f"{'belongs' if left_in_conflict == 1 else 'belong'} to an open conflict "
                "and can only be decided there."
            )
        raise ColumnReviewError(message, status_code=409)
    deciding = {claim.source_column for claim in to_decide}
    decided_columns = [column for column in state.columns if column in deciding]

    if decision == _REJECTED:
        if canonical_entity is not None or renames:
            raise ColumnReviewError("A rejection takes no kind of record and no field names")
        review = _describe(state, None)
        others_live = [
            column.source_column
            for column in review.columns
            if column.source_column not in selected and _live(column) > 0
        ]
        if review.key_column in deciding and others_live:
            raise ColumnReviewError(
                f"{review.key_column} identifies the record of each row. Without it the other "
                f"columns ({', '.join(others_live)}) have no record to belong to and nothing "
                "of this file is published. Reject every column of the file instead, or "
                "reject single values in the table below."
            )
        for claim in to_decide:
            claim.claim_state = _REJECTED
            claim.requires_review = False
        await db.flush()
        conflicts = await detect_conflicts(db, workspace_id, batch_id)
        return ColumnDecisionResult(
            decision=decision,
            canonical_entity=None,
            columns={column: None for column in decided_columns},
            claims_decided=len(to_decide),
            claims_left_in_conflict=left_in_conflict,
            conflicts_detected=conflicts.conflicts_detected,
        )

    # ── Acceptance ────────────────────────────────────────────────────────
    entity, entity_source, problem = _entity_as_it_stands(state, None)
    if problem:
        raise ColumnReviewError(problem, status_code=409)
    if entity is None:
        if canonical_entity is None:
            raise ColumnReviewError(
                "The column names do not say what kind of record each row of this file is. "
                "Choose the kind of record and the column that identifies each one."
            )
        if canonical_entity not in ENTITY_PRIMARY_KEYS:
            raise ColumnReviewError(f"{canonical_entity} is not a kind of record a file can hold")
        entity = canonical_entity
    elif canonical_entity is not None and canonical_entity != entity:
        reason = (
            "recognised from its column names"
            if entity_source == "columns"
            else "set by the accepted values of its identifying column"
        )
        raise ColumnReviewError(
            f"The rows of this file are {entity} records ({reason}); "
            f"they cannot be accepted as {canonical_entity}."
        )
    key_field = ENTITY_PRIMARY_KEYS[entity]

    for column, name in renames.items():
        if column not in column_index:
            raise ColumnReviewError(f"{column}: not a column of {file.original_name}")
        if column not in selected:
            raise ColumnReviewError(
                f"A field name was given for {column}, which is not part of this decision"
            )
        if not _FIELD_NAME.fullmatch(name or ""):
            raise ColumnReviewError(
                f"{name!r} cannot be a field name: use lowercase letters, digits and "
                "underscores, starting with a letter"
            )
        already = state.accepted_fields.get(column)
        if already and name not in already:
            raise ColumnReviewError(
                f"{column} already has accepted values published as {sorted(already)[0]}; "
                "the rest of the column has to use the same name"
            )
    for column in decided_columns:
        if len(state.accepted_fields.get(column, ())) > 1:
            names = ", ".join(sorted(state.accepted_fields[column]))
            raise ColumnReviewError(
                f"Accepted values of {column} are published under several names ({names}); "
                "it cannot be decided as one column.",
                status_code=409,
            )

    fields = {column: _field_of(state, column, entity, renames) for column in state.columns}

    # One field holds one column: two columns under one name would give a
    # record two values for it and block publishing at every row.
    published = [
        column
        for column in state.columns
        if column in deciding or state.accepted_fields.get(column)
    ]
    by_field: dict[str, list[str]] = defaultdict(list)
    for column in published:
        by_field[fields[column]].append(column)
    for name, sharing in by_field.items():
        if len(sharing) > 1:
            raise ColumnReviewError(
                f"{' and '.join(sharing)} would both be published as {name}. "
                "Give each its own field name, or reject one of them."
            )

    review = _describe(state, entity)
    key_columns = [column for column in state.columns if fields[column] == key_field]
    live_keys = [
        column
        for column in key_columns
        if _live(next(item for item in review.columns if item.source_column == column)) > 0
    ]
    if not key_columns:
        raise ColumnReviewError(
            f"No column of this file holds the {key_field} that identifies each {entity}. "
            f"Name the column that does (publish it as {key_field}), "
            "or choose another kind of record."
        )
    if not live_keys:
        raise ColumnReviewError(
            f"The values of {key_columns[0]}, which identifies each {entity}, were all "
            "rejected or withdrawn. Without them no row of this file can be published.",
            status_code=409,
        )

    for claim in to_decide:
        canonical_field = fields[claim.source_column]
        claim.canonical_entity = entity
        claim.canonical_field = canonical_field
        claim.confidence = 1.0
        claim.provenance = {
            **(claim.provenance or {}),
            "human_mapping_review": {
                "canonical_entity": entity,
                "canonical_field": canonical_field,
                "scope": "column",
            },
        }
        claim.claim_state = _ACCEPTED
        claim.requires_review = False

    # An accepted value is compared with other accepted values of the same
    # record. The record is the one named by the identifying cell of its row,
    # read exactly as for a single reviewed claim (``row_entity_key``).
    key_by_row: dict[int, str] = {}
    for claim in state.claims:
        if claim.row_number < 1 or claim.row_number in key_by_row:
            continue
        reviewed = claim.claim_state == _ACCEPTED and claim.canonical_field
        cell_field = (
            claim.canonical_field
            if reviewed
            else canonical_column_name(claim.source_column, entity)
        )
        if cell_field == key_field:
            value = (claim.normalized_value or claim.raw_value or "").strip()
            if value:
                key_by_row[claim.row_number] = value
    for claim in to_decide:
        provenance = claim.provenance or {}
        if not provenance.get("entity_key") and claim.row_number in key_by_row:
            claim.provenance = {**provenance, "entity_key": key_by_row[claim.row_number]}

    await db.flush()
    conflicts = await detect_conflicts(db, workspace_id, batch_id)
    return ColumnDecisionResult(
        decision=decision,
        canonical_entity=entity,
        columns={column: fields[column] for column in decided_columns},
        claims_decided=len(to_decide),
        claims_left_in_conflict=left_in_conflict,
        conflicts_detected=conflicts.conflicts_detected,
    )
