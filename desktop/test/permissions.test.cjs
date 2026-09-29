const { test } = require('node:test');
const assert = require('node:assert/strict');
const { allowPermission } = require('../permissions.cjs');
const origin = 'http://127.0.0.1:1234';
test('only the local main frame may capture audio, never camera or display', () => {
  assert.equal(allowPermission(origin, origin, 'media', {mediaTypes:['audio']}), true);
  assert.equal(allowPermission(origin, origin, 'media', {mediaType:'audio',origin}), true);
  for (const details of [{mediaTypes:['audio','video']}, {mediaTypes:['video']}, {}, {mediaType:'unknown'}, {mediaType:'audio',isMainFrame:false}, {mediaType:'audio',origin:'https://evil.example'}]) {
    assert.equal(allowPermission(origin, origin, 'media', details), false);
  }
  assert.equal(allowPermission(origin, 'https://evil.example', 'media', {mediaTypes:['audio']}), false);
  assert.equal(allowPermission(origin, origin, 'display-capture'), false);
});
