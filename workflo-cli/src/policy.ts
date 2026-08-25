import { spawn } from "child_process";

export interface SandboxPolicy {
  cpu_limit: number;
  memory_limit_mb: number;
  process_limit: number;
  execution_timeout_s: number;
  filesystem_scope: string;
  network_mode: string;
  allowed_hosts: string[];
  artifact_limit: number;
  artifact_max_bytes: number;
  output_max_bytes: number;
  command_allowlist: string[];
}

export const DEFAULT_POLICY: SandboxPolicy = {
  cpu_limit: 2,
  memory_limit_mb: 1024,
  process_limit: 64,
  execution_timeout_s: 120,
  filesystem_scope: "sandbox",
  network_mode: "none",
  allowed_hosts: [],
  artifact_limit: 50,
  artifact_max_bytes: 10 * 1024 * 1024,
  output_max_bytes: 512 * 1024,
  command_allowlist: [
    "node", "npm", "npx", "python", "python3", "pytest", "pip", "go",
    "cargo", "git", "ls", "dir", "cat", "type", "echo", "pwd", "cd",
    "mkdir", "rmdir", "rm", "cp", "copy", "mv", "move", "touch", "find",
    "grep", "rg", "head", "tail", "wc", "sort", "uniq", "diff", "tar",
    "unzip", "sh", "bash", "pwsh", "powershell", "cmd",
  ],
};

const BLOCKED_BASENAMES = new Set([
  "docker", "docker-compose", "kubectl", "ssh", "scp", "sftp", "nc",
  "netcat", "telnet", "ftp", "sudo", "su", "doas", "runas", "reg",
  "regedit", "diskpart", "format", "shutdown", "taskkill", "tasklist",
]);

const NETWORK_BASENAMES = new Set([
  "curl", "wget", "fetch", "ping", "traceroute", "tracert", "nslookup",
  "dig", "arp", "ipconfig", "ifconfig", "netsh", "invoke-webrequest",
  "invoke-restmethod", "iwr",
]);

const BLOCKED_PATH_FRAGMENTS = [
  ".ssh", ".aws", ".gnupg", ".kube", ".docker", "id_rsa", "id_ed25519",
  ".npmrc", ".pypirc", ".netrc", "credentials",
];

const DANGEROUS_PATTERNS = [
  "rm -rf /", "rm -fr /", "mkfs", ":(){ :|:& };:", "> /dev/sda",
  "chmod -r 777 /", "del /f /s /q c:\\", "rd /s /q c:\\",
  "remove-item -path c:\\ -recurse", "format c:",
];

const SENSITIVE_UNIX_ROOTS = new Set([
  "etc", "root", "proc", "sys", "var", "usr", "home", "users", "boot",
  "dev", "opt", "sbin", "bin", "lib", "srv",
]);

export class PolicyViolation extends Error {}

function basename(token: string): string {
  let name = token.replace(/\\/g, "/").split("/").pop() ?? "";
  name = name.replace(/^"|"$/g, "").toLowerCase();
  return name.replace(/\.(exe|cmd|bat|ps1|py|sh|jar)$/i, "");
}

function isUnixPathEscape(token: string): boolean {
  const lower = token.toLowerCase();
  if (lower === "/") return true;
  if (lower.startsWith("/workspace")) return false;
  const segments = lower.split("/").filter(Boolean);
  if (segments.length === 0) return false;
  if (segments.length >= 2) return true;
  return SENSITIVE_UNIX_ROOTS.has(segments[0]);
}

export function checkCommand(
  commandLine: string,
  policy: SandboxPolicy,
): string {
  const stripped = commandLine.trim();
  if (!stripped) throw new PolicyViolation("empty command");
  const lowered = stripped.toLowerCase();

  for (const pattern of DANGEROUS_PATTERNS) {
    if (lowered.includes(pattern)) {
      throw new PolicyViolation(`dangerous command pattern blocked: ${pattern}`);
    }
  }
  if (/^[a-z]:[\\/]/i.test(stripped)) {
    throw new PolicyViolation(
      `absolute path in '${stripped}' escapes the sandbox filesystem scope`,
    );
  }
  if (stripped.includes("\\\\")) {
    throw new PolicyViolation(
      `UNC path in '${stripped}' escapes the sandbox filesystem scope`,
    );
  }
  for (const frag of BLOCKED_PATH_FRAGMENTS) {
    if (lowered.includes(frag)) {
      throw new PolicyViolation(
        `path fragment '${frag}' is outside the sandbox scope`,
      );
    }
  }

  const tokens = stripped.split(/\s+/).map((t) => t.replace(/^"|"$/g, ""));
  const base = basename(tokens[0]);
  if (BLOCKED_BASENAMES.has(base)) {
    throw new PolicyViolation(`command '${base}' is blocked by policy`);
  }
  if (NETWORK_BASENAMES.has(base) && policy.network_mode === "none") {
    throw new PolicyViolation(
      `network command '${base}' blocked (network_mode=none)`,
    );
  }
  const allowed = new Set(policy.command_allowlist.map(basename));
  if (!allowed.has(base)) {
    throw new PolicyViolation(
      `command '${base}' is not in the sandbox command allowlist`,
    );
  }
  for (const token of tokens.slice(1)) {
    const tl = token.toLowerCase();
    for (const frag of BLOCKED_PATH_FRAGMENTS) {
      if (tl.includes(frag)) {
        throw new PolicyViolation(
          `path fragment '${frag}' is outside the sandbox scope`,
        );
      }
    }
    if (/^[a-z]:[\\/]/i.test(token)) {
      throw new PolicyViolation(
        `absolute path '${token}' escapes the sandbox filesystem scope`,
      );
    }
    if (token.startsWith("\\\\")) {
      throw new PolicyViolation(
        `UNC path '${token}' escapes the sandbox filesystem scope`,
      );
    }
    if (tl.startsWith("/") && isUnixPathEscape(token)) {
      throw new PolicyViolation(
        `absolute path '${token}' escapes the sandbox filesystem scope`,
      );
    }
    if (token.includes("${") || /^%.*%$/.test(token)) {
      throw new PolicyViolation("environment variable access is blocked");
    }
  }
  return base;
}

export interface ExecutionResult {
  exit_code: number | null;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  duration_ms: number;
  truncated: boolean;
}

const ENV_ALLOWLIST = [
  "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR",
  "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
  "PROGRAMFILES", "LANG", "LC_ALL", "TZ",
];

export function sandboxEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const key of ENV_ALLOWLIST) {
    const value = process.env[key];
    if (value !== undefined) env[key] = value;
  }
  env.WORKFLO_SANDBOX = "1";
  return env;
}

export async function executeInSandbox(
  cwd: string,
  command: string,
  policy: SandboxPolicy,
  timeoutOverride?: number,
): Promise<ExecutionResult> {
  checkCommand(command, policy);
  const timeout =
    Math.min(timeoutOverride ?? policy.execution_timeout_s,
      policy.execution_timeout_s) * 1000;

  const startedAt = Date.now();
  return new Promise<ExecutionResult>((resolve) => {
    const child = spawn(command, {
      cwd,
      env: sandboxEnv(),
      shell: true,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });

    let stdout = Buffer.alloc(0);
    let stderr = Buffer.alloc(0);
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, timeout);

    child.stdout?.on("data", (chunk: Buffer) => {
      if (stdout.length < policy.output_max_bytes + 65536) {
        stdout = Buffer.concat([stdout, chunk]);
      }
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length < policy.output_max_bytes + 65536) {
        stderr = Buffer.concat([stderr, chunk]);
      }
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({
        exit_code: null,
        stdout: stdout.toString("utf8"),
        stderr: `${stderr.toString("utf8")}\n${err.message}`,
        timed_out: false,
        duration_ms: Date.now() - startedAt,
        truncated: false,
      });
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      const cap = policy.output_max_bytes;
      const truncated =
        stdout.length > cap || stderr.length > cap;
      resolve({
        exit_code: timedOut ? null : code,
        stdout: stdout.subarray(0, cap).toString("utf8"),
        stderr: stderr.subarray(0, cap).toString("utf8"),
        timed_out: timedOut,
        duration_ms: Date.now() - startedAt,
        truncated,
      });
    });
  });
}
