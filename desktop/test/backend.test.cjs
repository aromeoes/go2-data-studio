const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { Backend } = require('../backend.cjs');
const { validateRuntime, runtimeEnvironment, DIMOS_SHA } = require('../backend.cjs');
const { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function runtimeFixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'go2-bundled-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const dir of ['.venv/bin', 'bin', 'deno-cache']) mkdirSync(path.join(root, dir), { recursive: true });
  for (const file of ['.venv/bin/python', 'bin/deno']) writeFileSync(path.join(root, file), '', { mode: 0o755 });
  writeFileSync(path.join(root, 'runtime.json'), JSON.stringify({format: 1, dimos_sha: DIMOS_SHA, platform: process.platform, arch: process.arch}));
  writeFileSync(path.join(root, 'deno-cache', 'seed'), 'offline dependencies');
  return root;
}

test('bundled runtime validates without Git and rejects a mismatched manifest', t => {
  const root = runtimeFixture(t);
  assert.equal(validateRuntime(root), path.join(root, '.venv/bin/python'));
  const manifestPath = path.join(root, 'runtime.json');
  const manifest = JSON.parse(readFileSync(manifestPath));
  for (const update of [{dimos_sha: 'wrong'}, {arch: 'wrong'}, {platform: 'wrong'}, {format: 2}]) {
    writeFileSync(manifestPath, JSON.stringify({...manifest, ...update}));
    assert.throws(() => validateRuntime(root), /does not match/);
  }
});

test('bundled backend excludes development paths and seeds a writable relay cache', t => {
  const root = runtimeFixture(t);
  const data = path.join(root, 'private-data');
  const env = runtimeEnvironment(root, data, '/packaged/app', {
    PATH: '/developer/bin', PYTHONPATH: '/developer/code', PYTHONHOME: '/developer/python',
    DENO_DIR: '/developer/cache', HOME: '/private-home',
  });
  assert.equal(env.PYTHONHOME, undefined);
  assert.equal(env.PYTHONPATH, '/packaged/app');
  assert.equal(env.PYTHONNOUSERSITE, '1');
  assert.equal(env.PYTHONDONTWRITEBYTECODE, '1');
  assert.ok(!env.PATH.includes('/developer'));
  assert.ok(env.PATH.startsWith(path.join(root, '.venv/bin')));
  assert.equal(env.HOME, '/private-home');
  assert.equal(readFileSync(path.join(env.DENO_DIR, 'seed'), 'utf8'), 'offline dependencies');
  writeFileSync(path.join(env.DENO_DIR, 'seed'), 'user cache');
  runtimeEnvironment(root, data, '/packaged/app', {});
  assert.equal(readFileSync(path.join(env.DENO_DIR, 'seed'), 'utf8'), 'user cache');
});

function fixture() {
  const backend = new Backend({ runtime: '/unused', data: '/unused', source: '/unused' });
  backend.child = new EventEmitter();
  backend.child.kill = signal => { backend.signal = signal; queueMicrotask(() => backend.child.emit('exit', 0)); };
  return backend;
}
test('quit never kills a connected or unreachable backend', async () => {
  for (const message of ['Save recording and disconnect', 'network error']) {
    const backend = fixture();
    backend.request = async () => { throw Error(message); };
    await assert.rejects(() => backend.quit(), { message });
    assert.equal(backend.signal, undefined);
  }
});
test('quit waits for the backend shutdown guard before signalling its own child', async () => {
  const backend = fixture();
  let release;
  backend.request = async (route, body) => {
    assert.equal(route, '/api/desktop/prepare-quit');
    assert.deepEqual(body, {});
    await new Promise(resolve => { release = resolve; });
    return { ok: true };
  };
  const quitting = backend.quit();
  assert.equal(backend.signal, undefined);
  release();
  await quitting;
  assert.equal(backend.signal, 'SIGTERM');
});
test('stopMotion requests a software stop, never posture or disconnect', async () => {
  const backend = fixture();
  backend.request = async route => { assert.equal(route, '/api/stop'); };
  await backend.stopMotion();
  assert.equal(backend.signal, undefined);
});
