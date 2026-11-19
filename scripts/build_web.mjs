import { existsSync } from 'node:fs';
import { build } from '../web/node_modules/esbuild/lib/main.js';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { stampServiceWorker } from './stamp_service_worker.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const defaultPython = existsSync('/home/antigravity/.venv/bin/python')
  ? '/home/antigravity/.venv/bin/python'
  : 'python3';
const pythonBin = process.env.PYTHON || defaultPython;
const result = spawnSync(pythonBin, [path.join(root, 'scripts/build_release.py')], {cwd: root, stdio: 'inherit'});
if (result.status !== 0) process.exit(result.status || 1);
for (const [entry, output] of [['web/app/main.ts','app/main.js'], ['web/worker/pyodide_worker.ts','worker/pyodide_worker.js'], ['web/worker/service_worker.ts','service_worker.js']]) {
  await build({entryPoints:[path.join(root,entry)], outfile:path.join(root,'web/dist',output), bundle:true, format:'esm', platform:'browser', target:'es2022', legalComments:'none', charset:'utf8'});
}
// Generate the SBOM before fingerprinting: its dependency metadata is part of
// the cached release, while the final manifest contains the stamped worker hash.
const preliminary = spawnSync(pythonBin, [path.join(root, 'scripts/build_release.py'), '--manifest'], {cwd:root, stdio:'inherit'});
if (preliminary.status !== 0) process.exit(preliminary.status || 1);
await stampServiceWorker(path.join(root, 'web/dist'));
const manifest = spawnSync(pythonBin, [path.join(root, 'scripts/build_release.py'), '--manifest'], {cwd:root, stdio:'inherit'});
process.exit(manifest.status === 0 ? 0 : (manifest.status || 1));
