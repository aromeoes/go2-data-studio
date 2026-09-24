const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { Backend } = require('../backend.cjs');

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
