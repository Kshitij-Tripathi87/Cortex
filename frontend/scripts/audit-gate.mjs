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

// ── Accepted advisories ──────────────────────────────────────────────────────
// RC1 upgrades Next.js to a patched 15.5 release and overrides PostCSS and
// source-map-js to patched releases. No high/critical production advisories
// are accepted by this gate.
const ACCEPTED = new Map();

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
  if (ghsaOf(adv.via).some((id) => ACCEPTED.has(id))) acceptedByDependency.add(name);
}

const unaccepted = [];
const accepted = [];
for (const [name, adv] of Object.entries(vulns)) {
  const ids = ghsaOf(adv.via);
  const via = adv.via ?? [];
  const hasAdvisoryObjects = via.some((v) => typeof v === "object");
  // An entry is accepted iff (a) one of ITS OWN advisory ids is accepted,
  // or (b) it has no advisory objects of its own and every transitive
  // reference points at an accepted package. Anything else — including a
  // mix of unaccepted advisories and accepted references — is unaccepted.
  const isAccepted =
    ids.some((id) => ACCEPTED.has(id)) ||
    (!hasAdvisoryObjects &&
      via.length > 0 &&
      via.every((v) => typeof v === "string" && acceptedByDependency.has(v)));
  const entry = { name, severity: adv.severity, ids, title: via.find((v) => typeof v === "object")?.title ?? "" };
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
