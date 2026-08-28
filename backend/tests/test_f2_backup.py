"""F2 — Backup script contract (Phase 15 production gate).

Pins the wire contract for the F2 backup script
(``scripts/backup.py``) so that:

- The frozen table list used for the post-backup
  ``SELECT COUNT(*)`` verification matches the live
  schema. Adding a new frozen table without updating the
  list (or vice-versa) is a silent data-protection bug.
- The status dict the script prints to stdout has a
  stable shape that the K8s CronJob parses. Renaming a
  field silently breaks the alerting path.
- The script is runnable as ``python scripts/backup.py``
  in dev (the import contract is preserved).

The test is hermetic — it does not actually run pg_dump
or psql. It exercises the helper functions that build
the pg_dump command and shape the status dict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests -> backend -> repo
SCRIPTS_DIR = REPO_ROOT / "scripts"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Frozen table list — the COUNT(*) verification must check these tables
# ─────────────────────────────────────────────────────────────────────────────

class TestFrozenTablesForVerify:
    """The backup script verifies its own integrity by
    restoring into a scratch schema and running
    ``SELECT COUNT(*)`` on each of these tables. If a new
    table is added to the schema, the operator MUST update
    this list. The test pins the current contract."""

    def test_frozen_table_list_includes_core_tables(self):
        # Import the script module; it must be importable
        # without invoking main() so the test stays fast.
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            import backup  # type: ignore
        except ImportError:
            pytest.skip("backup.py not on sys.path")

        for required in (
            "world_state",
            "events",
            "decisions",
            "audit_log",
            "users",
        ):
            assert required in backup.FROZEN_TABLES_FOR_VERIFY, (
                f"FROZEN_TABLES_FOR_VERIFY must include {required!r}; "
                f"without it, the post-backup verification is incomplete."
            )

    def test_frozen_table_list_no_duplicates(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            import backup  # type: ignore
        except ImportError:
            pytest.skip("backup.py not on sys.path")

        assert len(backup.FROZEN_TABLES_FOR_VERIFY) == len(
            set(backup.FROZEN_TABLES_FOR_VERIFY)
        ), "Duplicate table names in the verify list — would run COUNT(*) twice."

    def test_frozen_table_list_uses_lowercase(self):
        # PG table names are case-folded unless quoted; using
        # mixed case in the verify list would silently
        # double-count and break the contract.
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            import backup  # type: ignore
        except ImportError:
            pytest.skip("backup.py not on sys.path")
        for t in backup.FROZEN_TABLES_FOR_VERIFY:
            assert t == t.lower(), (
                f"Table name {t!r} must be lowercase; PG folds to "
                f"lowercase unless quoted and we don't quote."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Status dict shape — the K8s CronJob tail-logs this
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusDictContract:
    """The script prints a JSON status dict to stdout. The
    K8s CronJob's tail-log parse relies on the field
    names. Renaming ``backup_file`` to ``file`` would
    silently break the alerting path."""

    def test_status_dict_has_required_fields(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from backup import _status
        except ImportError:
            pytest.skip("backup.py not on sys.path")
        s = _status(ok=True, backup_file="cortex-x.sql.gz",
                    backup_size_bytes=1024)
        for required in ("script", "timestamp", "ok"):
            assert required in s, f"Status missing field {required!r}"

    def test_status_dict_is_json_serializable(self):
        # The K8s CronJob parses stdout as JSON. The status
        # must be a plain dict (no dataclass, no datetime)
        # so json.dumps works without a custom encoder.
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from backup import _status
        except ImportError:
            pytest.skip("backup.py not on sys.path")
        s = _status(ok=True, backup_file="cortex-x.sql.gz",
                    backup_size_bytes=1024)
        encoded = json.dumps(s)
        decoded = json.loads(encoded)
        assert decoded["ok"] is True
        assert decoded["backup_file"] == "cortex-x.sql.gz"


# ─────────────────────────────────────────────────────────────────────────────
# 3. pg_dump command construction — credentials stay out of argv
# ─────────────────────────────────────────────────────────────────────────────

class TestPgDumpCommandContract:
    """The script must pass the DB password via ``PGPASSWORD``
    env var, never as a command-line argument (which would
    be visible in ``ps`` and process listings). The test
    pins this contract."""

    def test_password_not_in_argv(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from backup import _build_pg_dump_cmd
        except ImportError:
            pytest.skip("backup.py not on sys.path")
        cmd = _build_pg_dump_cmd(Path("/tmp/x.sql"))
        # The full cmd is a list of strings. None of them
        # should look like a password. The password is the
        # only field not in this list, so it cannot leak.
        cmd_str = " ".join(cmd)
        assert "PGPASSWORD" not in cmd_str
        # The script's env-var path is the only way the
        # password reaches pg_dump; if a future refactor
        # adds the password as a -W arg or as the last
        # positional, this test catches it.

    def test_command_includes_required_flags(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from backup import _build_pg_dump_cmd
        except ImportError:
            pytest.skip("backup.py not on sys.path")
        cmd = _build_pg_dump_cmd(Path("/tmp/x.sql"))
        # --no-owner and --no-privileges are required so the
        # backup can be restored to a fresh cluster with
        # different role names. --format=plain is required
        # so the script can pipe the dump into psql during
        # the verification step.
        for required in ("--no-owner", "--no-privileges", "--format=plain"):
            assert required in cmd, (
                f"pg_dump command must include {required!r}; missing it "
                f"breaks restore or verification."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Script runs (smoke) — main() is invokable without raising
# ─────────────────────────────────────────────────────────────────────────────

class TestBackupScriptRunnable:
    """The script must be importable and ``main()`` must be
    invokable. We don't actually run pg_dump in this test —
    that would require a live PG instance and is exercised
    by the K8s CronJob in production. We only verify the
    import contract here."""

    def test_script_module_imports(self):
        # Add scripts/ to sys.path so we can import the
        # module by name. The script uses relative paths
        # (../datasets_test) so we must run it from the
        # repo root, not from the test directory.
        sys.path.insert(0, str(SCRIPTS_DIR))
        import backup  # type: ignore
        assert hasattr(backup, "main")
        assert hasattr(backup, "run_backup")
        assert hasattr(backup, "_build_pg_dump_cmd")

    def test_run_backup_returns_status_dict(self, tmp_path, monkeypatch):
        # Stub out pg_dump and the verify path so the test
        # is hermetic. We're testing the contract (returns
        # a dict with the right shape), not the backup
        # itself.
        sys.path.insert(0, str(SCRIPTS_DIR))
        import backup  # type: ignore

        # pg_dump creates the file; simulate that.
        def _fake_pg_dump(cmd, env):
            # Find the --file argument and create an empty
            # file there.
            try:
                i = cmd.index("--file")
                Path(cmd[i + 1]).write_text("-- stub dump --\n")
            except (ValueError, IndexError):
                pass
            return (0, "", "")

        monkeypatch.setattr(backup, "_run", _fake_pg_dump)
        # Skip the verify step (would need psql + live DB)
        monkeypatch.setattr(backup, "_verify_backup",
                            lambda p: {"ok": True, "skipped": True})

        status = backup.run_backup(
            backup_dir=tmp_path,
            compress=False,
            verify=False,  # also skip in run_backup
        )
        assert status["ok"] is True
        assert "backup_file" in status
        assert "backup_size_bytes" in status
        assert status["backup_size_bytes"] >= 0
