// Seeds one scenario into the API's store without an LLM call (see seed-scenario.py) and returns its id.
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../..");
const PYTHON = path.join(process.env.CR_VENV ?? path.join(ROOT, ".venv"), "bin", "python");

export function seedScenario(): string {
  const id = `scn_e2e${crypto.randomBytes(4).toString("hex")}`;
  execFileSync(PYTHON, [path.join(HERE, "seed-scenario.py"), id], { stdio: "pipe", timeout: 30_000 });
  return id;
}
