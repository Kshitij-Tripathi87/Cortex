/**
 * The dependency gate decides whether an image may be built, so its decisions
 * are tested: each case runs the real script against a stand-in `npm` that
 * prints a prepared `npm audit --json` answer.
 */
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const SCRIPT = path.resolve(__dirname, "audit-gate.mjs");

type Via = string | { title: string; url: string; severity: string; range: string };

function vulnerable(name: string, severity: string, via: Via[]) {
  return { name, severity, isDirect: false, via, effects: [], range: "*", nodes: [], fixAvailable: false };
}

function advisory(id: string, severity: string, title: string): Via {
  return { title, url: `https://github.com/advisories/${id}`, severity, range: "*" };
}

function answer(entries: ReturnType<typeof vulnerable>[]) {
  const counts = { info: 0, low: 0, moderate: 0, high: 0, critical: 0, total: entries.length };
  for (const entry of entries) counts[entry.severity as "high"] += 1;
  return JSON.stringify({
    auditReportVersion: 2,
    vulnerabilities: Object.fromEntries(entries.map((entry) => [entry.name, entry])),
    metadata: { vulnerabilities: counts },
  });
}

const cleanups: string[] = [];
afterEach(() => {
  for (const dir of cleanups.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** Run the gate with an `npm` that prints `stdout` and records its arguments. */
function runGate(stdout: string, args: string[] = []) {
  const dir = mkdtempSync(path.join(os.tmpdir(), "audit-gate-"));
  cleanups.push(dir);
  const answerFile = path.join(dir, "answer.json");
  const argsFile = path.join(dir, "args.txt");
  writeFileSync(answerFile, stdout);
  const fake = path.join(dir, "npm");
  writeFileSync(fake, `#!/bin/sh\necho "$@" >> "${argsFile}"\ncat "${answerFile}"\nexit 1\n`);
  chmodSync(fake, 0o755);
  const result = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: "utf8",
    env: { ...process.env, PATH: `${dir}${path.delimiter}${process.env.PATH}`, AUDIT_GATE_RETRY_MS: "5" },
  });
  const npmCalls = existsSync(argsFile) ? readFileSync(argsFile, "utf8").trim().split("\n") : [];
  return { status: result.status, output: `${result.stdout}${result.stderr}`, npmCalls };
}

const REDOS = advisory("GHSA-aaaa-bbbb-cccc", "high", "Pattern matching can be made very slow");
const RCE = advisory("GHSA-dddd-eeee-ffff", "critical", "Code execution through worker options");

describe("production scope", () => {
  it("passes when nothing is reported, and asks only about production dependencies", () => {
    const run = runGate(answer([]));
    expect(run.status).toBe(0);
    expect(run.output).toContain("npm-audit gate (production): no high or critical advisory.");
    expect(run.npmCalls).toEqual(["audit --json --omit=dev"]);
  });

  it("fails on a high advisory and names every package it reaches", () => {
    const run = runGate(
      answer([vulnerable("matcher", "high", [REDOS]), vulnerable("watcher", "high", ["matcher"])]),
    );
    expect(run.status).toBe(1);
    expect(run.output).toContain("::error title=npm-audit matcher [high]::Pattern matching can be made very slow");
    expect(run.output).toContain("GHSA-aaaa-bbbb-cccc");
    expect(run.output).toContain("2 high or critical entries not accepted: matcher, watcher");
  });

  it("fails on a critical advisory", () => {
    const run = runGate(answer([vulnerable("pool", "critical", [RCE])]));
    expect(run.status).toBe(1);
    expect(run.output).toContain("1 high or critical entry not accepted: pool");
  });

  it("reports a moderate advisory without failing", () => {
    const run = runGate(
      answer([vulnerable("parser", "moderate", [advisory("GHSA-1111-2222-3333", "moderate", "Slow parsing")])]),
    );
    expect(run.status).toBe(0);
    expect(run.output).toContain("::notice title=npm-audit parser [moderate]::Slow parsing");
  });
});

describe("tools scope", () => {
  it("asks about every dependency", () => {
    const run = runGate(answer([]), ["--tools"]);
    expect(run.status).toBe(0);
    expect(run.npmCalls).toEqual(["audit --json"]);
    expect(run.output).toContain("npm-audit gate (build and test tools): no critical advisory.");
  });

  it("reports a high advisory as a warning and passes", () => {
    const run = runGate(
      answer([vulnerable("matcher", "high", [REDOS]), vulnerable("watcher", "high", ["matcher"])]),
      ["--tools"],
    );
    expect(run.status).toBe(0);
    expect(run.output).toContain("::warning title=npm-audit matcher [high]::");
    // Packages listed only because they depend on it are summed up in one line.
    expect(run.output).toContain("listed only because they depend on a package above: watcher");
  });

  it("fails on a critical advisory", () => {
    const run = runGate(answer([vulnerable("pool", "critical", [RCE])]), ["--tools"]);
    expect(run.status).toBe(1);
    expect(run.output).toContain("::error title=npm-audit pool [critical]::Code execution through worker options");
    expect(run.output).toContain("1 critical entry not accepted: pool");
  });
});

describe("an audit that could not be answered", () => {
  it("fails after three attempts when the registry returns an error", () => {
    const run = runGate(JSON.stringify({ message: "request failed", error: { code: "ENOTFOUND", summary: "registry unreachable" } }));
    expect(run.status).toBe(1);
    expect(run.npmCalls).toHaveLength(3);
    expect(run.output).toContain("no usable answer after 3 attempts");
    expect(run.output).toContain("registry unreachable");
  });

  it("fails when the output is not JSON", () => {
    const run = runGate("npm ERR! something broke");
    expect(run.status).toBe(1);
    expect(run.output).toContain("no usable answer after 3 attempts");
  });
});
