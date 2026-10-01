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
  const packages = (info.packages || []).map(p => p.toLowerCase().replaceAll("_", "-"));
  if (!packages.includes("wirepod-vector-sdk==0.8.1") || !packages.includes("aiogrpc==1.8")) {
    throw new Error("Rebuild the runtime with the Vector SDK before packaging this version.");
  }
  for (const binary of ['.venv/bin/python', '.venv/bin/dimos', '.venv/bin/rerun', 'bin/deno']) {
    accessSync(path.join(runtime, binary), constants.X_OK);
  }
  accessSync(path.join(runtime, 'deno-cache'), constants.R_OK);
  const voice = JSON.parse(readFileSync(path.join(runtime, 'wirepod/runtime.json'), 'utf8'));
  if (voice.format !== 1 || voice.sha !== '347c45f7a4dba9adba7fa003c08248d301f19393' || voice.platform !== target || voice.arch !== arch) {
    throw new Error('Build the local wire-pod runtime for this platform before packaging.');
  }
  accessSync(path.join(runtime, 'wirepod/wirepod'), constants.X_OK);
  for (const file of ['dimensional.so', 'corresponding-source.tar.gz', 'assets/epod/ep.crt']) {
    accessSync(path.join(runtime, 'wirepod', file), constants.R_OK);
  }
};
