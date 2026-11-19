"""Import the synthetic demo dataset through the preview and commit services.

Usage (from services/api):
    uv run python ../../scripts/seed_demo_data.py
    uv run python ../../scripts/seed_demo_data.py --reset --confirm "DELETE ALL LOCAL NEXUS DATA"

Every file goes through the same preview and commit services the API uses, in
dependency order. Nothing is written to a canonical table directly. The seed
is safe to run twice: files that are already committed are recognised by
their checksum and nothing is written again.

After the import the dataset is checked against the World State, expected
values next to actual ones. The exit code is 1 if a file cannot be imported
completely or a check fails.

--reset deletes every record of the local development database first. It is
never the default, works only when APP_ENV is development and the database is
on this machine, and needs the confirmation phrase.
"""

import argparse
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

import demo_checks
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.db.base import Base
from app.db.session import Database
from app.models.enums import BatchStatus, IngestionEntityType
from app.repositories import project_repository
from app.services import ingestion_service, workspace_service, world_state_service
from app.services.ingestion_service import ImportLimits, UploadedFile

RESET_PHRASE = "DELETE ALL LOCAL NEXUS DATA"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "127.0.0.2", "::1"})


class SeedError(Exception):
    """The seed cannot continue."""


def reset_database(database: Database, settings: Settings, confirmation: str | None) -> None:
    """Delete every row of every table. Development only, local only, confirmed only."""
    host = settings.sqlalchemy_url.host or ""
    if not settings.is_development:
        raise SeedError("--reset is refused: APP_ENV is not development.")
    if host not in LOCAL_HOSTS:
        raise SeedError("--reset is refused: the database is not on this machine.")
    if confirmation != RESET_PHRASE:
        raise SeedError(f'--reset needs --confirm "{RESET_PHRASE}". Nothing was deleted.')
    with database.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(text(f'DELETE FROM "{table.name}"'))
    print(f"RESET  every record deleted from {settings.database_url_redacted}")


def import_file(
    session: Session, workspace_id: UUID, entry: dict[str, Any], limits: ImportLimits
) -> None:
    """Preview one file and commit it, through the services. Fails fast on any problem."""
    relative = entry["file"]
    data = (demo_checks.DATASET_DIR / relative).read_bytes()
    upload = UploadedFile(filename=Path(relative).name, content_type="text/csv", data=data)
    entity_type = IngestionEntityType(entry["entity_type"])

    preview = ingestion_service.preview_import(
        session, workspace_id, upload, entity_type, limits=limits
    )
    batch = preview.batch
    if batch.total_rows != entry["rows"] or batch.invalid_rows:
        for issue in preview.errors:
            print(f"       row {issue['row_number']}: {issue['code']} ({issue.get('column')})")
        raise SeedError(
            f"{relative}: expected {entry['rows']} valid rows, found {batch.valid_rows} valid "
            f"and {batch.invalid_rows} invalid of {batch.total_rows}. Later files depend on "
            "this one; the seed stops here."
        )

    if batch.status is BatchStatus.COMMITTED:
        result = "already committed (same file, nothing written)"
    else:
        ingestion_service.commit_import(session, workspace_id, batch.id)
        result = "committed"
    print(
        f"{relative:<46} {entity_type.value:<20} batch={batch.id} rows={batch.total_rows} "
        f"valid={batch.valid_rows} invalid={batch.invalid_rows} "
        f"committed={batch.committed_rows} skipped={batch.skipped_rows}  {result}"
    )


def world_state_json(session: Session, workspace_id: UUID, project_code: str) -> tuple[Any, Any]:
    """The workspace summary and the demo project's World State, as the API would return them."""
    project = project_repository.get_by_code(session, workspace_id, project_code)
    session.rollback()
    if project is None:
        raise SeedError(f"The demo project {project_code} was not imported.")
    summary = world_state_service.get_workspace_world_state_summary(session, workspace_id)
    detail = world_state_service.get_project_world_state(
        session,
        workspace_id,
        project.id,
        equipment_limit=200,
        po_limit=200,
        include_history=True,
    )
    return summary.model_dump(mode="json"), detail.model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete all local data first")
    parser.add_argument("--confirm", help=f'required with --reset: "{RESET_PHRASE}"')
    arguments = parser.parse_args()

    settings = get_settings()
    workspace_id = settings.nexus_dev_workspace_id
    if workspace_id is None:
        print("NEXUS_DEV_WORKSPACE_ID is not configured.", file=sys.stderr)
        return 1
    manifest = demo_checks.load_manifest()
    database = Database.from_settings(settings)
    try:
        if arguments.reset:
            reset_database(database, settings, arguments.confirm)
        with database.session() as session:
            workspace, created = workspace_service.ensure_development_workspace(
                session,
                workspace_id,
                name=manifest["workspace"]["name"],
                slug=manifest["workspace"]["slug"],
            )
            print(
                f"WORKSPACE {workspace.id} {workspace.slug!r} "
                f"({'created' if created else 'already present'}, {workspace.status.value})"
            )
            limits = ImportLimits.from_settings(settings)
            for entry in [*manifest["files"], *manifest["updates"]]:
                import_file(session, workspace.id, entry, limits)

            summary, project = world_state_json(session, workspace.id, manifest["project_code"])
    except (SeedError, DomainError) as exc:
        code = f" [{exc.code}]" if isinstance(exc, DomainError) else ""
        print(f"SEED FAILED{code}: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    print("\nWORLD STATE totals (counted in PostgreSQL)")
    for kind, value in summary["summary"].items():
        print(f"  {kind:<30} {value}")

    print("\nDATASET CHECKS")
    checks = demo_checks.check_demo_world_state(manifest, summary, project)
    for check in checks:
        print("  " + check.line())
    failed = [check for check in checks if not check.passed]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed.")
    if failed:
        print(
            "SEED CHECKS FAILED. If the workspace holds records that are not part of the demo "
            "dataset, the workspace counts differ.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
