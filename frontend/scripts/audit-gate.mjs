#!/usr/bin/env node
/**
 * Production dependency audit gate with an explicit advisory ratchet.
 *
 * Why this exists: the plain `npm audit --audit-level=critical` gate can
 * never pass while the frontend is on Next 14 — upstream publishes
 * advisories whose only fix is next@16 (semver-major) — and new advisory
 * publications regularly flip the gate red overnight (registry drift;
 * observed twice during the 2026-09 CI-green initiative on PR #1).
 *
 * Contract (same philosophy as the mypy ratchet in backend/pyproject.toml):
 *   * Every ADVISORY in ACCEPTED below is a documented, deliberate
 *     acceptance with a removal follow-up. Entries may only be ADDED
 *     with a justification comment and a tracked follow-up; they must
 *     be DELETED when the fix ships.
 *   * Any production vulnerability (high or critical) whose advisory is
 *     NOT in ACCEPTED fails the gate — new advisories still block CI.
 *   * Lower severities are reported as notices, never gated.
 *
 * Usage: node scripts/audit-gate.mjs   (from the frontend directory)
 */

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// ── Accepted advisories (ratchet) ────────────────────────────────────────────
// Removal follow-up for BOTH entries: the Next.js 14 → 16 migration PR
// (both are fixed in next 16.3.4; no backport exists for the 14.x line —
// the 14.2.35 security patch release already cleared the earlier batch).
const ACCEPTED = new Map([
  [
    "GHSA-9g9p-9gw9-jx7f",
    "next [critical] self-hosted Next.js DoS via Image Optimizer " +
      "remotePatterns. Not exploitable in the current deployment (no " +
      "remote image patterns configured). Fix: next 16.3.4 (semver-major).",
  ],
  [
    "GHSA-qx2v-qp2m-jg93",
    "postcss [high] XSS via unescaped </style> in stringify output, via " +
      "the postcss version Next 14 pins. Build-time tooling exposure. " +
      "Fix: next 16.3.4 (semver-major).",
  ],
]);

const GATE_SEVERITIES = new Set(["high", "critical"]);

// ── Run npm audit ────────────────────────────────────────────────────────────
let raw;
try {
  raw = execFileSync("npm", ["audit", "--json", "--omit=dev"], {
    cwd: frontendDir,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
} catch (err) {
  // npm audit exits non-zero when it finds vulnerabilities; the JSON is
  // still emitted on stdout.
  raw = err.stdout;
}

let audit;
try {
  audit = JSON.parse(raw);
} catch {
  console.log(`::error title=npm-audit unparsable::${String(raw).slice(0, 500)}`);
  process.exit(1);
}

// ── Classify ─────────────────────────────────────────────────────────────────
const vulns = audit.vulnerabilities ?? {};

const ghsaOf = (via) =>
  (via ?? [])
    .filter((v) => typeof v === "object" && v.url)
    .map((v) => (String(v.url).match(/(GHSA-[a-z0-9-]+)$/i) || [])[1])
    .filter(Boolean);

const acceptedByDependency = new Set();
for (const [name, adv] of Object.entries(vulns)) {
  const ids = ghsaOf(adv.via);
  if (ids.some((id) => ACCEPTED.has(id))) acceptedByDependency.add(name);
}

const unaccepted = [];
const accepted = [];
for (const [name, adv] of Object.entries(vulns)) {
  const ids = ghsaOf(adv.via);
  const isAccepted =
    ids.some((id) => ACCEPTED.has(id)) ||
    // pure transitive entry: every string via points at an accepted package
    ((adv.via ?? []).length > 0 &&
      (adv.via ?? []).every((v) => typeof v === "string" ? acceptedByDependency.has(v) : true));
  const entry = { name, severity: adv.severity, ids, title: (adv.via ?? []).find((v) => typeof v === "object")?.title ?? "" };
  if (isAccepted) accepted.push(entry);
  else unaccepted.push(entry);
}

// ── Report ───────────────────────────────────────────────────────────────────
const counts = audit.metadata?.vulnerabilities ?? {};
console.log(`::notice title=npm-audit summary::${JSON.stringify(counts)}`);
for (const a of accepted) {
  const id = a.ids.find((id) => ACCEPTED.has(id));
  console.log(
    `::notice title=npm-audit accepted ${a.name} [${a.severity}] (${id})::${ACCEPTED.get(id) ?? ""}`
  );
}

const blocking = unaccepted.filter((u) => GATE_SEVERITIES.has(u.severity));
for (const u of unaccepted) {
  const gated = GATE_SEVERITIES.has(u.severity);
  const level = gated ? "error" : "notice";
  console.log(
    `::${level} title=npm-audit ${u.name} [${u.severity}]::${u.title} ids=${u.ids.join(",") || "n/a"} fixAvailable=${JSON.stringify(vulns[u.name]?.fixAvailable)}`
  );
}

if (blocking.length > 0) {
  console.error(
    `npm-audit gate: ${blocking.length} unaccepted high/critical production vulnerabilit${blocking.length === 1 ? "y" : "ies"}: ${blocking.map((b) => b.name).join(", ")}`
  );
  process.exit(1);
}

console.log("npm-audit gate: no unaccepted high/critical production vulnerabilities.");
