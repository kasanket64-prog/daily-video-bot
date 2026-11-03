import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { validateClaims, authenticate, validateMetadata, allowedApproval, parseTrends, prepareJob, uploadsComplete, fitnessTrends, selectFitnessClip, inspectionPassed, acceptPreview } from './worker.mjs';

test('inspector requires every explicit check and never treats missing or string checks as passed', () => {
  const checks = { facts_supported: true, visuals_relevant: true, captions_readable: true, narration_matches: true, hook_clear: true };
  assert.equal(inspectionPassed(checks), true);
  for (const key of Object.keys(checks)) {
    assert.equal(inspectionPassed({ ...checks, [key]: false }), false);
    assert.equal(inspectionPassed({ ...checks, [key]: 'true' }), false);
    const incomplete = { ...checks }; delete incomplete[key];
    assert.equal(inspectionPassed(incomplete), false);
  }
  assert.equal(inspectionPassed(null), false);
});

test('preview cannot bypass inspection or substitute a different video after inspection', async () => {
  const data = new TextEncoder().encode('different video');
  let mutations = 0;
  for (const inspection of [undefined, { passed: false }, { passed: true, sha256: 'a'.repeat(64) }]) {
    const job = { run_id: '1', status: 'generating', expires: Date.now() / 1000 + 1000, metadata: JSON.stringify({ inspection }) };
    const DB = { prepare() { return { bind() { return { async first() { return job; }, async run() { mutations++; } }; } }; } };
    const request = new Request('https://example.com/render/preview/2026-11-04', { method: 'POST', headers: { 'Content-Length': String(data.length) }, body: data });
    assert.equal((await acceptPreview(request, { DB }, { run_id: '1' }, '2026-11-04')).status, 409);
  }
  assert.equal(mutations, 0);
});

test('Fit-zee ignores unrelated news and chooses a practical fitness topic', () => {
  const fallback = fitnessTrends([{ title: 'Bayern Munich', sources: ['https://example.com'] }], '2026-11-04');
  assert.equal(fallback.length, 1);
  assert.ok(fallback[0].sources[0].startsWith('https://www.'));
  assert.ok(fallback[0].facts.length > 30);
  assert.notEqual(fallback[0].title, 'Bayern Munich');
  const fitness = [{ title: 'Walking exercise', sources: [] }];
  assert.notEqual(fitnessTrends(fitness)[0].title, 'Walking exercise');
});

test('footage matching rejects dogs, unrelated landscapes, and duplicate clips', () => {
  const hit = (tags, url) => ({ tags, videos: { medium: { url, width: 720, height: 1280 } } });
  const dog = hit('dog, training, exercise', 'https://cdn.pixabay.com/dog.mp4');
  const city = hit('city, landscape, Munich', 'https://cdn.pixabay.com/city.mp4');
  const squat = hit('squat, fitness, gym', 'https://cdn.pixabay.com/squat.mp4');
  assert.equal(selectFitnessClip([dog, city, squat], 'squat exercise'), squat);
  assert.equal(selectFitnessClip([dog, city], 'exercise'), undefined);
  assert.equal(selectFitnessClip([squat], 'squat exercise', new Set([squat.videos.medium.url])), undefined);
});

const env = { REPOSITORY: 'owner/repo', REPOSITORY_ID: '123', OWNER_ID: '456', TELEGRAM_USER_ID: '7', TELEGRAM_CHAT_ID: '7' };
test('YouTube-only approval completes without uploading to an unconfigured Instagram account', () => {
  assert.equal(uploadsComplete({ youtube_state: 'uploaded' }, {}), true);
  assert.equal(uploadsComplete({ youtube_state: 'started' }, {}), false);
  const instagram = { INSTAGRAM_ACCESS_TOKEN: 'token', INSTAGRAM_USER_ID: '1', META_API_VERSION: 'v1.0' };
  assert.equal(uploadsComplete({ youtube_state: 'uploaded' }, instagram), false);
  assert.equal(uploadsComplete({ youtube_state: 'uploaded', instagram_state: 'uploaded' }, instagram), true);
});

test('stock rate limiting produces an original-background job without hammering the stock API', async () => {
  const meta = { trend_index: 0, title: 'Daily explainer', language: 'en', script: 'An original explainer script with enough text for validation.',
    description: 'An original explainer.', terms: ['city', 'nature', 'exercise'] };
  const DB = { prepare() { return { bind() { return { async first() { return null; }, async run() { return { meta: { changes: 1 } }; } }; } }; } };
  let stockRequests = 0;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async url => {
    if (url.includes('trends.google.com')) return new Response('<rss><item><title>Daily topic</title></item></rss>');
    if (url.includes('generativelanguage.googleapis.com')) return Response.json({ candidates: [{ content: { parts: [{ text: JSON.stringify(meta) }] } }] });
    assert.equal(new URL(url).hostname, 'pixabay.com');
    stockRequests++;
    return new Response('', { status: 429 });
  };
  try {
    const result = await (await prepareJob({ DB, GEMINI_API_KEY: 'private', PIXABAY_API_KEY: 'private' }, { run_id: '1' })).json();
    assert.deepEqual(result.metadata.materials, []);
    assert.match(result.metadata.footage_note, /original backgrounds/);
    assert.equal(stockRequests, 1);
  } finally { globalThis.fetch = oldFetch; }
});
test('failed preparation can retry while completed previews are never reserved again', async () => {
  let job = null, reservations = 0, requests = 0;
  const DB = { prepare(sql) { return { bind(...values) { return {
    async first() { return job; },
    async run() {
      if (sql.startsWith('INSERT INTO jobs')) {
        reservations++;
        job = { id: values[0], run_id: values[1], status: 'preparing' };
      } else if (sql.startsWith("UPDATE jobs SET status='failed'")) job.status = 'failed';
      return { meta: { changes: 1 } };
    }
  }; } }; } };
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async () => { requests++; return new Response('', { status: 503 }); };
  try {
    await assert.rejects(prepareJob({ DB }, { run_id: '1' }), /Trend feed unavailable/);
    assert.equal(job.status, 'failed');
    await assert.rejects(prepareJob({ DB }, { run_id: '2' }), /Trend feed unavailable/);
    assert.equal(reservations, 2);
    job.status = 'ready';
    assert.deepEqual(await (await prepareJob({ DB }, { run_id: '3' })).json(), { skip: true });
    assert.equal(reservations, 2);
    assert.equal(requests, 2);
  } finally { globalThis.fetch = oldFetch; }
});
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
