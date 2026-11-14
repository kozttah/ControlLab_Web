#!/usr/bin/env node
/**
 * Runner compartilhado e fail-closed de testes Web/TypeScript (Frente F9 — Job C / CL-DIR-001 §15.2 / AUD-015).
 *
 * Modos suportados:
 *   - `--scope all` (padrão quando invocado sem argumentos via `npm --prefix web test`):
 *       Exige `web/tsconfig.json`, executa `tsc -p web/tsconfig.json --noEmit` e exige
 *       ao menos 1 arquivo de teste em CADA diretório obrigatório (`tests/unit/f7` e `tests/unit/f8`).
 *   - `--scope f7`:
 *       Executa `tsc --noEmit` com as mesmas flags estritas de `web/tsconfig.json` sobre
 *       `web/node-builtins.d.ts` (se existir), `web/bridge/`, `web/worker/`, `web/storage/` e
 *       `tests/unit/f7/`, exigindo `tests/unit/f7` não vazio antes de `node --test`.
 *   - `--scope f8`:
 *       Executa `tsc --noEmit` com as mesmas flags estritas de `web/tsconfig.json` sobre
 *       `web/node-builtins.d.ts` (se existir), `web/features/`, `web/charts/`, `web/app/` e
 *       `tests/unit/f8/`, exigindo `tests/unit/f8` não vazio antes de `node --test`.
 *
 * Política fail-closed (AUD-015):
 *   - Argumentos ou escopos inválidos encerram com código != 0.
 *   - Ausência de `tsc` (`web/node_modules/.bin/tsc`, `node_modules/.bin/tsc` ou `PATH`)
 *     quando há arquivos TS no escopo falha explicitamente com código != 0 (proibido pular).
 *   - Ausência de arquivos TS no escopo ou diretório obrigatório de testes ausente/vazio
 *     encerra com código != 0.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_REPO_ROOT = path.resolve(__dirname, "..");

const TEST_FILE_RE = /\.test\.(ts|mts|mjs|js)$/i;
const TS_SOURCE_FILE_RE = /\.(ts|tsx|mts|cts)$/i;
const TS_DECLARATION_RE = /\.d\.(ts|mts|cts)$/i;

export const VALID_SCOPES = Object.freeze(["all", "f7", "f8"]);

export const STRICT_TSC_FLAGS = Object.freeze([
  "--noEmit",
  "--target",
  "ES2022",
  "--module",
  "NodeNext",
  "--moduleResolution",
  "NodeNext",
  "--strict",
  "--skipLibCheck",
  "--allowImportingTsExtensions",
  "--erasableSyntaxOnly",
  "--verbatimModuleSyntax",
  "--lib",
  "ES2022,DOM,WebWorker",
]);

function walkFiles(dir, predicate, out = []) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
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

function getScopeConfig(repoRoot, scope) {
  const f7SourceDirs = [
    path.join(repoRoot, "web", "bridge"),
    path.join(repoRoot, "web", "worker"),
    path.join(repoRoot, "web", "storage"),
  ];
  const f8SourceDirs = [
    path.join(repoRoot, "web", "features"),
    path.join(repoRoot, "web", "charts"),
    path.join(repoRoot, "web", "app"),
  ];
  const f7TestDir = path.join(repoRoot, "tests", "unit", "f7");
  const f8TestDir = path.join(repoRoot, "tests", "unit", "f8");

  if (scope === "all") {
    return {
      sourceDirs: [...f7SourceDirs, ...f8SourceDirs],
      testDirs: [f7TestDir, f8TestDir],
    };
  }
  if (scope === "f7") {
    return {
      sourceDirs: f7SourceDirs,
      testDirs: [f7TestDir],
    };
  }
  if (scope === "f8") {
    return {
      sourceDirs: f8SourceDirs,
      testDirs: [f8TestDir],
    };
  }
  throw new Error(`Escopo inválido: ${String(scope)}. Valores aceitos: ${VALID_SCOPES.join(", ")}.`);
}

export function parseCliArgs(argv = process.argv.slice(2)) {
  if (!Array.isArray(argv)) {
    throw new TypeError("argv deve ser um array de strings.");
  }

  let scope = "all";
  let seenScope = false;

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (typeof arg !== "string") {
      throw new TypeError(`Argumento inválido na posição ${i}: esperado string.`);
    }

    if (arg === "--scope") {
      if (seenScope) {
        throw new Error("Argumento duplicado: --scope informado mais de uma vez.");
      }
      if (i + 1 >= argv.length) {
        throw new Error("Argumento incompleto: --scope requer um valor (all, f7 ou f8).");
      }
      const value = argv[i + 1];
      if (!VALID_SCOPES.includes(value)) {
        throw new Error(`Escopo inválido '${value}'. Valores aceitos: ${VALID_SCOPES.join(", ")}.`);
      }
      scope = value;
      seenScope = true;
      i += 1;
      continue;
    }

    if (arg.startsWith("--scope=")) {
      if (seenScope) {
        throw new Error("Argumento duplicado: --scope informado mais de uma vez.");
      }
      const value = arg.slice("--scope=".length);
      if (!VALID_SCOPES.includes(value)) {
        throw new Error(`Escopo inválido '${value}'. Valores aceitos: ${VALID_SCOPES.join(", ")}.`);
      }
      scope = value;
      seenScope = true;
      continue;
    }

    throw new Error(`Argumento desconhecido ou não permitido: '${arg}'. Uso permitido: [--scope all|f7|f8].`);
  }

  return { scope };
}

function isExecutableFile(filePath) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return false;
  }
  if (process.platform === "win32") {
    return true;
  }
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export function resolveTscCommand(options = {}) {
  const opts = typeof options === "string" ? { repoRoot: options } : (options ?? {});
  const root = path.resolve(opts.repoRoot ?? opts.rootDir ?? DEFAULT_REPO_ROOT);
  const env = opts.env ?? process.env;
  const binNames = process.platform === "win32" ? ["tsc.cmd", "tsc"] : ["tsc"];

  for (const binName of binNames) {
    const localCandidates = [
      path.join(root, "web", "node_modules", ".bin", binName),
      path.join(root, "node_modules", ".bin", binName),
    ];
    for (const candidate of localCandidates) {
      if (isExecutableFile(candidate)) {
        return candidate;
      }
    }
  }

  for (const binName of binNames) {
    const probe = spawnSync(binName, ["--version"], {
      stdio: "ignore",
      env,
    });
    if (!probe.error && probe.status === 0) {
      return binName;
    }
  }

  return null;
}

export function runWebTests(options = {}) {
  const opts = options ?? {};
  const repoRoot = path.resolve(opts.repoRoot ?? opts.rootDir ?? DEFAULT_REPO_ROOT);
  const env = opts.env ?? process.env;
  const emitStdout = opts.writeStdout ?? ((chunk) => process.stdout.write(chunk));
  const emitStderr = opts.writeStderr ?? ((chunk) => process.stderr.write(chunk));

  const stdoutChunks = [];
  const stderrChunks = [];

  const logOut = (line) => {
    const text = `${line}\n`;
    stdoutChunks.push(text);
    emitStdout(text);
  };
  const logErr = (line) => {
    const text = `${line}\n`;
    stderrChunks.push(text);
    emitStderr(text);
  };
  const forwardChildOutput = (res) => {
    if (typeof res.stdout === "string" && res.stdout.length > 0) {
      stdoutChunks.push(res.stdout);
      emitStdout(res.stdout);
    }
    if (typeof res.stderr === "string" && res.stderr.length > 0) {
      stderrChunks.push(res.stderr);
      emitStderr(res.stderr);
    }
  };

  let scope;
  try {
    if (opts.argv !== undefined) {
      ({ scope } = parseCliArgs(opts.argv));
    } else if (opts.scope !== undefined) {
      ({ scope } = parseCliArgs(["--scope", String(opts.scope)]));
    } else {
      ({ scope } = parseCliArgs([]));
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    logErr(`[typecheck] FAIL: argumentos CLI inválidos — ${msg}`);
    logErr("[unit-tests] FAIL: execução abortada por argumentos CLI inválidos.");
    return {
      exitCode: 1,
      scope: null,
      typecheckStatus: "FAIL",
      unitTestsStatus: "FAIL",
      tsFiles: [],
      testFiles: [],
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  const { sourceDirs, testDirs } = getScopeConfig(repoRoot, scope);

  const tsFiles = [];
  for (const dir of [...sourceDirs, ...testDirs]) {
    walkFiles(dir, (name) => TS_SOURCE_FILE_RE.test(name) && !TS_DECLARATION_RE.test(name), tsFiles);
  }

  if (tsFiles.length === 0) {
    logErr(`[typecheck] FAIL: nenhum arquivo TypeScript encontrado no escopo '${scope}'.`);
    logErr(`[unit-tests] FAIL: execução cancelada devido à falha no estágio [typecheck].`);
    return {
      exitCode: 1,
      scope,
      typecheckStatus: "FAIL",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles: [],
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  const tscCmd = resolveTscCommand({ repoRoot, env });
  if (tscCmd === null) {
    logErr(
      `[typecheck] FAIL: tsc não encontrado em web/node_modules/.bin/tsc, node_modules/.bin/tsc ou PATH (escopo '${scope}', ${tsFiles.length} arquivo(s) TS).`
    );
    logErr("[unit-tests] FAIL: execução bloqueada (fail-closed) porque o compilador TypeScript está ausente.");
    return {
      exitCode: 1,
      scope,
      typecheckStatus: "FAIL",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles: [],
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  let tscArgs;
  if (scope === "all") {
    const tsconfigPath = path.join(repoRoot, "web", "tsconfig.json");
    if (!fs.existsSync(tsconfigPath) || !fs.statSync(tsconfigPath).isFile()) {
      logErr(`[typecheck] FAIL: arquivo obrigatório não encontrado: ${path.relative(repoRoot, tsconfigPath)}.`);
      logErr("[unit-tests] FAIL: execução cancelada devido à falha no estágio [typecheck].");
      return {
        exitCode: 1,
        scope,
        typecheckStatus: "FAIL",
        unitTestsStatus: "FAIL",
        tsFiles,
        testFiles: [],
        stdout: stdoutChunks.join(""),
        stderr: stderrChunks.join(""),
      };
    }
    tscArgs = ["-p", tsconfigPath, "--noEmit"];
  } else {
    const nodeBuiltinsDts = path.join(repoRoot, "web", "node-builtins.d.ts");
    const extraDeclarations = [];
    for (const dir of [...sourceDirs, ...testDirs]) {
      walkFiles(dir, (name) => TS_DECLARATION_RE.test(name), extraDeclarations);
    }
    const targetFiles = [];
    if (fs.existsSync(nodeBuiltinsDts) && fs.statSync(nodeBuiltinsDts).isFile()) {
      targetFiles.push(nodeBuiltinsDts);
    }
    for (const decl of extraDeclarations) {
      if (!targetFiles.includes(decl)) {
        targetFiles.push(decl);
      }
    }
    targetFiles.push(...tsFiles);
    tscArgs = [...STRICT_TSC_FLAGS, ...targetFiles];
  }

  logOut(`[run_web_tests] Executando typecheck (${scope}, ${tsFiles.length} arquivo(s) TS)...`);
  const tcRes = spawnSync(tscCmd, tscArgs, {
    cwd: repoRoot,
    env,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  forwardChildOutput(tcRes);

  if (tcRes.error) {
    logErr(`[typecheck] FAIL: erro ao invocar '${tscCmd}': ${tcRes.error.message}`);
    logErr("[unit-tests] FAIL: execução cancelada devido à falha no estágio [typecheck].");
    return {
      exitCode: 1,
      scope,
      typecheckStatus: "FAIL",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles: [],
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }
  if (tcRes.status !== 0) {
    const code = tcRes.status ?? 1;
    logErr(`[typecheck] FAIL: compilador TypeScript retornou código ${code} (escopo '${scope}').`);
    logErr("[unit-tests] FAIL: execução cancelada devido à falha no estágio [typecheck].");
    return {
      exitCode: code,
      scope,
      typecheckStatus: "FAIL",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles: [],
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  logOut(`[typecheck] PASS (${scope}, ${tsFiles.length} arquivo(s) TS)`);

  const testFiles = [];
  for (const dir of testDirs) {
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
      logErr(
        `[unit-tests] FAIL: diretório obrigatório de testes ausente: ${path.relative(repoRoot, dir)} (escopo '${scope}').`
      );
      return {
        exitCode: 1,
        scope,
        typecheckStatus: "PASS",
        unitTestsStatus: "FAIL",
        tsFiles,
        testFiles,
        stdout: stdoutChunks.join(""),
        stderr: stderrChunks.join(""),
      };
    }
    const dirTests = walkFiles(dir, (name) => TEST_FILE_RE.test(name));
    if (dirTests.length === 0) {
      logErr(
        `[unit-tests] FAIL: diretório obrigatório de testes vazio (0 arquivos *.test.ts|mts|mjs|js): ${path.relative(repoRoot, dir)} (escopo '${scope}').`
      );
      return {
        exitCode: 1,
        scope,
        typecheckStatus: "PASS",
        unitTestsStatus: "FAIL",
        tsFiles,
        testFiles,
        stdout: stdoutChunks.join(""),
        stderr: stderrChunks.join(""),
      };
    }
    testFiles.push(...dirTests);
  }

  if (testFiles.length === 0) {
    logErr(`[unit-tests] FAIL: nenhum arquivo de teste encontrado no escopo '${scope}'.`);
    return {
      exitCode: 1,
      scope,
      typecheckStatus: "PASS",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles,
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  logOut(`[run_web_tests] Executando ${testFiles.length} arquivo(s) de teste com node --test...`);
  const nodeTestEnv = { ...env };
  delete nodeTestEnv.NODE_TEST_CONTEXT;
  const testRes = spawnSync(process.execPath, ["--test", ...testFiles], {
    cwd: repoRoot,
    env: nodeTestEnv,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  forwardChildOutput(testRes);

  if (testRes.error) {
    logErr(`[unit-tests] FAIL: falha ao invocar node --test: ${testRes.error.message}`);
    return {
      exitCode: 1,
      scope,
      typecheckStatus: "PASS",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles,
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }
  if (testRes.status !== 0) {
    const code = testRes.status ?? 1;
    logErr(`[unit-tests] FAIL: node --test retornou código ${code} (escopo '${scope}').`);
    return {
      exitCode: code,
      scope,
      typecheckStatus: "PASS",
      unitTestsStatus: "FAIL",
      tsFiles,
      testFiles,
      stdout: stdoutChunks.join(""),
      stderr: stderrChunks.join(""),
    };
  }

  logOut(`[unit-tests] PASS (${scope}, ${testFiles.length} arquivo(s) de teste)`);
  return {
    exitCode: 0,
    scope,
    typecheckStatus: "PASS",
    unitTestsStatus: "PASS",
    tsFiles,
    testFiles,
    stdout: stdoutChunks.join(""),
    stderr: stderrChunks.join(""),
  };
}

const isMainModule =
  typeof process.argv[1] === "string" &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isMainModule) {
  const result = runWebTests({ argv: process.argv.slice(2) });
  process.exit(result.exitCode);
}
