export const VERSION = "0.1.0";

const useColor =
  process.stdout.isTTY && process.env.NO_COLOR === undefined;

function paint(code: string, text: string): string {
  return useColor ? `\x1b[${code}m${text}\x1b[0m` : text;
}

export const dim = (t: string) => paint("2", t);
export const bold = (t: string) => paint("1", t);
export const green = (t: string) => paint("32", t);
export const red = (t: string) => paint("31", t);
export const yellow = (t: string) => paint("33", t);
export const cyan = (t: string) => paint("36", t);
export const gray = (t: string) => paint("90", t);

export function ok(msg: string): void {
  console.log(`  ${green("\u2713")} ${msg}`);
}

export function fail(msg: string): void {
  console.log(`  ${red("\u2717")} ${msg}`);
}

export function info(msg: string): void {
  console.log(`  ${cyan("\u25c9")} ${msg}`);
}

export function warn(msg: string): void {
  console.log(`  ${yellow("!")} ${msg}`);
}

export function line(label: string, value: string): void {
  console.log(`  ${dim(label.padEnd(14))}${value}`);
}

export function banner(workspace: string, mode: string): void {
  const w = `Workspace: ${workspace}`;
  const m = `Mode: ${mode}`;
  const inner = Math.max(62, w.length + m.length + 6);
  console.log(dim("\u256d" + "\u2500".repeat(inner) + "\u256e"));
  console.log(
    dim("\u2502 ") +
      bold("WORKFLO") +
      " ".repeat(Math.max(1, inner - 9 - m.length - w.length - 2)) +
      dim(w + "   " + m) +
      dim(" \u2502"),
  );
  console.log(
    dim("\u2502 ") +
      dim("Autonomous QA & Runtime Agent") +
      " ".repeat(inner - 31) +
      dim("\u2502"),
  );
  console.log(dim("\u2570" + "\u2500".repeat(inner) + "\u2570"));
}

export async function confirm(question: string): Promise<boolean> {
  process.stdout.write(`${question} [y/N] `);
  return new Promise((resolve) => {
    const stdin = process.stdin;
    stdin.resume();
    stdin.once("data", (data) => {
      stdin.pause();
      const answer = data.toString().trim().toLowerCase();
      resolve(answer === "y" || answer === "yes");
    });
  });
}
