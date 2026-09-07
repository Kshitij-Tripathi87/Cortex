"""Workflo sandbox orchestrator.

Owns the full sandbox lifecycle: creation of an isolated root on disk
(/workspace, /artifacts, /tmp), controlled file ingress/egress, policy-checked
command execution with timeout/output caps/artifact collection, inspection, and
destruction. Sandboxes never touch the host filesystem outside their own root
and never inherit host environment secrets.
"""

from __future__ import annotations

import asyncio
import os
import subprocess  # noqa: S404 - commands run under a strict allowlist policy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.common.ids import uuid7

from .policy import PolicyViolation, SandboxPolicy


class SandboxError(Exception):
    """Raised for operational sandbox failures (not policy violations)."""


class SandboxNotFound(SandboxError):
    pass


@dataclass
class Artifact:
    name: str
    path: str
    size_bytes: int


@dataclass
class ExecutionResult:
    sandbox_id: str
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    artifacts: list[Artifact] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "artifacts": [
                {"name": a.name, "path": a.path, "size_bytes": a.size_bytes} for a in self.artifacts
            ],
            "truncated": self.truncated,
        }


@dataclass
class Sandbox:
    id: str
    workspace_id: str
    name: str
    root: Path
    policy: SandboxPolicy
    status: str = "running"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "status": self.status,
            "policy": self.policy.to_dict(),
            "created_at": self.created_at,
        }


_SANDBOX_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "LANG",
    "LC_ALL",
    "TZ",
)


def _sandbox_env() -> dict[str, str]:
    """Build a minimal environment for sandbox processes.

    Host secrets (AWS keys, tokens, database DSNs) are never inherited: only a
    small allowlist of OS-required variables passes through.
    """
    env: dict[str, str] = {}
    for key in _SANDBOX_ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["WORKFLO_SANDBOX"] = "1"
    return env


def _resolve_in(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    root_resolved = root.resolve()
    if os.path.commonpath([str(p), str(root_resolved)]) != str(root_resolved):
        raise PolicyViolation(f"path '{relative}' escapes the sandbox filesystem scope")
    return p


class SandboxOrchestrator:
    """Creates, inspects, executes within, and destroys sandboxes."""

    def __init__(self, storage_root: Path | str) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, Sandbox] = {}
        self._destroyed: set[str] = set()

    # -- lifecycle ---------------------------------------------------------

    def create_sandbox(
        self,
        workspace_id: str,
        name: str,
        policy_data: dict[str, Any] | None = None,
    ) -> Sandbox:
        policy = SandboxPolicy.from_dict(policy_data)
        policy.validate_bounds()
        sandbox_id = f"sbx_{uuid7()}"
        root = self.storage_root / sandbox_id
        for sub in ("workspace", "artifacts", "tmp"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        sandbox = Sandbox(
            id=sandbox_id,
            workspace_id=workspace_id,
            name=name,
            root=root,
            policy=policy,
        )
        self._sandboxes[sandbox_id] = sandbox
        return sandbox

    def get(self, sandbox_id: str) -> Sandbox:
        if sandbox_id in self._destroyed:
            raise PolicyViolation(f"sandbox '{sandbox_id}' was destroyed; reuse is blocked")
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            raise SandboxNotFound(f"sandbox '{sandbox_id}' not found")
        return sandbox

    def inspect(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = self.get(sandbox_id)
        ws = sandbox.root / "workspace"
        files = sorted(
            str(p.relative_to(sandbox.root)).replace("\\", "/")
            for p in ws.rglob("*")
            if p.is_file()
        )
        artifacts_dir = sandbox.root / "artifacts"
        artifacts = sorted(
            str(p.relative_to(sandbox.root)).replace("\\", "/")
            for p in artifacts_dir.rglob("*")
            if p.is_file()
        )
        info = sandbox.to_dict()
        info["files"] = files[:500]
        info["file_count"] = len(files)
        info["artifacts"] = artifacts
        return info

    def destroy(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = self.get(sandbox_id)
        sandbox.status = "destroyed"
        import shutil

        shutil.rmtree(sandbox.root, ignore_errors=True)
        del self._sandboxes[sandbox_id]
        self._destroyed.add(sandbox_id)
        return {"id": sandbox_id, "status": "destroyed"}

    # -- file ingress / egress ----------------------------------------------

    def write_file(self, sandbox_id: str, path: str, content: bytes) -> dict[str, Any]:
        sandbox = self.get(sandbox_id)
        if not sandbox.policy.path_is_safe_relative(path):
            raise PolicyViolation(f"path '{path}' escapes the sandbox filesystem scope")
        target = _resolve_in(sandbox.root / "workspace", path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if len(content) > sandbox.policy.artifact_max_bytes:
            raise PolicyViolation("file exceeds artifact_max_bytes")
        target.write_bytes(content)
        return {"path": path, "size_bytes": len(content)}

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        sandbox = self.get(sandbox_id)
        rel = path
        if rel.startswith(("workspace/", "/workspace")):
            rel = rel.split("workspace/", 1)[-1]
        elif rel.startswith("/"):
            raise PolicyViolation(f"path '{path}' escapes the sandbox filesystem scope")
        if not sandbox.policy.path_is_safe_relative(rel):
            raise PolicyViolation(f"path '{path}' escapes the sandbox filesystem scope")
        target = _resolve_in(sandbox.root / "workspace", rel)
        if not target.is_file():
            raise SandboxNotFound(f"file '{path}' not found in sandbox")
        return target.read_bytes()

    def list_files(self, sandbox_id: str, path: str = "") -> list[dict[str, Any]]:
        sandbox = self.get(sandbox_id)
        base_rel = path or ""
        if base_rel.startswith("/"):
            raise PolicyViolation(f"path '{path}' escapes the sandbox filesystem scope")
        if base_rel and not sandbox.policy.path_is_safe_relative(base_rel):
            raise PolicyViolation(f"path '{path}' escapes the sandbox filesystem scope")
        base = _resolve_in(sandbox.root / "workspace", base_rel)
        if not base.exists():
            raise SandboxNotFound(f"path '{path}' not found in sandbox")
        out: list[dict[str, Any]] = []
        for p in sorted(base.rglob("*")):
            rel = str(p.relative_to(sandbox.root / "workspace")).replace("\\", "/")
            if p.is_file():
                out.append({"path": rel, "size_bytes": p.stat().st_size})
            else:
                out.append({"path": rel + "/", "size_bytes": None})
        return out[:1000]

    # -- execution -----------------------------------------------------------

    async def execute(
        self, sandbox_id: str, command: str, timeout_s: int | None = None
    ) -> ExecutionResult:
        sandbox = self.get(sandbox_id)
        if sandbox.status != "running":
            raise PolicyViolation(
                f"sandbox '{sandbox_id}' is {sandbox.status}; reuse after destroy is blocked"
            )
        sandbox.policy.check_command(command)
        effective_timeout = min(
            timeout_s or sandbox.policy.execution_timeout_s,
            sandbox.policy.execution_timeout_s,
        )

        workspace = sandbox.root / "workspace"
        started = time.monotonic()
        timed_out = False
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workspace),
                env=_sandbox_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise SandboxError(f"failed to spawn process: {exc}") from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()
            stdout_b, stderr_b = b"", b""

        duration_ms = int((time.monotonic() - started) * 1000)
        cap = sandbox.policy.output_max_bytes
        truncated = len(stdout_b) > cap or len(stderr_b) > cap
        stdout = stdout_b[:cap].decode("utf-8", errors="replace")
        stderr = stderr_b[:cap].decode("utf-8", errors="replace")

        result = ExecutionResult(
            sandbox_id=sandbox_id,
            command=command,
            exit_code=None if timed_out else proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_ms=duration_ms,
            truncated=truncated,
        )
        result.artifacts = self.collect_artifacts(sandbox)
        return result

    # -- artifacts -----------------------------------------------------------

    def collect_artifacts(self, sandbox: Sandbox) -> list[Artifact]:
        artifacts_dir = sandbox.root / "artifacts"
        found: list[Artifact] = []
        for p in sorted(artifacts_dir.rglob("*")):
            if p.is_file():
                size = p.stat().st_size
                if size > sandbox.policy.artifact_max_bytes:
                    continue
                found.append(
                    Artifact(
                        name=str(p.relative_to(artifacts_dir)),
                        path=f"artifacts/{p.relative_to(artifacts_dir)}",
                        size_bytes=size,
                    )
                )
        return found[: sandbox.policy.artifact_limit]

    def save_artifact(self, sandbox_id: str, name: str, content: bytes) -> dict[str, Any]:
        sandbox = self.get(sandbox_id)
        if not sandbox.policy.path_is_safe_relative(name):
            raise PolicyViolation(f"artifact name '{name}' is unsafe")
        existing = self.collect_artifacts(sandbox)
        if len(existing) >= sandbox.policy.artifact_limit:
            raise PolicyViolation("artifact_limit reached")
        if len(content) > sandbox.policy.artifact_max_bytes:
            raise PolicyViolation("artifact exceeds artifact_max_bytes")
        target = _resolve_in(sandbox.root / "artifacts", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"name": name, "path": f"artifacts/{name}", "size_bytes": len(content)}

    def fetch_artifact(self, sandbox_id: str, name: str) -> bytes:
        sandbox = self.get(sandbox_id)
        if not sandbox.policy.path_is_safe_relative(name):
            raise PolicyViolation(f"artifact name '{name}' is unsafe")
        target = _resolve_in(sandbox.root / "artifacts", name)
        if not target.is_file():
            raise SandboxNotFound(f"artifact '{name}' not found")
        if target.stat().st_size > sandbox.policy.artifact_max_bytes:
            raise PolicyViolation("artifact exceeds artifact_max_bytes")
        return target.read_bytes()


_orchestrator: SandboxOrchestrator | None = None


def get_orchestrator() -> SandboxOrchestrator:
    """Process-wide orchestrator rooted at CORTEX_WORKFLO_ROOT (default ./.workflo)."""
    global _orchestrator
    if _orchestrator is None:
        root = os.environ.get("CORTEX_WORKFLO_ROOT", ".workflo")
        _orchestrator = SandboxOrchestrator(root)
    return _orchestrator


def reset_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
