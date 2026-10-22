import test from 'node:test';
import assert from 'node:assert/strict';
import * as backup from '../static/backup.mjs';

const json = (status, value) => ({ ok: status >= 200 && status < 300, status, json: async () => value });

test('backup client sends session CSRF and credentials on writes', async () => {
  const calls = [];
  const api = backup.createBackupApi(async (url, options) => {
    calls.push({ url, options });
    return json(200, url.endsWith('api/session') ? { csrf: 'session-token' } : { ok: true });
  });
  await api.post('api/check', {});
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, '/memory/backup/api/session');
  assert.equal(calls[1].options.credentials, 'same-origin');
  assert.equal(calls[1].options.headers['X-CSRF-Token'], 'session-token');
  assert.equal(calls[1].options.headers['Content-Type'], 'application/json');
});

test('expired session refreshes without repeating a mutation', async () => {
  const calls = [];
  const api = backup.createBackupApi(async (url, options) => {
    calls.push({ url, method: options.method });
    return json(url.endsWith('api/run') ? 403 : 200, { csrf: 'fresh-token' });
  });
  await assert.rejects(api.post('api/run', {}), /会话.*再次/);
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(calls.filter(call => call.url.endsWith('api/session')).length, 2);
});

test('preconditions describe saved configuration rather than unsaved form values', () => {
  assert.deepEqual(backup.missingRequirements({}), ['私有仓库', 'GitHub Token', '恢复公钥']);
  assert.deepEqual(backup.missingRequirements({ repository: 'owner/repo', token_configured: true, key_fingerprint: 'sha256:key' }), []);
});

test('recovery key exports browser-compatible RSA3072 PKCS8 and public SPKI with OAEP SHA256', async () => {
  const pair = await backup.generateRecoveryKey();
  assert.match(pair.publicKeyPem, /^-----BEGIN PUBLIC KEY-----\n/);
  assert.match(pair.privateKeyPem, /^-----BEGIN PRIVATE KEY-----\n/);
  const bytes = pem => Uint8Array.from(atob(pem.replace(/-----[^-]+-----|\s/g, '')), c => c.charCodeAt(0));
  const privateKey = await crypto.subtle.importKey('pkcs8', bytes(pair.privateKeyPem), { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['decrypt']);
  const publicKey = await crypto.subtle.importKey('spki', bytes(pair.publicKeyPem), { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt']);
  assert.equal(publicKey.algorithm.modulusLength, 3072);
  const message = new TextEncoder().encode('recover this backup');
  const encrypted = await crypto.subtle.encrypt('RSA-OAEP', publicKey, message);
  assert.deepEqual(new Uint8Array(await crypto.subtle.decrypt('RSA-OAEP', privateKey, encrypted)), message);
});

test('release links only accept HTTPS GitHub release pages', () => {
  assert.equal(backup.safeReleaseUrl('https://github.com/owner/repo/releases/tag/backup-1'), 'https://github.com/owner/repo/releases/tag/backup-1');
  for (const url of ['javascript:alert(1)', 'http://github.com/owner/repo', 'https://evil.example/release', 'https://github.com@evil.example/x']) assert.equal(backup.safeReleaseUrl(url), null);
});
