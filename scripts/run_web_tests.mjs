#!/usr/bin/env node
/**
 * Runner compartilhado de testes Web/TypeScript (Frente F9 — Job C / Seção 15.2).
 *
 * 1. Verifica type-check via `tsc -p web/tsconfig.json --noEmit` quando houver
 *    arquivos TS em `web/` ou `tests/unit/{f7,f8}` (ou declarações no tsconfig)
 *    e `tsc` estiver disponível em `web/node_modules/.bin/tsc` ou no `PATH`.
 * 2. Descobre recursivamente arquivos `*.test.ts`, `*.test.mts`, `*.test.mjs` e
 *    `*.test.js` sob `tests/unit/f7` e `tests/unit/f8` (ignorando diretórios
 *    inexistentes) e executa `node --test <arquivos>`.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");

const TEST_DIRS = [
  path.join(repoRoot, "tests", "unit", "f7"),
  path.join(repoRoot, "tests", "unit", "f8"),
];

const WEB_SOURCE_DIRS = [
  path.join(repoRoot, "web", "bridge"),
  path.join(repoRoot, "web", "worker"),
  path.join(repoRoot, "web", "storage"),
  path.join(repoRoot, "web", "features"),
  path.join(repoRoot, "web", "charts"),
  path.join(repoRoot, "web", "app"),
];

const TEST_FILE_RE = /\.test\.(ts|mts|mjs|js)$/i;
const TS_FILE_RE = /\.(ts|tsx|mts|cts)$/i;

function walkFiles(dir, predicate, out = []) {
  if (!fs.existsSync(dir)) {
    return out;
  }
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === ".git" || entry.name === "dist") {
      continue;
    }
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkFiles(full, predicate, out);
    } else if (entry.isFile() && predicate(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function resolveTscCommand() {
  const localCandidates = [
    path.join(repoRoot, "web", "node_modules", ".bin", "tsc"),
    path.join(repoRoot, "node_modules", ".bin", "tsc"),
  ];
  for (const candidate of localCandidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  const probe = spawnSync("tsc", ["--version"], { stdio: "ignore" });
  if (probe.status === 0) {
    return "tsc";
  }
  return null;
}

const tsFiles = [];
for (const dir of [...WEB_SOURCE_DIRS, ...TEST_DIRS]) {
  walkFiles(dir, (name) => TS_FILE_RE.test(name), tsFiles);
}

const tscCmd = resolveTscCommand();
const tsconfigPath = path.join(repoRoot, "web", "tsconfig.json");
if (tsFiles.length > 0 && tscCmd !== null && fs.existsSync(tsconfigPath)) {
  console.log(`[run_web_tests] Executando typecheck (${tscCmd} -p web/tsconfig.json --noEmit)...`);
  const tcRes = spawnSync(tscCmd, ["-p", tsconfigPath, "--noEmit"], {
    cwd: repoRoot,
    stdio: "inherit",
  });
  if (tcRes.error) {
    console.error(`[run_web_tests] Falha ao invocar tsc: ${tcRes.error.message}`);
    process.exit(1);
  }
  if (tcRes.status !== 0) {
    process.exit(tcRes.status ?? 1);
  }
} else if (tsFiles.length > 0 && tscCmd === null) {
  console.warn("[run_web_tests] Aviso: tsc não encontrado em web/node_modules/.bin nem no PATH; pulando typecheck.");
}

const testFiles = [];
for (const dir of TEST_DIRS) {
  walkFiles(dir, (name) => TEST_FILE_RE.test(name), testFiles);
}

if (testFiles.length === 0) {
  console.log("[run_web_tests] Nenhum arquivo de teste (*.test.ts|mts|mjs|js) encontrado em tests/unit/f7 ou tests/unit/f8.");
  process.exit(0);
}

console.log(`[run_web_tests] Executando ${testFiles.length} arquivo(s) com node --test...`);
const testRes = spawnSync(process.execPath, ["--test", ...testFiles], {
  cwd: repoRoot,
  stdio: "inherit",
});
if (testRes.error) {
  console.error(`[run_web_tests] Falha ao invocar node --test: ${testRes.error.message}`);
  process.exit(1);
}
process.exit(testRes.status ?? 1);
