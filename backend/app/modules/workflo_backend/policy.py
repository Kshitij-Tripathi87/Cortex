"""Workflo sandbox execution policy.

Defines the declarative security policy applied to every sandbox and every
command executed inside one. The policy is enforced by the orchestrator before
any process is spawned: command allowlist, path scoping, network mode, output
caps, timeouts, and artifact limits. Violations raise PolicyViolation which the
API surfaces as HTTP 403 with a machine-readable reason.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")

BLOCKED_COMMAND_BASENAMES = frozenset(
    {
        "docker",
        "docker-compose",
        "kubectl",
        "ssh",
        "scp",
        "sftp",
        "nc",
        "netcat",
        "telnet",
        "ftp",
        "sudo",
        "su",
        "doas",
        "runas",
        "reg",
        "regedit",
        "diskpart",
        "format",
        "shutdown",
        "taskkill",
        "tasklist",
    }
)

NETWORK_COMMAND_BASENAMES = frozenset(
    {
        "curl",
        "wget",
        "fetch",
        "ping",
        "traceroute",
        "tracert",
        "nslookup",
        "dig",
        "arp",
        "ipconfig",
        "ifconfig",
        "netsh",
        "invoke-webrequest",
        "invoke-restmethod",
        "iwr",
    }
)

BLOCKED_PATH_FRAGMENTS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
)

DANGEROUS_ARG_PATTERNS = (
    "rm -rf /",
    "rm -fr /",
    "mkfs",
    "dd if=/dev/zero of=/dev/",
    ":(){ :|:& };:",
    "> /dev/sda",
    "chmod -r 777 /",
    "del /f /s /q c:\\",
    "rd /s /q c:\\",
    "remove-item -path c:\\ -recurse",
    "format c:",
)

_SENSITIVE_UNIX_ROOTS = frozenset(
    {
        "etc",
        "root",
        "proc",
        "sys",
        "var",
        "usr",
        "home",
        "users",
        "boot",
        "dev",
        "opt",
        "sbin",
        "bin",
        "lib",
        "srv",
    }
)


def _is_unix_path_escape(token: str) -> bool:
    """Classify a leading-'/' token as a host path rather than a CLI flag.

    Single short segments (/c, /q, /y) are Windows-style flags and allowed;
    multi-segment paths or sensitive roots (/etc/shadow, /proc) are escapes.
    """
    lowered = token.lower()
    if lowered == "/":
        return True
    if lowered.startswith("/workspace"):
        return False
    segments = [s for s in lowered.split("/") if s]
    if not segments:
        return False
    if len(segments) >= 2:
        return True
    return segments[0] in _SENSITIVE_UNIX_ROOTS


class PolicyViolation(Exception):
    """Raised when a request violates the sandbox execution policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SandboxPolicy:
    """Declarative isolation policy for a sandbox."""

    cpu_limit: int = 2
    memory_limit_mb: int = 1024
    process_limit: int = 64
    execution_timeout_s: int = 120
    filesystem_scope: str = "sandbox"
    network_mode: str = "none"
    allowed_hosts: tuple[str, ...] = ()
    artifact_limit: int = 50
    artifact_max_bytes: int = 10 * 1024 * 1024
    output_max_bytes: int = 512 * 1024
    command_allowlist: tuple[str, ...] = (
        "node",
        "npm",
        "npx",
        "python",
        "python3",
        "pytest",
        "pip",
        "go",
        "cargo",
        "git",
        "ls",
        "dir",
        "cat",
        "type",
        "echo",
        "pwd",
        "cd",
        "mkdir",
        "rmdir",
        "rm",
        "cp",
        "copy",
        "mv",
        "move",
        "touch",
        "find",
        "grep",
        "rg",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "diff",
        "tar",
        "unzip",
        "sh",
        "bash",
        "pwsh",
        "powershell",
        "cmd",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_limit": self.cpu_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "process_limit": self.process_limit,
            "execution_timeout_s": self.execution_timeout_s,
            "filesystem_scope": self.filesystem_scope,
            "network_mode": self.network_mode,
            "allowed_hosts": list(self.allowed_hosts),
            "artifact_limit": self.artifact_limit,
            "artifact_max_bytes": self.artifact_max_bytes,
            "output_max_bytes": self.output_max_bytes,
            "command_allowlist": list(self.command_allowlist),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SandboxPolicy:
        if not data:
            return cls()
        valid_fields = {
            "cpu_limit",
            "memory_limit_mb",
            "process_limit",
            "execution_timeout_s",
            "filesystem_scope",
            "network_mode",
            "allowed_hosts",
            "artifact_limit",
            "artifact_max_bytes",
            "output_max_bytes",
            "command_allowlist",
        }
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        if isinstance(filtered.get("allowed_hosts"), list):
            filtered["allowed_hosts"] = tuple(filtered["allowed_hosts"])
        if isinstance(filtered.get("command_allowlist"), list):
            filtered["command_allowlist"] = tuple(filtered["command_allowlist"])
        return cls(**filtered)

    def validate_bounds(self) -> None:
        if self.execution_timeout_s < 1 or self.execution_timeout_s > 600:
            raise PolicyViolation("execution_timeout_s must be within [1, 600]")
        if self.cpu_limit < 1 or self.cpu_limit > 16:
            raise PolicyViolation("cpu_limit must be within [1, 16]")
        if self.memory_limit_mb < 128 or self.memory_limit_mb > 8192:
            raise PolicyViolation("memory_limit_mb must be within [128, 8192]")
        if self.process_limit < 1 or self.process_limit > 512:
            raise PolicyViolation("process_limit must be within [1, 512]")
        if self.filesystem_scope != "sandbox":
            raise PolicyViolation("filesystem_scope must be 'sandbox'")
        if self.network_mode not in ("none", "allowlisted"):
            raise PolicyViolation("network_mode must be 'none' or 'allowlisted'")
        if self.network_mode == "allowlisted" and not self.allowed_hosts:
            raise PolicyViolation("network_mode 'allowlisted' requires allowed_hosts")
        if self.artifact_limit < 1 or self.artifact_limit > 500:
            raise PolicyViolation("artifact_limit must be within [1, 500]")
        if self.artifact_max_bytes < 1024 or self.artifact_max_bytes > 100 * 1024 * 1024:
            raise PolicyViolation("artifact_max_bytes must be within [1KB, 100MB]")

    def _basename(self, token: str) -> str:
        name = token.replace("\\", "/").split("/")[-1].strip().strip('"')
        name = name.lower()
        for ext in (".exe", ".cmd", ".bat", ".ps1", ".py", ".sh", ".jar"):
            if name.endswith(ext):
                name = name[: -len(ext)]
                break
        return name

    def check_command(self, command_line: str) -> str:
        """Validate a full command line against this policy.

        Returns the allowlisted program basename when permitted; raises
        PolicyViolation otherwise.
        """
        stripped = command_line.strip()
        if not stripped:
            raise PolicyViolation("empty command")
        lowered = stripped.lower()
        for pattern in DANGEROUS_ARG_PATTERNS:
            if pattern in lowered:
                raise PolicyViolation(f"dangerous command pattern blocked: {pattern}")
        if _WINDOWS_DRIVE_RE.search(lowered):
            raise PolicyViolation(
                f"absolute path in '{stripped}' escapes the sandbox filesystem scope"
            )
        if "\\\\" in stripped:
            raise PolicyViolation(f"UNC path in '{stripped}' escapes the sandbox filesystem scope")
        for frag in BLOCKED_PATH_FRAGMENTS:
            if frag in lowered:
                raise PolicyViolation(f"path fragment '{frag}' is outside the sandbox scope")

        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError:
            tokens = stripped.split()
        if not tokens:
            raise PolicyViolation("empty command")

        first = tokens[0]
        base = self._basename(first)
        if base in BLOCKED_COMMAND_BASENAMES:
            raise PolicyViolation(f"command '{base}' is blocked by policy")
        if base in NETWORK_COMMAND_BASENAMES and self.network_mode == "none":
            raise PolicyViolation(f"network command '{base}' blocked (network_mode=none)")

        allowed = {self._basename(entry) for entry in self.command_allowlist}
        if base not in allowed:
            raise PolicyViolation(f"command '{base}' is not in the sandbox command allowlist")

        for token in tokens[1:]:
            tl = token.lower()
            for frag in BLOCKED_PATH_FRAGMENTS:
                if frag in tl:
                    raise PolicyViolation(f"path fragment '{frag}' is outside the sandbox scope")
            if _WINDOWS_DRIVE_RE.match(token):
                raise PolicyViolation(
                    f"absolute path '{token}' escapes the sandbox filesystem scope"
                )
            if token.startswith("\\\\"):
                raise PolicyViolation(f"UNC path '{token}' escapes the sandbox filesystem scope")
            if tl.startswith("/") and _is_unix_path_escape(token):
                raise PolicyViolation(
                    f"absolute path '{token}' escapes the sandbox filesystem scope"
                )
            if "${" in token or (token.startswith("%") and token.endswith("%")):
                raise PolicyViolation("environment variable access is blocked")
        return base

    def check_shell_script(self, script: str) -> None:
        """Validate each line of a shell script against this policy."""
        for raw_line in script.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            self.check_command(line)

    def check_path_in_scope(self, requested: str, sandbox_root: str) -> bool:
        """Return True when `requested` resolves inside the sandbox root."""
        root = PurePosixPath(sandbox_root.replace("\\", "/"))
        candidate = PurePosixPath(requested.replace("\\", "/"))
        joined = root / candidate
        normalized = PurePosixPath(*[p for p in joined.parts if p not in (".",)])
        parts: list[str] = []
        for part in normalized.parts:
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        resolved = PurePosixPath(*parts) if parts else PurePosixPath("/")
        return str(resolved).startswith(str(root))

    def path_is_safe_relative(self, requested: str) -> bool:
        p = PurePosixPath(requested.replace("\\", "/"))
        if p.is_absolute():
            return False
        if PureWindowsPath(requested).drive:
            return False
        return all(part != ".." for part in p.parts)
