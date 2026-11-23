import test from 'node:test';
import assert from 'node:assert/strict';
import { createApiClient } from '../api-client.mjs';

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

test('an expired write session is refreshed once and the explicit save is retried', async () => {
  const calls = [];
  let sessions = 0;
  let writes = 0;
  const client = createApiClient(async (url, options = {}) => {
    const path = new URL(url).pathname;
    calls.push([path, options.method || 'GET', options.headers || {}]);
    if (path.endsWith('/write-session')) {
      sessions += 1;
      return response(200, { write_token: `token-${sessions}` });
    }
    writes += 1;
    if (writes === 1) return response(403, { code: 'write_session_invalid', error: 'expired' });
    assert.equal(options.headers['X-HA-Inventory-Write-Token'], 'token-2');
    return response(201, { item: { id: 1 } });
  }, 'https://ha.example/api/v1/');

  const result = await client.request('items', { method: 'POST', body: '{"name":"Test"}' });
  assert.equal(result.item.id, 1);
  assert.equal(sessions, 2);
  assert.equal(writes, 2);
});

test('an Ingress 403 is not disguised as an expired write session', async () => {
  let sessions = 0;
  let writes = 0;
  const client = createApiClient(async (url) => {
    if (new URL(url).pathname.endsWith('/write-session')) {
      sessions += 1;
      return response(200, { write_token: 'valid' });
    }
    writes += 1;
    return response(403, { code: 'ingress_required', error: 'Ingress only' });
  }, 'https://ha.example/api/v1/');

  await assert.rejects(client.request('items/1', { method: 'PATCH', body: '{}' }), (error) => {
    assert.equal(error.status, 403);
    assert.equal(error.code, 'ingress_required');
    return true;
  });
  assert.equal(sessions, 1);
  assert.equal(writes, 1);
});

test('a repeated invalid token is not retried more than once', async () => {
  let sessions = 0;
  let writes = 0;
  const client = createApiClient(async (url) => {
    if (new URL(url).pathname.endsWith('/write-session')) {
      sessions += 1;
      return response(200, { write_token: `token-${sessions}` });
    }
    writes += 1;
    return response(403, { code: 'write_session_invalid', error: 'invalid' });
  }, 'https://ha.example/api/v1/');

  await assert.rejects(client.request('items', { method: 'POST', body: '{}' }));
  assert.equal(sessions, 2);
  assert.equal(writes, 2);
});
