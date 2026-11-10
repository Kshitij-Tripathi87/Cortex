import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import {
  DEFAULT_POLICY,
  PolicyViolation,
  SandboxPolicy,
  executeInSandbox,
} from "./policy";

export interface LocalSandbox {
  id: string;
  root: string;
  workspace: string;
  artifacts: string;
  policy: SandboxPolicy;
}

const SKIP_DIRS = new Set([
  "node_modules", ".git", ".next", "dist", "build", ".venv", "__pycache__",
  ".workflo", "target", ".pytest_cache", ".mypy_cache", ".ruff_cache",
]);

export function newSandboxId(): string {
  return `sbx_${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
}

export interface SandboxIndexEntry {
  id: string;
  policy: SandboxPolicy;
}

export class LocalEngine {
  private sandboxes = new Map<string, LocalSandbox>();
  private destroyed = new Set<string>();

  constructor(private storageRoot: string) {
    fs.mkdirSync(storageRoot, { recursive: true });
    this.loadIndex();
  }

  private get indexPath(): string {
    return path.join(this.storageRoot, "index.json");
  }

  private loadIndex(): void {
    try {
      const raw = JSON.parse(fs.readFileSync(this.indexPath, "utf8")) as {
        active: SandboxIndexEntry[];
        destroyed: string[];
      };
      for (const entry of raw.active ?? []) {
        const root = path.join(this.storageRoot, entry.id);
        if (!fs.existsSync(root)) continue;
        this.sandboxes.set(entry.id, {
          id: entry.id,
          root,
          workspace: path.join(root, "workspace"),
          artifacts: path.join(root, "artifacts"),
          policy: entry.policy,
        });
      }
      this.destroyed = new Set(raw.destroyed ?? []);
    } catch {
      // no index yet — first run
    }
  }

  private saveIndex(): void {
    const active = [...this.sandboxes.values()].map((sbx) => ({
      id: sbx.id,
      policy: sbx.policy,
    }));
    fs.writeFileSync(
      this.indexPath,
      JSON.stringify({ active, destroyed: [...this.destroyed] }, null, 2),
    );
  }

  create(policy?: Partial<SandboxPolicy>): LocalSandbox {
    const merged: SandboxPolicy = { ...DEFAULT_POLICY, ...policy };
    const id = newSandboxId();
    const root = path.join(this.storageRoot, id);
    for (const sub of ["workspace", "artifacts", "tmp"]) {
      fs.mkdirSync(path.join(root, sub), { recursive: true });
    }
    const sandbox: LocalSandbox = {
      id,
      root,
      workspace: path.join(root, "workspace"),
      artifacts: path.join(root, "artifacts"),
      policy: merged,
    };
    this.sandboxes.set(id, sandbox);
    this.saveIndex();
    return sandbox;
  }

  get(id: string): LocalSandbox {
    if (this.destroyed.has(id)) {
      throw new PolicyViolation(`sandbox '${id}' was destroyed; reuse is blocked`);
    }
    const sandbox = this.sandboxes.get(id);
    if (!sandbox) throw new Error(`sandbox '${id}' not found`);
    return sandbox;
  }

  mountDirectory(sandbox: LocalSandbox, sourceDir: string): number {
    let count = 0;
    const walk = (dir: string, rel: string): void => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
          if (SKIP_DIRS.has(entry.name)) continue;
          walk(path.join(dir, entry.name), path.posix.join(rel, entry.name));
        } else if (entry.isFile()) {
          const targetRel = path.posix.join(rel, entry.name);
          const target = path.join(sandbox.workspace, targetRel);
          fs.mkdirSync(path.dirname(target), { recursive: true });
          fs.copyFileSync(path.join(dir, entry.name), target);
          count++;
        }
      }
    };
    walk(sourceDir, "");
    return count;
  }

  writeFile(sandbox: LocalSandbox, relPath: string, content: Buffer): void {
    assertSafeRelative(relPath);
    const target = path.resolve(sandbox.workspace, relPath);
    assertInside(sandbox.workspace, target);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }

  listFiles(sandbox: LocalSandbox): string[] {
    const out: string[] = [];
    const walk = (dir: string, rel: string): void => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const childRel = rel ? path.posix.join(rel, entry.name) : entry.name;
        if (entry.isFile()) out.push(childRel);
        else if (entry.isDirectory()) walk(path.join(dir, entry.name), childRel);
      }
    };
    walk(sandbox.workspace, "");
    return out.sort();
  }

  collectArtifacts(sandbox: LocalSandbox): Array<{ name: string; size: number }> {
    if (!fs.existsSync(sandbox.artifacts)) return [];
    return fs
      .readdirSync(sandbox.artifacts)
      .filter((name) =>
        fs.statSync(path.join(sandbox.artifacts, name)).isFile(),
      )
      .map((name) => ({
        name,
        size: fs.statSync(path.join(sandbox.artifacts, name)).size,
      }));
  }

  async execute(
    sandbox: LocalSandbox,
    command: string,
    timeoutOverride?: number,
  ): Promise<import("./policy").ExecutionResult> {
    return executeInSandbox(sandbox.workspace, command, sandbox.policy, timeoutOverride);
  }

  destroy(id: string): void {
    const sandbox = this.get(id);
    fs.rmSync(sandbox.root, { recursive: true, force: true });
    this.sandboxes.delete(id);
    this.destroyed.add(id);
    this.saveIndex();
  }
}

function assertSafeRelative(relPath: string): void {
  const normalized = relPath.replace(/\\/g, "/");
  if (path.isAbsolute(relPath) || /^[a-z]:[\\/]/i.test(relPath)) {
    throw new PolicyViolation(
      `path '${relPath}' escapes the sandbox filesystem scope`,
    );
  }
  if (normalized.startsWith("/")) {
    throw new PolicyViolation(
      `path '${relPath}' escapes the sandbox filesystem scope`,
    );
  }
  for (const part of normalized.split("/")) {
    if (part === "..") {
      throw new PolicyViolation(
        `path '${relPath}' escapes the sandbox filesystem scope`,
      );
    }
  }
}

function assertInside(root: string, target: string): void {
  const resolvedRoot = path.resolve(root);
  if (!path.resolve(target).startsWith(resolvedRoot + path.sep) &&
      path.resolve(target) !== resolvedRoot) {
    throw new PolicyViolation("path escapes the sandbox filesystem scope");
  }
}
