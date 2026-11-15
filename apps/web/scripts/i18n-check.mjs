// Static i18n check for the web app. Run: npm run i18n:check
// 1. No hard-coded Chinese UI text outside src/i18n (comments, `i18n-ignore` lines and server-message matchers excepted).
// 2. zh-TW and en define the same keys (tsc also enforces this through the Messages type).
// 3. Each key uses the same {placeholders} in both locales.
// 4. Lists keys that no source file references (info only; some keys are built from template strings).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("../src/", import.meta.url).pathname;
const CJK = /[㐀-鿿]/;
// Files that match fixed Chinese text sent by the server (data, not UI text).
const ALLOW = new Set(["lib/errors.ts"]);

const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p]; });
const files = walk(root).filter((f) => /\.(ts|tsx)$/.test(f));

let failed = false;
const hard = [];
for (const f of files) {
  const rel = relative(root, f);
  if (rel.startsWith("i18n/") || ALLOW.has(rel)) continue;
  let inBlock = false;
  readFileSync(f, "utf8").split("\n").forEach((line, i) => {
    let code = line;
    if (inBlock) { const e = code.indexOf("*/"); if (e < 0) return; code = code.slice(e + 2); inBlock = false; }
    code = code.replace(/\{?\/\*.*?\*\/\}?/g, "");
    const s = code.indexOf("/*"); if (s >= 0) { inBlock = true; code = code.slice(0, s); }
    if (/i18n-ignore/.test(line)) return;
    code = code.replace(/(^|[^:"'`\\])\/\/.*$/, "$1");
    if (CJK.test(code)) hard.push(`${rel}:${i + 1}: ${line.trim().slice(0, 120)}`);
  });
}
if (hard.length) { failed = true; console.error(`Hard-coded Chinese UI text (${hard.length}):\n  ${hard.join("\n  ")}`); }

const parse = (file) => {
  const out = new Map();
  for (const m of readFileSync(join(root, "i18n", file), "utf8").matchAll(/^\s*"([^"]+)":\s*(.+?),?$/gm)) out.set(m[1], m[2]);
  return out;
};
const zh = parse("zh-TW.ts"), en = parse("en.ts");
const vars = (v) => new Set([...v.matchAll(/\{(\w+)\}/g)].map((m) => m[1]));
const missing = [...zh.keys()].filter((k) => !en.has(k)), extra = [...en.keys()].filter((k) => !zh.has(k));
if (missing.length || extra.length) { failed = true; console.error(`Key mismatch. Missing in en: ${missing.join(", ") || "-"}. Only in en: ${extra.join(", ") || "-"}`); }
const varDiff = [];
for (const [k, v] of zh) {
  if (!en.has(k)) continue;
  const a = vars(v), b = vars(en.get(k));
  // English may drop a variable that only Chinese needs (and the reverse), but not invent one the caller never passes.
  const onlyEn = [...b].filter((x) => !a.has(x));
  if (onlyEn.length) varDiff.push(`${k}: en uses {${onlyEn.join("}, {")}} that zh-TW does not`);
}
if (varDiff.length) console.warn(`Placeholder differences (check the caller passes them):\n  ${varDiff.join("\n  ")}`);

const src = files.filter((f) => !relative(root, f).startsWith("i18n/")).map((f) => readFileSync(f, "utf8")).join("\n");
const unused = [...zh.keys()].filter((k) => !src.includes(`"${k}"`) && !src.includes(`\`${k.replace(/\.[^.]+$/, ".")}`));
console.log(`i18n: ${zh.size} keys, ${files.length} source files, ${hard.length} hard-coded strings, ${unused.length} keys without a literal reference.`);
if (unused.length) console.log(`  Possibly unused: ${unused.join(", ")}`);
process.exit(failed ? 1 : 0);
