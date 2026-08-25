import * as fs from "fs";
import * as path from "path";

export interface Discovery {
  frameworks: string[];
  suites: string[];
  case_estimate: number;
  suggested_command: string;
}

const MARKERS: Array<[string, string, string]> = [
  ["package.json", "node", "npm test --silent"],
  ["pytest.ini", "pytest", "python -m pytest -q"],
  ["pyproject.toml", "pytest", "python -m pytest -q"],
  ["go.mod", "go", "go test ./..."],
  ["Cargo.toml", "cargo", "cargo test"],
];

export function discoverSurfaces(dir: string): Discovery {
  const frameworks: string[] = [];
  let suggested = "echo 'no test framework detected'";
  for (const [marker, framework, command] of MARKERS) {
    if (fs.existsSync(path.join(dir, marker))) {
      frameworks.push(framework);
      if (suggested.startsWith("echo")) suggested = command;
    }
  }

  const suites = new Set<string>();
  const walk = (current: string): void => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      if (!entry.isDirectory() && !entry.isFile()) continue;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (["node_modules", ".git", ".venv", "__pycache__", "dist"].includes(entry.name)) {
          continue;
        }
        walk(full);
      } else {
        const name = entry.name;
        if (
          name.startsWith("test_") ||
          name.endsWith(".test.ts") || name.endsWith(".test.js") ||
          name.endsWith(".spec.ts") || name.endsWith(".spec.js") ||
          name.endsWith("_test.go")
        ) {
          suites.add(name.replace(/\.(test|spec)\.(ts|js)$/, "").replace(/\.ts$|\.js$/, ""));
        }
        if (name === "conftest.py" || name === "pytest.ini") suites.add("pytest");
      }
    }
  };
  try {
    walk(dir);
  } catch {
    // unreadable directory yields no suites
  }

  return {
    frameworks,
    suites: [...suites].sort().slice(0, 50),
    case_estimate: Math.max(suites.size * 3, suites.size),
    suggested_command: suggested,
  };
}
