import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { validateClaims, authenticate, validateMetadata, allowedApproval, parseTrends } from './worker.mjs';

const env = { REPOSITORY: 'owner/repo', REPOSITORY_ID: '123', OWNER_ID: '456', TELEGRAM_USER_ID: '7', TELEGRAM_CHAT_ID: '7' };
function claims() {
  return { iss: 'https://token.actions.githubusercontent.com', sub: 'repo:owner/repo:ref:refs/heads/main', aud: 'https://bot.workers.dev',
    repository: 'owner/repo', repository_id: '123', repository_owner_id: '456', ref: 'refs/heads/main',
    workflow_ref: 'owner/repo/.github/workflows/generate.yml@refs/heads/main', event_name: 'schedule',
    run_id: '99', iat: Math.floor(Date.now() / 1000) - 1, exp: Math.floor(Date.now() / 1000) + 120 };
}
test('workload identity rejects other repos, forks, branches, workflows, subjects, audiences and expired tokens', () => {
  assert.equal(validateClaims(claims(), env, 'https://bot.workers.dev').run_id, '99');
  assert.equal(validateClaims({ ...claims(), sub: 'repo:owner@456/repo@123:ref:refs/heads/main' }, env, 'https://bot.workers.dev').run_id, '99');
  for (const sub of ['repo:owner@999/repo@123:ref:refs/heads/main', 'repo:owner@456/repo@999:ref:refs/heads/main',
    'repo:owner@456/repo@123:ref:refs/heads/other']) {
    assert.throws(() => validateClaims({ ...claims(), sub }, env, 'https://bot.workers.dev'));
  }
  for (const [field, value] of [['repository', 'attacker/repo'], ['repository_id', '999'], ['repository_owner_id', '999'],
    ['ref', 'refs/heads/other'], ['workflow_ref', 'owner/repo/.github/workflows/other.yml@refs/heads/main'],
    ['sub', 'repo:attacker/repo:ref:refs/heads/main'], ['aud', 'https://attacker.example'], ['iss', 'https://attacker.example'],
    ['event_name', 'pull_request'], ['exp', 0], ['iat', 0]]) {
    assert.throws(() => validateClaims({ ...claims(), [field]: value }, env, 'https://bot.workers.dev'));
  }
});
test('identity signatures are verified cryptographically', async () => {
  const pair = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const jwk = { ...await crypto.subtle.exportKey('jwk', pair.publicKey), kid: 'test-key' };
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, 'https://token.actions.githubusercontent.com/.well-known/jwks');
    assert.equal(init.redirect, 'manual');
    return Response.json({ keys: [jwk] });
  };
  try {
    const base = value => Buffer.from(JSON.stringify(value)).toString('base64url');
    const input = base({ alg: 'RS256', kid: 'test-key' }) + '.' + base(claims());
    const signature = Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, new TextEncoder().encode(input))).toString('base64url');
    const request = token => new Request('https://bot.workers.dev/render/job', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
    assert.equal((await authenticate(request(input + '.' + signature), env)).run_id, '99');
    await assert.rejects(authenticate(request(input + '.' + Buffer.alloc(256).toString('base64url')), env));
    await assert.rejects(authenticate(request(base({ alg: 'none' }) + '.' + base(claims()) + '.x'), env));
  } finally { globalThis.fetch = oldFetch; }
});
test('only the owner can approve an exact, unexpired pending private preview', () => {
  const job = { status: 'pending', expires: Date.now() / 1000 + 3600, message_id: 42 };
  const callback = { from: { id: 7 }, message: { chat: { id: 7, type: 'private' }, message_id: 42 } };
  assert.equal(allowedApproval(callback, job, env), true);
  assert.equal(allowedApproval({ ...callback, from: { id: 8 } }, job, env), false);
  assert.equal(allowedApproval(callback, { ...job, message_id: 43 }, env), false);
  assert.equal(allowedApproval(callback, { ...job, status: 'approved' }, env), false);
  assert.equal(allowedApproval(callback, { ...job, expires: 0 }, env), false);
});
test('malformed AI output is rejected', () => {
  const meta = { title: 'A title', description: 'Description', script: 'A sufficiently long original spoken script.', language: 'hi', terms: ['space'] };
  assert.equal(validateMetadata(meta).language, 'hi');
  for (const value of [null, { ...meta, terms: [42] }, { ...meta, language: 'unknown' }, { ...meta, title: 'x'.repeat(101) }]) {
    assert.throws(() => validateMetadata(value));
  }
});
test('Google RSS CDATA and source URLs are read without executing instructions', () => {
  const result = parseTrends('<rss><channel><item><title><![CDATA[Space &amp; science]]></title><ht:news_item_url>https://example.com/a?x=1&amp;y=2</ht:news_item_url></item></channel></rss>');
  assert.equal(result[0].title, 'Space & science');
  assert.equal(result[0].sources[0], 'https://example.com/a?x=1&y=2');
  assert.throws(() => parseTrends('<rss/>'));
});
test('health never discloses credentials and disabled automation has no side effects', async () => {
  const privateEnv = { AUTOMATION_ENABLED: 'false', TELEGRAM_BOT_TOKEN: 'private-token' };
  const response = await worker.fetch(new Request('https://bot.workers.dev/health'), privateEnv);
  assert.equal((await response.text()).includes('private-token'), false);
  const disabled = await worker.fetch(new Request('https://bot.workers.dev/render/job', { method: 'POST' }), privateEnv);
  assert.equal(disabled.status, 503);
});
