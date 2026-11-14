import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  parseCliArgs,
  resolveTscCommand,
  runWebTests,
  STRICT_TSC_FLAGS,
} from "../../scripts/run_web_tests.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const RUNNER_PATH = path.join(REPO_ROOT, "scripts", "run_web_tests.mjs");

function createTempDir(prefix = "controllab-f9-runner-") {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
}

function writeMockTsc(binPath, { exitCode = 0, argsLogFile = null } = {}) {
  const script = `#!${process.execPath}
import fs from "node:fs";
const args = process.argv.slice(2);
if (args.includes("--version")) {
  process.stdout.write("Version 5.9.3-mock\\n");
  process.exit(0);
}
${
  argsLogFile
    ? `fs.writeFileSync(${JSON.stringify(argsLogFile)}, JSON.stringify(args, null, 2), "utf8");`
    : ""
}
if (${exitCode} !== 0) {
  process.stderr.write("mock tsc error TS2322\\n");
}
process.exit(${exitCode});
`;
  writeFile(binPath, script);
  fs.chmodSync(binPath, 0o755);
}

function createSyntheticRepo(rootDir, options = {}) {
  const {
    includeTsconfig = true,
    includeF7Test = true,
    includeF8Test = true,
    includeF7Ts = true,
    includeF8Ts = true,
    includeNodeBuiltins = true,
    failingUnitTest = false,
    markerFile = null,
  } = options;

  writeFile(
    path.join(rootDir, "web", "package.json"),
    JSON.stringify({ name: "tmp-web", private: true, type: "module" }, null, 2)
  );
  writeFile(
    path.join(rootDir, "tests", "package.json"),
    JSON.stringify({ private: true, type: "module" }, null, 2)
  );

  if (includeTsconfig) {
    writeFile(
      path.join(rootDir, "web", "tsconfig.json"),
      JSON.stringify(
        {
          compilerOptions: {
            target: "ES2022",
            module: "NodeNext",
            moduleResolution: "NodeNext",
            strict: true,
            skipLibCheck: true,
            allowImportingTsExtensions: true,
            erasableSyntaxOnly: true,
            verbatimModuleSyntax: true,
            noEmit: true,
            lib: ["ES2022", "DOM", "WebWorker"],
          },
          include: [
            "node-builtins.d.ts",
            "bridge/**/*",
            "worker/**/*",
            "storage/**/*",
            "features/**/*",
            "charts/**/*",
            "app/**/*",
            "../tests/unit/f7/**/*",
            "../tests/unit/f8/**/*",
          ],
        },
        null,
        2
      )
    );
  }

  if (includeNodeBuiltins) {
    writeFile(
      path.join(rootDir, "web", "node-builtins.d.ts"),
      'declare module "node:test" {}\n'
    );
  }

  if (includeF7Ts) {
    writeFile(
      path.join(rootDir, "web", "bridge", "sample.ts"),
      "export function addOne(x: number): number { return x + 1; }\n"
    );
    writeFile(
      path.join(rootDir, "web", "worker", "worker_stub.ts"),
      "export const WORKER_READY = false;\n"
    );
    writeFile(
      path.join(rootDir, "web", "storage", "store_stub.ts"),
      "export const STORE_VERSION = 1;\n"
    );
  }

  if (includeF8Ts) {
    writeFile(
      path.join(rootDir, "web", "features", "feature_stub.ts"),
      "export const FEATURE_TAG = 'lqr';\n"
    );
    writeFile(
      path.join(rootDir, "web", "charts", "chart_stub.ts"),
      "export const CHART_TAG = 'svg';\n"
    );
    writeFile(
      path.join(rootDir, "web", "app", "app_stub.ts"),
      "export const APP_TAG = 'shell';\n"
    );
  }

  fs.mkdirSync(path.join(rootDir, "tests", "unit", "f7"), { recursive: true });
  fs.mkdirSync(path.join(rootDir, "tests", "unit", "f8"), { recursive: true });

  if (includeF7Test) {
    const markerSnippet = markerFile
      ? `import fs from "node:fs";\nfs.writeFileSync(${JSON.stringify(markerFile)}, "ran");\n`
      : "";
    writeFile(
      path.join(rootDir, "tests", "unit", "f7", "sample.test.mjs"),
      `import test from "node:test";
import assert from "node:assert/strict";
${markerSnippet}
test("f7 sample", () => {
  assert.equal(${failingUnitTest ? "1, 2" : "1 + 1, 2"});
});
`
    );
  }

  if (includeF8Test) {
    writeFile(
      path.join(rootDir, "tests", "unit", "f8", "sample.test.mjs"),
      `import test from "node:test";
import assert from "node:assert/strict";

test("f8 sample", () => {
  assert.equal(2 + 2, 4);
});
`
    );
  }
}

function captureIo() {
  return {
    writeStdout: () => {},
    writeStderr: () => {},
  };
}

test("test_acceptance_runner_requires_tsc_and_tests", async (t) => {
  await t.test("parseCliArgs valida escopos e rejeita flags/argumentos inválidos", () => {
    assert.deepEqual(parseCliArgs([]), { scope: "all" });
    assert.deepEqual(parseCliArgs(["--scope", "all"]), { scope: "all" });
    assert.deepEqual(parseCliArgs(["--scope", "f7"]), { scope: "f7" });
    assert.deepEqual(parseCliArgs(["--scope", "f8"]), { scope: "f8" });
    assert.deepEqual(parseCliArgs(["--scope=f7"]), { scope: "f7" });
    assert.deepEqual(parseCliArgs(["--scope=f8"]), { scope: "f8" });

    assert.throws(() => parseCliArgs(["--scope", "invalid"]));
    assert.throws(() => parseCliArgs(["--scope=invalid"]));
    assert.throws(() => parseCliArgs(["--scope"]));
    assert.throws(() => parseCliArgs(["--skip-typecheck"]));
    assert.throws(() => parseCliArgs(["--scope", "f7", "--scope", "f8"]));
    assert.throws(() => parseCliArgs(["unexpected"]));
  });

  await t.test("CLI real falha fechado sem tsc no PATH (sem argumentos, --scope all, --scope f7, --scope f8)", () => {
    const emptyBinDir = createTempDir("controllab-empty-path-");
    const tmpRepo = createTempDir("controllab-cli-notsc-");
    try {
      createSyntheticRepo(tmpRepo);
      const copiedRunner = path.join(tmpRepo, "scripts", "run_web_tests.mjs");
      fs.mkdirSync(path.dirname(copiedRunner), { recursive: true });
      fs.copyFileSync(RUNNER_PATH, copiedRunner);

      const isolatedEnv = { ...process.env, PATH: emptyBinDir };

      // 1. Subprocesso isolado contra árvore sem node_modules/.bin/tsc nem tsc no PATH
      for (const cliArgs of [[], ["--scope", "all"], ["--scope", "f7"], ["--scope", "f8"]]) {
        const res = spawnSync(process.execPath, [copiedRunner, ...cliArgs], {
          cwd: tmpRepo,
          env: isolatedEnv,
          encoding: "utf8",
        });
        assert.notEqual(res.status, 0, `CLI sem tsc deveria falhar para args=${JSON.stringify(cliArgs)}`);
        assert.match(res.stderr, /\[typecheck\] FAIL/);
        assert.doesNotMatch(res.stdout, /\[typecheck\] PASS/);
        assert.doesNotMatch(res.stdout, /\[unit-tests\] PASS/);
      }

      // 2. CLI real diretamente no repositório quando não há tsc local em node_modules/.bin
      const repoLocalTsc = [
        path.join(REPO_ROOT, "web", "node_modules", ".bin", "tsc"),
        path.join(REPO_ROOT, "node_modules", ".bin", "tsc"),
      ].some((p) => fs.existsSync(p));

      if (!repoLocalTsc) {
        for (const cliArgs of [[], ["--scope", "all"], ["--scope", "f7"], ["--scope", "f8"]]) {
          const res = spawnSync(process.execPath, [RUNNER_PATH, ...cliArgs], {
            cwd: REPO_ROOT,
            env: isolatedEnv,
            encoding: "utf8",
          });
          assert.notEqual(
            res.status,
            0,
            `CLI real no repositório sem tsc deveria falhar para args=${JSON.stringify(cliArgs)}`
          );
          assert.match(res.stderr, /\[typecheck\] FAIL/);
          assert.doesNotMatch(res.stdout, /\[typecheck\] PASS/);
          assert.doesNotMatch(res.stdout, /\[unit-tests\] PASS/);
        }
      }
    } finally {
      fs.rmSync(emptyBinDir, { recursive: true, force: true });
      fs.rmSync(tmpRepo, { recursive: true, force: true });
    }
  });

  await t.test("CLI real rejeita escopos e flags inválidas com código != 0", () => {
    for (const cliArgs of [
      ["--scope", "invalid"],
      ["--scope=invalid"],
      ["--scope"],
      ["--skip-typecheck"],
      ["invalid-arg"],
    ]) {
      const res = spawnSync(process.execPath, [RUNNER_PATH, ...cliArgs], {
        cwd: REPO_ROOT,
        encoding: "utf8",
      });
      assert.notEqual(res.status, 0, `Args inválidos deveriam falhar: ${JSON.stringify(cliArgs)}`);
    }
  });

  await t.test("runWebTests falha com código != 0 para pasta de teste vazia/ausente, falta de TS ou falta de tsconfig", () => {
    const tmpRepo = createTempDir("controllab-empty-tests-");
    const mockBinDir = createTempDir("controllab-mock-tsc-");
    try {
      const emptyEnv = { ...process.env, PATH: mockBinDir };
      writeMockTsc(path.join(mockBinDir, "tsc"), { exitCode: 0 });

      // (a1) --scope all com tests/unit/f8 vazia -> exit != 0
      createSyntheticRepo(tmpRepo, { includeF7Test: true, includeF8Test: false });
      let res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "all"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.equal(res.typecheckStatus, "PASS");
      assert.equal(res.unitTestsStatus, "FAIL");
      assert.match(res.stderr, /\[unit-tests\] FAIL/);

      // (a2) --scope all com tests/unit/f7 vazia -> exit != 0
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.mkdirSync(tmpRepo, { recursive: true });
      createSyntheticRepo(tmpRepo, { includeF7Test: false, includeF8Test: true });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "all"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.match(res.stderr, /\[unit-tests\] FAIL/);

      // (a3) --scope f7 com tests/unit/f7 ausente -> exit != 0
      fs.rmSync(path.join(tmpRepo, "tests", "unit", "f7"), { recursive: true, force: true });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f7"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.match(res.stderr, /\[unit-tests\] FAIL/);

      // (a4) --scope f8 com tests/unit/f8 vazia -> exit != 0
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.mkdirSync(tmpRepo, { recursive: true });
      createSyntheticRepo(tmpRepo, { includeF8Test: false });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f8"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.match(res.stderr, /\[unit-tests\] FAIL/);

      // (a5) --scope all sem web/tsconfig.json -> exit != 0
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.mkdirSync(tmpRepo, { recursive: true });
      createSyntheticRepo(tmpRepo, { includeTsconfig: false });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "all"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.match(res.stderr, /\[typecheck\] FAIL/);

      // (a6) tsFiles.length === 0 no escopo f7 -> exit != 0
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.mkdirSync(tmpRepo, { recursive: true });
      createSyntheticRepo(tmpRepo, { includeF7Ts: false });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f7"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.match(res.stderr, /\[typecheck\] FAIL/);

      // (b) --scope invalid via runWebTests -> exit != 0
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "invalid"],
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);

      res = runWebTests({
        repoRoot: tmpRepo,
        scope: "invalid",
        env: emptyEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
    } finally {
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.rmSync(mockBinDir, { recursive: true, force: true });
    }
  });

  await t.test("runWebTests com tsc mock, TS válido e .test.mjs válido retorna 0 e registra [typecheck] PASS e [unit-tests] PASS", () => {
    const tmpRepo = createTempDir("controllab-pass-");
    const mockBinDir = createTempDir("controllab-mock-pass-");
    const argsLogFile = path.join(mockBinDir, "tsc_args.json");
    try {
      createSyntheticRepo(tmpRepo);
      const mockTscPath = path.join(mockBinDir, "tsc");
      writeMockTsc(mockTscPath, { exitCode: 0, argsLogFile });
      const isolatedEnv = { ...process.env, PATH: mockBinDir };

      // 1. --scope all
      let res = runWebTests({
        repoRoot: tmpRepo,
        argv: [],
        env: isolatedEnv,
        ...captureIo(),
      });
      assert.equal(res.exitCode, 0);
      assert.equal(res.scope, "all");
      assert.equal(res.typecheckStatus, "PASS");
      assert.equal(res.unitTestsStatus, "PASS");
      assert.match(res.stdout, /^\[typecheck\] PASS/m);
      assert.match(res.stdout, /^\[unit-tests\] PASS/m);

      let recordedArgs = JSON.parse(fs.readFileSync(argsLogFile, "utf8"));
      assert.deepEqual(recordedArgs, [
        "-p",
        path.join(tmpRepo, "web", "tsconfig.json"),
        "--noEmit",
      ]);

      // 2. --scope f7 (não deve incluir arquivos F8)
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f7"],
        env: isolatedEnv,
        ...captureIo(),
      });
      assert.equal(res.exitCode, 0);
      assert.equal(res.scope, "f7");
      assert.match(res.stdout, /^\[typecheck\] PASS/m);
      assert.match(res.stdout, /^\[unit-tests\] PASS/m);

      recordedArgs = JSON.parse(fs.readFileSync(argsLogFile, "utf8"));
      for (const flag of STRICT_TSC_FLAGS) {
        assert.ok(recordedArgs.includes(flag), `Flag estrita ausente em --scope f7: ${flag}`);
      }
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "node-builtins.d.ts")));
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "bridge", "sample.ts")));
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "worker", "worker_stub.ts")));
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "storage", "store_stub.ts")));
      assert.ok(!recordedArgs.some((a) => a.includes(`${path.sep}features${path.sep}`)));
      assert.ok(!recordedArgs.some((a) => a.includes(`${path.sep}charts${path.sep}`)));
      assert.ok(!recordedArgs.some((a) => a.includes(`${path.sep}app${path.sep}`)));
      assert.ok(!recordedArgs.some((a) => a.includes(`${path.sep}f8${path.sep}`)));

      // 3. --scope f8 (não deve incluir testes F7)
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f8"],
        env: isolatedEnv,
        ...captureIo(),
      });
      assert.equal(res.exitCode, 0);
      assert.equal(res.scope, "f8");
      assert.match(res.stdout, /^\[typecheck\] PASS/m);
      assert.match(res.stdout, /^\[unit-tests\] PASS/m);

      recordedArgs = JSON.parse(fs.readFileSync(argsLogFile, "utf8"));
      for (const flag of STRICT_TSC_FLAGS) {
        assert.ok(recordedArgs.includes(flag), `Flag estrita ausente em --scope f8: ${flag}`);
      }
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "features", "feature_stub.ts")));
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "charts", "chart_stub.ts")));
      assert.ok(recordedArgs.includes(path.join(tmpRepo, "web", "app", "app_stub.ts")));
      assert.ok(!recordedArgs.some((a) => a.includes(`${path.sep}f7${path.sep}`)));
    } finally {
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.rmSync(mockBinDir, { recursive: true, force: true });
    }
  });

  await t.test("falha de tsc interrompe antes dos testes unitários e falha de unitário reporta [typecheck] PASS + [unit-tests] FAIL", () => {
    const tmpRepo = createTempDir("controllab-fail-stages-");
    const mockBinDir = createTempDir("controllab-mock-fail-");
    const markerFile = path.join(tmpRepo, "unit_ran.marker");
    try {
      createSyntheticRepo(tmpRepo, { markerFile });
      const isolatedEnv = { ...process.env, PATH: mockBinDir };

      // 1. tsc retorna erro 2 -> testes unitários não devem rodar
      writeMockTsc(path.join(mockBinDir, "tsc"), { exitCode: 2 });
      let res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f7"],
        env: isolatedEnv,
        ...captureIo(),
      });
      assert.equal(res.exitCode, 2);
      assert.equal(res.typecheckStatus, "FAIL");
      assert.equal(fs.existsSync(markerFile), false);
      assert.match(res.stderr, /\[typecheck\] FAIL/);
      assert.match(res.stderr, /\[unit-tests\] FAIL/);

      // 2. tsc passa, mas teste unitário falha
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.mkdirSync(tmpRepo, { recursive: true });
      createSyntheticRepo(tmpRepo, { failingUnitTest: true });
      writeMockTsc(path.join(mockBinDir, "tsc"), { exitCode: 0 });
      res = runWebTests({
        repoRoot: tmpRepo,
        argv: ["--scope", "f7"],
        env: isolatedEnv,
        ...captureIo(),
      });
      assert.notEqual(res.exitCode, 0);
      assert.equal(res.typecheckStatus, "PASS");
      assert.equal(res.unitTestsStatus, "FAIL");
      assert.match(res.stdout, /^\[typecheck\] PASS/m);
      assert.match(res.stderr, /\[unit-tests\] FAIL/);
    } finally {
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.rmSync(mockBinDir, { recursive: true, force: true });
    }
  });

  await t.test("resolveTscCommand respeita precedência web/node_modules/.bin -> node_modules/.bin -> PATH -> null", () => {
    const tmpRepo = createTempDir("controllab-resolve-tsc-");
    const pathBinDir = createTempDir("controllab-path-tsc-");
    try {
      const emptyEnv = { ...process.env, PATH: createTempDir("controllab-empty-") };
      assert.equal(resolveTscCommand({ repoRoot: tmpRepo, env: emptyEnv }), null);

      writeMockTsc(path.join(pathBinDir, "tsc"));
      assert.equal(
        resolveTscCommand({ repoRoot: tmpRepo, env: { ...process.env, PATH: pathBinDir } }),
        "tsc"
      );

      const rootLocalTsc = path.join(tmpRepo, "node_modules", ".bin", "tsc");
      writeMockTsc(rootLocalTsc);
      assert.equal(
        resolveTscCommand({ repoRoot: tmpRepo, env: { ...process.env, PATH: pathBinDir } }),
        rootLocalTsc
      );

      const webLocalTsc = path.join(tmpRepo, "web", "node_modules", ".bin", "tsc");
      writeMockTsc(webLocalTsc);
      assert.equal(
        resolveTscCommand({ repoRoot: tmpRepo, env: { ...process.env, PATH: pathBinDir } }),
        webLocalTsc
      );

      fs.rmSync(emptyEnv.PATH, { recursive: true, force: true });
    } finally {
      fs.rmSync(tmpRepo, { recursive: true, force: true });
      fs.rmSync(pathBinDir, { recursive: true, force: true });
    }
  });
});
