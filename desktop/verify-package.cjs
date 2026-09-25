const { readFileSync, accessSync, constants } = require('node:fs');
const path = require('node:path');
const { DIMOS_SHA } = require('./backend.cjs');
module.exports = async context => {
  const target = context.electronPlatformName;
  const arch = target === 'darwin' ? 'arm64' : 'x64';
  const runtime = path.join(context.packager.projectDir, 'runtime');
  const info = JSON.parse(readFileSync(path.join(runtime, 'runtime.json'), 'utf8'));
  if (info.format !== 1 || info.dimos_sha !== DIMOS_SHA || info.platform !== target || info.arch !== arch) {
    throw new Error('Build the pinned runtime for the target platform before packaging the app.');
  }
  for (const binary of ['.venv/bin/python', '.venv/bin/dimos', '.venv/bin/rerun', 'bin/deno']) {
    accessSync(path.join(runtime, binary), constants.X_OK);
  }
  accessSync(path.join(runtime, 'deno-cache'), constants.R_OK);
};
