import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export interface WorkfloConfig {
  api_url: string;
  token?: string;
  workspace_id: string;
  sandbox_policy?: Record<string, unknown>;
}

const HOME_DIR = path.join(os.homedir(), ".workflo");
const GLOBAL_CONFIG = path.join(HOME_DIR, "config.json");
const PROJECT_CONFIG = ".workflo.json";

export function defaultConfig(): WorkfloConfig {
  return {
    api_url: process.env.CORTEX_URL || "http://localhost:8000",
    token: process.env.WORKFLO_TOKEN || undefined,
    workspace_id: process.env.WORKSPACE_ID || "default",
  };
}

export function loadConfig(projectDir: string = process.cwd()): WorkfloConfig {
  const config = defaultConfig();
  try {
    if (fs.existsSync(GLOBAL_CONFIG)) {
      Object.assign(config, JSON.parse(fs.readFileSync(GLOBAL_CONFIG, "utf8")));
    }
  } catch {
    // corrupt global config falls back to defaults
  }
  const projectFile = path.join(projectDir, PROJECT_CONFIG);
  try {
    if (fs.existsSync(projectFile)) {
      Object.assign(config, JSON.parse(fs.readFileSync(projectFile, "utf8")));
    }
  } catch {
    // corrupt project config falls back to global/defaults
  }
  return config;
}

export function saveGlobalConfig(config: WorkfloConfig): void {
  fs.mkdirSync(HOME_DIR, { recursive: true });
  fs.writeFileSync(GLOBAL_CONFIG, JSON.stringify(config, null, 2));
}

export function saveProjectConfig(
  projectDir: string,
  patch: Partial<WorkfloConfig>,
): void {
  const file = path.join(projectDir, PROJECT_CONFIG);
  let current: Partial<WorkfloConfig> = {};
  if (fs.existsSync(file)) {
    try {
      current = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {
      current = {};
    }
  }
  const merged = { ...current, ...patch };
  fs.writeFileSync(file, JSON.stringify(merged, null, 2));
}

export function credentialsPath(): string {
  return GLOBAL_CONFIG;
}
