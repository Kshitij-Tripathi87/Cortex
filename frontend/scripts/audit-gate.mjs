#!/usr/bin/env node
/**
 * Dependency audit gate.
 *
 *   node scripts/audit-gate.mjs           production dependencies:
 *                                         fails on any high or critical advisory
 *   node scripts/audit-gate.mjs --tools   every dependency, build, lint and test
 *                                         tools included: fails on any critical
 *                                         advisory, reports the rest
 *
 * Run from the frontend directory, after `npm ci`.
 *
 * What counts as production
 * -------------------------
 * `dependencies` in package.json are what the running site needs. The image
 * ships Next's standalone output, which holds those packages and nothing else.
 * Tailwind, PostCSS and Autoprefixer compile the style sheet during
 * `next build` and are not in that output, so they are `devDependencies`,
 * together with the lint and test tools. (They used to be listed under
 * `dependencies`; an advisory in a glob library that only Tailwind uses then
 * failed the production gate, and with it the image build on main.)
 *
 * Why two thresholds
 * ------------------
 * A flaw in a production dependency can be reached by anyone who can reach
 * the site, so high and critical both block. Build and test tools run on a
 * developer's or the CI machine over the repository's own files; there a
 * critical advisory (code execution, typically) still blocks, while a high
 * one is reported so that it gets fixed in the normal course of updates.
 *
 * Exemptions
 * ----------
 * ACCEPTED holds advisories that are deliberately not blocking, each with its
 * reason and what removes it. It is empty. Add an entry only with both, and
 * delete it when the fix ships. An exemption applies to one advisory id; a new
 * advisory against the same package still blocks.
 *
 * NOTES explains advisories that are reported but do not block, so the log
 * says why they are still there.
 */

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const TOOLS = process.argv.includes("--tools");
const SCOPE = TOOLS
  ? {
      name: "build and test tools",
      npmArgs: ["audit", "--json"],
      gate: new Set(["critical"]),
      gateWords: "critical",
    }
  : {
      name: "production",
      npmArgs: ["audit", "--json", "--omit=dev"],
      gate: new Set(["high", "critical"]),
      gateWords: "high or critical",
    };

// advisory id -> why it is accepted and what removes the entry
const ACCEPTED = new Map();

// advisory id -> why it is still reported
const NOTES = new Map([
  [
    "GHSA-fc5q-39xc-vjpf",
    "picomatch: no fixed release exists (every version up to the latest, 4.0.7, is affected). " +
      "Reached only through build, lint and test tools (Tailwind 3, ESLint, Vite), which match " +
      "file patterns written in this repository; nothing a visitor sends reaches it. Goes away " +
      "when picomatch publishes a fix or these tools stop using it (Tailwind 4 does not).",
  ],
]);

// -- Run npm audit -----------------------------------------------------------
// The advisory endpoint of the registry fails now and then. Ask up to three
// times; if no answer arrives the gate fails, because an unanswered question
// is not a pass.
function runAudit() {
  let raw;
  try {
    raw = execFileSync("npm", SCOPE.npmArgs, {
      cwd: frontendDir,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch (err) {
    // npm audit exits non-zero when it finds vulnerabilities; the JSON is
    // still emitted on stdout.
    raw = err.stdout;
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.vulnerabilities === "object" && !parsed.error) return { audit: parsed };
    return { problem: JSON.stringify(parsed.error ?? parsed).slice(0, 500) };
  } catch {
    return { problem: String(raw).slice(0, 500) };
  }
}

const ATTEMPTS = 3;
// The wait grows with each attempt. (The tests shorten it.)
const RETRY_MS = Number(process.env.AUDIT_GATE_RETRY_MS ?? 5000);
let audit;
let problem = "";
for (let attempt = 1; attempt <= ATTEMPTS && !audit; attempt += 1) {
  const result = runAudit();
  audit = result.audit;
  problem = result.problem ?? "";
  if (!audit && attempt < ATTEMPTS) {
    console.log(`::notice title=npm-audit retry::attempt ${attempt} got no usable answer: ${problem}`);
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, RETRY_MS * attempt);
  }
}
if (!audit) {
  console.log(`::error title=npm-audit unanswered::no usable answer after ${ATTEMPTS} attempts: ${problem}`);
  process.exit(1);
}

// -- Classify ----------------------------------------------------------------
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
  // reference points at an accepted package. Anything else, including a
  // mix of unaccepted advisories and accepted references, is unaccepted.
  const isAccepted =
    ids.some((id) => ACCEPTED.has(id)) ||
    (!hasAdvisoryObjects &&
      via.length > 0 &&
      via.every((v) => typeof v === "string" && acceptedByDependency.has(v)));
  const entry = {
    name,
    severity: adv.severity,
    ids,
    own: hasAdvisoryObjects,
    title: via.find((v) => typeof v === "object")?.title ?? "",
  };
  if (isAccepted) accepted.push(entry);
  else unaccepted.push(entry);
}

// -- Report ------------------------------------------------------------------
const counts = audit.metadata?.vulnerabilities ?? {};
console.log(`::notice title=npm-audit ${SCOPE.name}::${JSON.stringify(counts)}`);
for (const a of accepted) {
  const id = a.ids.find((id) => ACCEPTED.has(id));
  console.log(
    `::notice title=npm-audit accepted ${a.name} [${a.severity}] (${id})::${ACCEPTED.get(id) ?? ""}`
  );
}

const blocking = unaccepted.filter((u) => SCOPE.gate.has(u.severity));

// A package with an advisory of its own gets a line. Packages that are listed
// only because they depend on one are summed up in a single line below.
const dependents = [];
for (const u of unaccepted) {
  if (!u.own) {
    dependents.push(u.name);
    continue;
  }
  const gated = SCOPE.gate.has(u.severity);
  const level = gated ? "error" : u.severity === "high" || u.severity === "critical" ? "warning" : "notice";
  const note = u.ids.map((id) => NOTES.get(id)).filter(Boolean).join(" ");
  console.log(
    `::${level} title=npm-audit ${u.name} [${u.severity}]::${u.title} ids=${u.ids.join(",") || "n/a"} fixAvailable=${JSON.stringify(vulns[u.name]?.fixAvailable)}${note ? ` -- ${note}` : ""}`
  );
}
if (dependents.length > 0) {
  console.log(
    `::notice title=npm-audit dependents::listed only because they depend on a package above: ${dependents.sort().join(", ")}`
  );
}

if (blocking.length > 0) {
  console.error(
    `npm-audit gate (${SCOPE.name}): ${blocking.length} ${SCOPE.gateWords} entr${blocking.length === 1 ? "y" : "ies"} not accepted: ${blocking.map((b) => b.name).join(", ")}`
  );
  process.exit(1);
}

console.log(`npm-audit gate (${SCOPE.name}): no ${SCOPE.gateWords} advisory.`);
