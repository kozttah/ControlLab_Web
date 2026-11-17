/** Bind browser update detection to the complete immutable release inventory.
 * SBOM is generated first; only the worker itself and the final manifest are
 * excluded to avoid a hash cycle. No timestamps or directory traversal order.
 */
import { createHash } from 'node:crypto';
import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export async function stampServiceWorker(dist) {
  const entries = [];
  async function visit(directory, prefix = '') {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const relative = prefix + item.name;
      if (item.isDirectory()) await visit(path.join(directory, item.name), relative + '/');
      else if (item.isFile() && !['service_worker.js', 'release-manifest.json'].includes(relative)) {
        const data = await readFile(path.join(directory, item.name));
        entries.push({ path: relative, size: data.length, sha256: createHash('sha256').update(data).digest('hex') });
      }
    }
  }
  await visit(dist);
  entries.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const fingerprint = createHash('sha256').update(JSON.stringify(entries)).digest('hex');
  const worker = path.join(dist, 'service_worker.js');
  const body = (await readFile(worker, 'utf8')).replace(/^\/\/ ControlLab release fingerprint sha256:[a-f0-9]{64}\n/, '');
  await writeFile(worker, `// ControlLab release fingerprint sha256:${fingerprint}\n${body}`);
  return fingerprint;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3) throw new Error('Usage: node scripts/stamp_service_worker.mjs DIST');
  console.log(await stampServiceWorker(path.resolve(process.argv[2])));
}
