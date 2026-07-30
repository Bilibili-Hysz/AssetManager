import { existsSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const projectRoot = process.cwd();
const vitestArgs = ['run', ...process.argv.slice(2)];

function runVitest(cwd) {
  const vitest = path.join(cwd, 'node_modules', 'vitest', 'vitest.mjs');
  return spawnSync(process.execPath, [vitest, ...vitestArgs], {
    cwd,
    stdio: 'inherit',
  });
}

function availableDrive() {
  for (let code = 'Z'.charCodeAt(0); code >= 'P'.charCodeAt(0); code -= 1) {
    const drive = `${String.fromCharCode(code)}:`;
    if (!existsSync(`${drive}\\`)) return drive;
  }
  throw new Error('No free drive letter is available for the Vitest path workaround.');
}

let result;
let cleanupResult;
if (process.platform === 'win32' && /[~#%]/.test(projectRoot)) {
  const drive = availableDrive();
  const repositoryRoot = path.dirname(projectRoot);
  const mappedRoot = `${drive}\\${path.basename(projectRoot)}`;
  const mapped = spawnSync('subst.exe', [drive, repositoryRoot], { stdio: 'inherit' });
  if (mapped.status !== 0) process.exit(mapped.status ?? 1);

  try {
    result = runVitest(mappedRoot);
  } finally {
    cleanupResult = spawnSync('subst.exe', [drive, '/d'], { stdio: 'inherit' });
  }
} else {
  result = runVitest(projectRoot);
}

if (result.error) throw result.error;
if (cleanupResult?.error) throw cleanupResult.error;
if (cleanupResult && cleanupResult.status !== 0) {
  throw new Error(`Failed to remove temporary Vitest drive mapping (${cleanupResult.status}).`);
}
process.exit(result.status ?? 1);
