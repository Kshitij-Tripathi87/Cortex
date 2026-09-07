export interface PlanStep {
  index: number;
  action: string;
  detail: string;
}

const FAIL_HINTS: Array<[string, string]> = [
  ["assertionerror", "assertion mismatch — compare expected vs actual payload"],
  ["expect(", "expectation failed — inspect the diff above it"],
  ["modulenotfounderror", "missing dependency — install inside the sandbox image"],
  ["cannot find module", "missing dependency — install inside the sandbox image"],
  ["syntaxerror", "syntax error — check the reported file and line"],
  ["typeerror", "type error — inspect null/undefined access at reported location"],
];

function add(
  steps: PlanStep[],
  action: string,
  detail: string,
): void {
  steps.push({ index: steps.length, action, detail });
}

export function buildPlan(intent: string, discovery?: { frameworks: string[] }): PlanStep[] {
  const text = (intent || "").toLowerCase();
  const steps: PlanStep[] = [];

  add(steps, "inspect_project", "read manifests and source layout inside the sandbox");
  if (discovery && discovery.frameworks.length > 0) {
    add(steps, "discover_tests", `test surfaces found: ${discovery.frameworks.join(", ")}`);
  } else {
    add(steps, "discover_tests", "scan for test suites, flows, and API contracts");
  }
  if (/regression|all|full|suite/.test(text)) {
    add(steps, "run_suite", "execute the full regression suite in the sandbox");
  }
  if (text.includes("checkout")) {
    add(steps, "run_target", "run checkout-related tests only");
  }
  if (/why|failing|failure|broken|diagnose|find/.test(text)) {
    add(steps, "inspect_failure", "capture stdout/stderr and exit codes of failing targets");
    add(steps, "reproduce", "re-run the failing target once to confirm determinism");
  }
  if (/api|contract|schema/.test(text)) {
    add(steps, "check_contracts", "validate API response schemas against expectations");
  }
  add(steps, "collect_artifacts", "persist logs, reports, and dumps as artifacts");
  add(steps, "report", "emit structured run report with findings");
  return steps;
}

export interface Finding {
  severity: string;
  title: string;
  evidence: string;
  suggestion: string;
}

export interface DiagnoseInput {
  command?: string;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  timed_out?: boolean;
  duration_ms?: number;
}

function firstFailureLines(output: string, maxLines = 8): string {
  const lines = output.split("\n").filter((l) => l.trim());
  const interesting = lines.filter((l) =>
    /fail|error|assert|expect|\u2717/i.test(l),
  );
  return (interesting.length ? interesting : lines).slice(-maxLines).join("\n");
}

function grepLine(output: string, needles: string[]): string {
  for (const line of output.split("\n")) {
    if (needles.some((n) => line.toLowerCase().includes(n.toLowerCase()))) {
      return line;
    }
  }
  return "";
}

export function diagnose(result: DiagnoseInput): {
  status: string;
  findings: Finding[];
} {
  const findings: Finding[] = [];
  const combined = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;

  if (result.timed_out) {
    findings.push({
      severity: "high",
      title: "execution timed out",
      evidence: `command '${result.command}' exceeded the policy timeout`,
      suggestion: "raise execution_timeout_s in the sandbox policy or fix the hang",
    });
  } else if ((result.exit_code ?? 0) !== 0 && result.exit_code !== null) {
    let suggestion = "inspect stderr and failing test output";
    const lowered = combined.toLowerCase();
    for (const [hint, s] of FAIL_HINTS) {
      if (lowered.includes(hint)) {
        suggestion = s;
        break;
      }
    }
    findings.push({
      severity: "high",
      title: `command failed with exit code ${result.exit_code}`,
      evidence: firstFailureLines(combined),
      suggestion,
    });
  }

  if (/econnrefused|connection refused/i.test(combined)) {
    findings.push({
      severity: "medium",
      title: "network dependency unreachable",
      evidence: grepLine(combined, ["ECONNREFUSED", "connection refused"]),
      suggestion: "sandbox network_mode is 'none'; stub external services",
    });
  }

  const failedMatch = combined.match(/(\d+) (?:tests? )?failed/i);
  if (failedMatch) {
    findings.push({
      severity: "critical",
      title: `${failedMatch[1]} test case(s) failed`,
      evidence: firstFailureLines(combined),
      suggestion: "see failing target output; reproduce individually before fixing",
    });
  }

  if (findings.length === 0 && result.exit_code === 0) {
    findings.push({
      severity: "info",
      title: "execution succeeded",
      evidence: `'${result.command}' exited 0 in ${result.duration_ms ?? 0}ms`,
      suggestion: "no action required",
    });
  }

  return {
    status:
      result.exit_code === 0 && !result.timed_out ? "healthy" : "degraded",
    findings,
  };
}
