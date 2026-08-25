#!/usr/bin/env node
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { api, probeHealth, streamRunEvents } from "./api";
import { diagnose, buildPlan } from "./agent";
import {
  credentialsPath,
  defaultConfig,
  loadConfig,
  saveGlobalConfig,
  saveProjectConfig,
  WorkfloConfig,
} from "./config";
import { discoverSurfaces } from "./discovery";
import { LocalEngine } from "./local-engine";
import { banner, bold, cyan, dim, fail, gray, green, info, line, ok, red, VERSION, warn, yellow } from "./render";
import { PolicyViolation } from "./policy";

const PROJECT = process.cwd();

function engine(): LocalEngine {
  const root =
    process.env.WORKFLO_ROOT || path.join(PROJECT, ".workflo", "sandboxes");
  return new LocalEngine(root);
}

function isRemote(config: WorkfloConfig): boolean {
  return config.api_url.startsWith("http");
}

function printHelp(): void {
  console.log(`
${bold("workflo")} ${gray(VERSION)} — Autonomous QA & Runtime Agent

${bold("Usage:")} workflo <command> [args]

${bold("Commands:")}
  init                    Initialize workflo in the current project
  doctor                  Check environment, config, and API connectivity
  login --token <tok>     Store an API token
  config get|set          Read or write configuration
  run [intent]            Discover -> plan -> sandbox -> execute -> report
  test [target]           Alias of run focused on tests
  agent "<intent>"        Build and display an execution plan for an intent
  sandbox create|inspect|exec|files|destroy
  artifacts list|fetch    List or fetch run/sandbox artifacts
  report [runId]          Print latest (or given) run report
  version                 Print version
  help                    This message

Running ${bold("workflo")} with no command starts an interactive REPL.
`);
}

async function cmdInit(config: WorkfloConfig): Promise<number> {
  saveProjectConfig(PROJECT, { workspace_id: config.workspace_id });
  fs.mkdirSync(path.join(PROJECT, ".workflo"), { recursive: true });
  ok(`initialized workflo in ${PROJECT}`);
  line("config file", ".workflo.json");
  line("workspace_id", config.workspace_id);
  line("api_url", config.api_url);
  const reachable = await probeHealth(config);
  if (reachable) ok(`control plane reachable at ${config.api_url}`);
  else warn(`control plane not reachable — local mode will be used`);
  return 0;
}

interface DoctorCheck {
  name: string;
  pass: boolean;
  detail: string;
}

async function cmdDoctor(config: WorkfloConfig): Promise<number> {
  console.log();
  info("Checking environment");
  const checks: DoctorCheck[] = [];
  checks.push({
    name: "node",
    pass: parseInt(process.versions.node.split(".")[0], 10) >= 18,
    detail: `v${process.versions.node}`,
  });
  checks.push({
    name: "workspace",
    pass: fs.existsSync(PROJECT),
    detail: PROJECT,
  });
  const hasProject = fs.existsSync(path.join(PROJECT, ".workflo.json"));
  checks.push({
    name: "project config",
    pass: true,
    detail: hasProject ? ".workflo.json found" : "not initialized (run `workflo init`)",
  });

  info("Probing control plane");
  let remote = false;
  try {
    remote = await probeHealth(config);
  } catch {
    remote = false;
  }
  checks.push({
    name: "api",
    pass: true,
    detail: remote
      ? `connected at ${config.api_url}`
      : `${config.api_url} unreachable — using local embedded runtime`,
  });

  let failures = 0;
  for (const check of checks) {
    if (!check.pass && check.name !== "api") failures++;
    if (check.pass) ok(`${check.name.padEnd(16)}${check.detail}`);
    else fail(`${check.name.padEnd(16)}${check.detail}`);
  }

  info("Sandbox engine self-test");
  try {
    const eng = engine();
    const sbx = eng.create({ execution_timeout_s: 30 });
    const result = await eng.execute(sbx, "echo workflo-doctor-ok");
    eng.destroy(sbx.id);
    if (result.stdout.includes("workflo-doctor-ok")) {
      ok("sandbox echo test passed".padEnd(32));
    } else {
      fail("sandbox echo test produced unexpected output");
      failures++;
    }
  } catch (exc) {
    fail(`sandbox self-test failed: ${(exc as Error).message}`);
    failures++;
  }

  console.log();
  if (failures === 0) {
    ok(`doctor complete — all critical checks passed (${remote ? "remote" : "local"} mode)`);
    return 0;
  }
  fail(`doctor found ${failures} problem(s)`);
  return 1;
}

async function cmdLogin(args: string[], config: WorkfloConfig): Promise<number> {
  const idx = args.indexOf("--token");
  const token = idx >= 0 ? args[idx + 1] : undefined;
  if (!token) {
    fail("usage: workflo login --token <token>");
    return 2;
  }
  const next = { ...defaultConfig(), ...config, token };
  saveGlobalConfig(next);
  ok(`credentials stored at ${credentialsPath()}`);
  return 0;
}

async function cmdConfig(args: string[], projectDir: string): Promise<number> {
  const sub = args[0];
  if (sub === "get") {
    const cfg = loadConfig(projectDir);
    for (const [key, value] of Object.entries(cfg)) {
      let shown: string = String(value);
      if (key === "token" && value) shown = "***redacted***";
      line(key, shown);
    }
    return 0;
  }
  if (sub === "set") {
    const [key, ...rest] = args.slice(1);
    const value = rest.join(" ");
    if (!key || !value) {
      fail("usage: workflo config set <key> <value>");
      return 2;
    }
    saveProjectConfig(projectDir, { [key]: value } as Partial<WorkfloConfig>);
    ok(`${key} = ${key === "token" ? "***" : value}`);
    return 0;
  }
  fail("usage: workflo config get|set");
  return 2;
}

function renderFindings(findings: ReturnType<typeof diagnose>["findings"]): void {
  if (findings.length === 0) return;
  console.log();
  console.log(bold("Agent findings:"));
  for (const finding of findings) {
    const icon =
      finding.severity === "info"
        ? green("\u2713")
        : finding.severity === "critical"
          ? red("\u2717")
          : yellow("!");
    console.log(`\n  ${icon} [${finding.severity}] ${finding.title}`);
    if (finding.evidence) {
      for (const evidenceLine of finding.evidence.split("\n").slice(0, 6)) {
        console.log(gray(`      ${evidenceLine}`));
      }
    }
    console.log(dim(`      fix: ${finding.suggestion}`));
  }
}

async function runLocal(intent: string): Promise<number> {
  const eng = engine();
  const discovery = discoverSurfaces(PROJECT);

  console.log();
  info("Inspecting project");
  line("frameworks", discovery.frameworks.join(", ") || "none detected");
  line("test suites", String(discovery.suites.length));
  if (discovery.suites.length > 0) {
    for (const suite of discovery.suites.slice(0, 8)) {
      console.log(gray(`    - ${suite}`));
    }
  }

  info("Building execution plan");
  const steps = buildPlan(intent || "run regression suite", discovery);
  for (const step of steps) {
    console.log(gray(`    ${step.index + 1}. [${step.action}] ${step.detail}`));
  }

  info("Creating sandbox");
  const policy = loadConfig(PROJECT).sandbox_policy as never | undefined;
  const sbx = eng.create(policy);
  ok(`sandbox created: ${cyan(sbx.id)}`);

  info("Mounting project (controlled copy)");
  const mounted = eng.mountDirectory(sbx, PROJECT);
  line("files mounted", String(mounted));

  const command = intent && !/regression|suite|all/i.test(intent)
    ? `npm test --silent ${intent}`
    : discovery.suggested_command;

  console.log();
  info(`Executing: ${command}`);
  const started = Date.now();
  const result = await eng.execute(sbx, command);
  const duration = Date.now() - started;

  const outputTail = (result.stdout + result.stderr).trim().split("\n").slice(-12);
  for (const outLine of outputTail) {
    console.log(gray(`    ${outLine}`));
  }

  const diagnosis = diagnose({
    command,
    exit_code: result.exit_code,
    stdout: result.stdout,
    stderr: result.stderr,
    timed_out: result.timed_out,
    duration_ms: result.duration_ms,
  });
  renderFindings(diagnosis.findings);

  const reportName = `report-${Date.now()}.md`;
  fs.writeFileSync(
    path.join(sbx.artifacts, reportName),
    [
      `# Workflo Report`,
      ``,
      `- intent: ${intent || "(none)"}`,
      `- status: **${diagnosis.status}**`,
      `- sandbox: \`${sbx.id}\``,
      `- duration: ${duration}ms`,
      `- exit code: ${result.exit_code}`,
      ``,
      `## Findings`,
      ...diagnosis.findings.map(
        (fnd) => `\n### [${fnd.severity}] ${fnd.title}\n\n${fnd.evidence}\n\nFix: ${fnd.suggestion}\n`,
      ),
    ].join("\n"),
  );

  console.log();
  line("exit code", String(result.exit_code ?? (result.timed_out ? "timeout" : "?")));
  line("duration", `${duration}ms`);
  line("artifacts", `${eng.collectArtifacts(sbx).length + 1} collected`);
  line("report", `.workflo/sandboxes/${sbx.id}/artifacts/${reportName}`);

  const failed = result.exit_code !== 0 || result.timed_out;
  if (failed) fail("run finished with failures");
  else ok("run finished successfully");

  eng.destroy(sbx.id);
  info(`sandbox destroyed: ${dim(sbx.id)}`);
  return failed ? 1 : 0;
}

async function runRemote(config: WorkfloConfig, intent: string): Promise<number> {
  const discovery = discoverSurfaces(PROJECT);
  const files: Array<{ path: string; content_base64: string }> = [];

  const collect = (dir: string, rel: string): void => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const childRel = rel ? path.posix.join(rel, entry.name) : entry.name;
      if (entry.isDirectory()) {
        if (["node_modules", ".git", ".next", ".workflo", ".venv"].includes(entry.name)) continue;
        collect(full, childRel);
      } else if (entry.isFile() && files.length < 200) {
        const sizeBytes = fs.statSync(full).size;
        if (sizeBytes <= 1024 * 1024) {
          files.push({
            path: childRel,
            content_base64: fs.readFileSync(full).toString("base64"),
          });
        }
      }
    }
  };
  collect(PROJECT, "");

  info(`Uploading ${files.length} file(s) to control plane`);
  const response = await api.createRun(config, {
    workspace_id: config.workspace_id,
    name: "cli-run",
    intent: intent || "run regression suite",
    files,
    command: discovery.suggested_command,
  });

  if (response.status !== 201) {
    fail(`run creation failed (${response.status})`);
    return 1;
  }

  const run = response.data;
  line("run id", run.id);
  line("sandbox", run.sandbox_id ?? "?");
  console.log();
  info("Streaming events (SSE)");

  const done = streamRunEvents(config, run.id, (type, message) => {
    const glyph =
      type === "failed" || type === "finding"
        ? red("\u2717")
        : type === "completed" && run.status === "passed"
          ? green("\u2713")
          : type === "executed" || type === "reported" || type === "completed"
            ? green("\u25c9")
            : cyan("\u25c9");
    console.log(`  ${glyph} ${type.padEnd(10)} ${message}`);
  }).catch(() => undefined);

  let waited = 0;
  while (waited < 300000) {
    const poll = await api.getRun(config, run.id);
    if (poll.status === 200 && ["passed", "failed"].includes(poll.data.status)) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    waited += 1500;
  }
  await done;

  const finalRun = await api.getRun(config, run.id);
  const record = finalRun.data;
  if (record.findings) renderFindings(record.findings);

  console.log();
  line("status", record.status);
  let artifactCount = 0;
  try {
    const artifactsResp = await api.runArtifacts(config, run.id);
    if (artifactsResp.status === 200) {
      artifactCount = artifactsResp.data.artifacts.length;
      for (const artifact of artifactsResp.data.artifacts) {
        console.log(gray(`    artifact: ${artifact.name} (${artifact.size_bytes}B)`));
      }
    }
  } catch {
    // artifacts endpoint unavailable
  }
  line("artifacts", String(artifactCount));
  return record.status === "passed" ? 0 : 1;
}

async function cmdRun(args: string[]): Promise<number> {
  const config = loadConfig(PROJECT);
  const intent = args.join(" ");
  const remote = await probeHealth(config);
  if (remote) {
    info(`control plane detected at ${config.api_url} — remote mode`);
    return runRemote(config, intent);
  }
  info(`no control plane at ${config.api_url} — local embedded mode`);
  return runLocal(intent);
}

async function cmdSandbox(args: string[]): Promise<number> {
  const config = loadConfig(PROJECT);
  const [sub, ...rest] = args;
  const eng = engine();

  switch (sub) {
    case "create": {
      const sbx = eng.create();
      ok(`sandbox created: ${cyan(sbx.id)} ${dim("(local)")}`);
      line("id", sbx.id);
      line("layout", "workspace/ artifacts/ tmp/");
      line("timeout", `${sbx.policy.execution_timeout_s}s`);
      line("network", sbx.policy.network_mode);
      return 0;
    }
    case "inspect": {
      const id = rest[0];
      if (!id) {
        fail("usage: workflo sandbox inspect <id>");
        return 2;
      }
      if (await probeHealth(config)) {
        const resp = await api.inspectSandbox(config, id);
        console.log(JSON.stringify(resp.data, null, 2));
        return resp.status === 200 ? 0 : 1;
      }
      const sbx = eng.get(id);
      console.log(JSON.stringify({
        id: sbx.id,
        workspace: sbx.workspace,
        files: eng.listFiles(sbx),
        artifacts: eng.collectArtifacts(sbx),
      }, null, 2));
      return 0;
    }
    case "exec": {
      const id = rest[0];
      const command = rest.slice(1).join(" ");
      if (!id || !command) {
        fail('usage: workflo sandbox exec <id> "<command>"');
        return 2;
      }
      if (await probeHealth(config)) {
        const resp = await api.execInSandbox(config, id, command);
        if (resp.status !== 200) {
          fail(JSON.stringify(resp.data));
          return 1;
        }
        console.log(String((resp.data as Record<string, unknown>).stdout ?? ""));
        return 0;
      }
      try {
        const sbx = eng.get(id);
        const result = await eng.execute(sbx, command);
        process.stdout.write(result.stdout);
        if (result.stderr) process.stderr.write(result.stderr);
        return result.exit_code ?? 1;
      } catch (exc) {
        if (exc instanceof PolicyViolation) {
          fail(`policy violation: ${exc.message}`);
          return 3;
        }
        throw exc;
      }
    }
    case "files": {
      const id = rest[0];
      if (!id) {
        fail("usage: workflo sandbox files <id>");
        return 2;
      }
      if (await probeHealth(config)) {
        const resp = await api.listSandboxFiles(config, id);
        for (const f of resp.data.files) console.log(f.path);
        return resp.status === 200 ? 0 : 1;
      }
      const sbx = eng.get(id);
      for (const f of eng.listFiles(sbx)) console.log(f);
      return 0;
    }
    case "destroy": {
      const id = rest[0];
      if (!id) {
        fail("usage: workflo sandbox destroy <id>");
        return 2;
      }
      if (await probeHealth(config)) {
        const resp = await api.destroySandbox(config, id);
        ok(`sandbox destroyed: ${id} (status: ${JSON.stringify(resp.data)})`);
        return resp.status === 200 ? 0 : 1;
      }
      eng.destroy(id);
      ok(`sandbox destroyed: ${id}`);
      return 0;
    }
    default:
      fail("usage: workflo sandbox create|inspect|exec|files|destroy");
      return 2;
  }
}

async function cmdArtifacts(args: string[]): Promise<number> {
  const config = loadConfig(PROJECT);
  const [sub, id] = args;
  if (sub === "list") {
    if (!id) {
      fail("usage: workflo artifacts list <runId>");
      return 2;
    }
    const resp = await api.runArtifacts(config, id);
    for (const artifact of resp.data.artifacts) {
      console.log(`  ${artifact.name.padEnd(40)} ${artifact.size_bytes}B`);
    }
    return resp.status === 200 ? 0 : 1;
  }
  if (sub === "fetch") {
    fail("fetch requires a running control plane; use artifacts list to enumerate");
    return 2;
  }
  fail("usage: workflo artifacts list|fetch");
  return 2;
}

async function cmdReport(args: string[]): Promise<number> {
  const config = loadConfig(PROJECT);
  const runId = args[0];
  if (!runId) {
    fail("usage: workflo report <runId>");
    return 2;
  }
  const resp = await api.getRun(config, runId);
  if (resp.status !== 200) {
    fail(`run '${runId}' not found on control plane`);
    return 1;
  }
  const record = resp.data;
  console.log(bold(`Report ${record.id}`));
  line("status", record.status);
  line("sandbox", record.sandbox_id ?? "-");
  for (const event of record.events ?? []) {
    console.log(gray(`  [${event.type}] ${event.message}`));
  }
  return 0;
}

async function cmdAgent(args: string[]): Promise<number> {
  const intent = args.join(" ");
  if (!intent) {
    fail('usage: workflo agent "<intent>"');
    return 2;
  }
  const discovery = discoverSurfaces(PROJECT);
  const steps = buildPlan(intent, discovery);
  console.log();
  console.log(bold("PLAN"));
  for (const step of steps) {
    console.log(`  ${cyan("\u251c")} ${bold(step.action.padEnd(18))} ${dim(step.detail)}`);
  }
  console.log();
  const config = loadConfig(PROJECT);
  if (await probeHealth(config)) {
    const resp = await api.agentPlan(config, intent, discovery.suites);
    if (resp.status === 200) ok(`plan registered on control plane (${resp.status})`);
  }
  return 0;
}

function startRepl(config: WorkfloConfig): void {
  const readline = require("readline") as typeof import("readline");
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: dim("workflo > "),
  });
  banner(PROJECT, "auto");
  rl.prompt();
  rl.on("line", async (inputLine: string) => {
    const input = inputLine.trim();
    if (!input) {
      rl.prompt();
      return;
    }
    if (["exit", "quit", ":q"].includes(input.toLowerCase())) {
      rl.close();
      process.exit(0);
    }
    const code = await dispatch(input.split(/\s+/), true);
    process.exitCode = code;
    rl.prompt();
  });
  rl.on("close", () => {
    process.exit(process.exitCode ?? 0);
  });
  void config;
}

async function dispatch(argv: string[], replMode = false): Promise<number> {
  const [command, ...args] = argv;
  switch ((command ?? "").toLowerCase()) {
    case "":
      return 0;
    case "help":
      printHelp();
      return 0;
    case "version":
    case "--version":
    case "-v":
      console.log(`workflo ${VERSION}`);
      return 0;
    case "--help":
    case "-h":
      printHelp();
      return 0;
    default:
      break;
  }

  const config = loadConfig(PROJECT);
  switch (command) {
    case "init":
      return cmdInit(config);
    case "doctor":
      return cmdDoctor(config);
    case "login":
      return cmdLogin(args, config);
    case "config":
      return cmdConfig(args, PROJECT);
    case "run":
      return cmdRun(args);
    case "test":
      return cmdRun(args.length ? args : []);
    case "agent":
      return cmdAgent(args);
    case "sandbox":
      return cmdSandbox(args);
    case "artifacts":
      return cmdArtifacts(args);
    case "report":
      return cmdReport(args);
    default:
      if (replMode) {
        fail(`unknown command '${command}' — try 'help'`);
        return 2;
      }
      fail(`unknown command '${command}'`);
      printHelp();
      return 2;
  }
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  if (argv.length === 0) {
    startRepl(loadConfig(PROJECT));
    return 0;
  }
  return dispatch(argv);
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((err) => {
    fail(err instanceof Error ? err.message : String(err));
    process.exitCode = 1;
  });

void os;
void warn;
