const { spawn, execFileSync } = require('node:child_process');
const { randomBytes, createHash } = require('node:crypto');
const { mkdirSync, createWriteStream, accessSync, constants, existsSync, readFileSync, cpSync, renameSync, rmSync } = require('node:fs');
const path = require('node:path');
const net = require('node:net');

const DIMOS_SHA = 'c1c3cdc9d2ee54ca72259465688395699d7d99a2';

function validateRuntime(runtime) {
  const python = path.join(runtime, '.venv', 'bin', 'python');
  accessSync(python, constants.X_OK);
  const manifestPath = path.join(runtime, 'runtime.json');
  if (existsSync(manifestPath)) {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    if (manifest.format !== 1 || manifest.dimos_sha !== DIMOS_SHA ||
        manifest.platform !== process.platform || manifest.arch !== process.arch) {
      throw new Error('The bundled DimOS runtime does not match this application or computer.');
    }
    accessSync(path.join(runtime, 'bin', 'deno'), constants.X_OK);
    return python;
  }
  const sha = execFileSync('git', ['-C', runtime, 'rev-parse', 'HEAD'], { encoding: 'utf8', timeout: 5000 }).trim();
  if (sha !== DIMOS_SHA) throw new Error(`This build requires DimOS ${DIMOS_SHA}.`);
  return python;
}

function runtimeEnvironment(runtime, data, source, inherited = process.env) {
  const env = { ...inherited };
  delete env.PYTHONHOME;
  const bundled = existsSync(path.join(runtime, 'runtime.json'));
  const paths = [path.join(runtime, '.venv/bin'), path.join(runtime, 'bin')];
  // Finder launches with a minimal PATH. Packaged builds use only their own
  // executables and system tools. Development previews can still use Homebrew.
  paths.push(...(bundled ? ['/usr/bin', '/bin', '/usr/sbin', '/sbin'] :
    [env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin']));
  Object.assign(env, {
    PATH: paths.join(path.delimiter), PYTHONPATH: source, PYTHONNOUSERSITE: '1',
    PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1',
    DYLD_FALLBACK_LIBRARY_PATH: path.join(runtime, 'lib'),
    DIMOS_RUNTIME: runtime, GO2_SPACES: data,
    DIMOS_RUN_LOG_DIR: path.join(data, 'logs'), NUMBA_CACHE_DIR: path.join(data, 'numba-cache'),
  });
  if (bundled && process.platform === 'linux') {
    // Steam injects its game runtime and overlay loader settings. Python/DimOS
    // must use the shipped libraries, not Steam's alternate C++/OpenSSL stack.
    delete env.LD_PRELOAD;
    env.LD_LIBRARY_PATH = path.join(runtime, 'lib');
  }
  if (bundled) {
    // Deno writes compilation/cache metadata. Seed a private writable cache,
    // keeping the installed application itself immutable.
    const cacheId = createHash('sha256').update(readFileSync(path.join(runtime, 'runtime.json'))).digest('hex').slice(0, 16);
    const denoCache = path.join(data, 'cache', 'deno-' + cacheId);
    if (!existsSync(denoCache)) {
      const staging = denoCache + '.' + randomBytes(8).toString('hex');
      try {
        cpSync(path.join(runtime, 'deno-cache'), staging, { recursive: true });
        renameSync(staging, denoCache);
      } finally { rmSync(staging, { recursive: true, force: true }); }
    }
    env.DENO_DIR = denoCache;
    env.DENO_NO_UPDATE_CHECK = '1';
  }
  return env;
}

async function freePorts(count) {
  const servers = [];
  try {
    for (let i = 0; i < count; i++) {
      const server = net.createServer();
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, '127.0.0.1', resolve);
      });
      servers.push(server);
    }
    return servers.map(server => server.address().port);
  } finally {
    await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))));
  }
}

class Backend {
  constructor({ runtime, data, source, robotEnv, replayOnly = false }) {
    Object.assign(this, { runtime, data, source, robotEnv, replayOnly });
    this.token = randomBytes(32).toString('hex');
    this.child = null;
    this.exited = false;
  }
  async start() {
    const python = validateRuntime(this.runtime);
    const [port, runtimePort, relayPort] = await freePorts(3);
    this.origin = `http://127.0.0.1:${port}`;
    mkdirSync(path.join(this.data, 'logs'), { recursive: true, mode: 0o700 });
    this.log = createWriteStream(path.join(this.data, 'logs', 'desktop-backend.log'), { flags: 'a', mode: 0o600 });
    this.child = spawn(python, ['-m', 'go2_setup.api'], {
      cwd: this.source,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...runtimeEnvironment(this.runtime, this.data, this.source),
        GO2_ENV_FILE: this.robotEnv,
        GO2_SETUP_PORT: String(port),
        GO2_RUNTIME_PORT: String(runtimePort),
        GO2_RELAY_PORT: String(relayPort),
        GO2_DESKTOP_TOKEN: this.token,
        GO2_REPLAY_ONLY: this.replayOnly ? '1' : '0',
        DIMOS_RUN_LOG_DIR: path.join(this.data, 'logs'),
        NUMBA_CACHE_DIR: path.join(this.data, 'numba-cache'),
      },
    });
    this.child.stdout.pipe(this.log, { end: false });
    this.child.stderr.pipe(this.log, { end: false });
    this.child.once('exit', () => { this.exited = true; this.log.end(); this.onExit?.(); });
    this.child.once('error', error => { this.spawnError = error; this.exited = true; });
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      if (this.exited) throw new Error('DimOS could not start. Inspect desktop-backend.log in the data folder.');
      try {
        const status = await this.request('/api/desktop/status');
        if (status.pid !== this.child.pid || status.dimos_sha !== DIMOS_SHA) {
          throw new Error('The local service identity does not match this application.');
        }
        return;
      } catch (error) {
        if (error.message.includes('identity')) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    throw new Error('DimOS startup timed out. Inspect desktop-backend.log.');
  }
  async request(route, body) {
    const response = await fetch(this.origin + route, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-Go2-Desktop': this.token, 'X-Go2-Request': '1', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Local service request failed');
    return data;
  }
  async stopMotion() {
    if (this.child && !this.exited) await this.request('/api/stop', {});
  }
  async quit() {
    if (!this.child || this.exited) return;
    // The backend atomically rejects shutdown with a session present and locks
    // out new connections before acknowledging. No forced termination fallback.
    await this.request('/api/desktop/prepare-quit', {});
    if (this.exited) return;
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('DimOS is still closing. Wait and try again.')), 30000);
      this.child.once('exit', () => { clearTimeout(timeout); resolve(); });
      this.child.kill('SIGTERM');
    });
  }
}
module.exports = { Backend, DIMOS_SHA, freePorts, validateRuntime, runtimeEnvironment };
