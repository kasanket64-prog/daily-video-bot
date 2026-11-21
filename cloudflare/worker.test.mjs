import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { validateClaims, authenticate, validateMetadata, allowedApproval, parseTrends, prepareJob, uploadsComplete, fitnessTrends, selectFitnessClip, inspectionPassed, acceptPreview } from './worker.mjs';
import {liveToken,validateLiveToken,restorePinnedSourceWindows} from './worker.mjs';
import {validLivePlan} from './worker.mjs';

test('live editorial plans require bounded factual text and a visible facecam crop', () => {
  const good={usable:true,standout:true,highlight_type:'escape',title:'The red car gets away',hook:'Watch the red car',payoff:'The car escapes',facecam:{x:0,y:0,w:.25,h:.4}};
  assert.equal(Boolean(validLivePlan(good)),true);
  for(const change of [{usable:false},{standout:false},{standout:undefined},{standout:'true'},{highlight_type:undefined},{highlight_type:'idle_stakeout'},{hook:'a'.repeat(33)},{payoff:''},{facecam:{x:.9,y:0,w:.25,h:.4}},{facecam:{x:0,y:0,w:0,h:1}},{title:'two\nlines'}]){
    assert.equal(Boolean(validLivePlan({...good,...change})),false);
  }
});

test('live capability expires and cannot authorize another creator or a modified payload', async () => {
  const env={LIVE_CALLBACK_SECRET:'test'.repeat(16),LIVE_CHANNEL_ID:'UCeoZXkaJDtdTHafgoZeDcAA'};
  const claims={channel:env.LIVE_CHANNEL_ID,liveSource:'youtube:6MvZUbYzLEI',run_id:crypto.randomUUID(),exp:Math.floor(Date.now()/1000)+60};
  const request=token=>new Request('https://example.com/live/short-history',{method:'POST',headers:{Authorization:'Bearer '+token}});
  const token=await liveToken(env,claims);
  assert.deepEqual(await validateLiveToken(request(token),env),claims);
  await assert.rejects(validateLiveToken(request('a'+token),env));
  for(const change of [{channel:'another'},{exp:0},{exp:null},{liveSource:'other'},{run_id:'../other'}]){
    await assert.rejects(validateLiveToken(request(await liveToken(env,{...claims,...change})),env));
  }
  const response=await worker.fetch(request(token),{...env,GTA_REELS_ENABLED:'true',LIVE_WATCH_ENABLED:'false'});
  assert.equal(response.status,503);
});

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

test('a reviewed Clix live clip keeps Clix source attribution and rejects other creators', async () => {
  let saved;
  const env={LIVE_CALLBACK_SECRET:'test'.repeat(16),LIVE_CHANNEL_ID:'UCeoZXkaJDtdTHafgoZeDcAA',
    GTA_REELS_ENABLED:'true',LIVE_WATCH_ENABLED:'true',SHORT_PREVIEW_TEST:'true',
    DB:{prepare(){return {bind(...values){saved=values;return {async run(){return {meta:{changes:1}};}};}};}}};
  const token=await liveToken(env,{channel:env.LIVE_CHANNEL_ID,liveSource:'twitch:reviewed',run_id:crypto.randomUUID(),exp:Math.floor(Date.now()/1000)+60});
  const meta={source_id:'twitch:321495894240',creator:'clix',title:'Clix escapes the chase',hook:'Watch the escape',
    script:'Clix escapes the chase.',source_facts:"Clix's GTA VI marathon beginning November 18, 2026. Require genuine gameplay and Clix as the primary visible subject. Credit Clix with #Clix. No AI-generated footage, added logos, major story spoilers or negative false framing.",
    sources:['https://reachclipping.com/ClixGTA'],credit:'Ad | #Clix | twitch.tv/clix',category:'GTA 6 gameplay',
    slot:1,start:1795250000,duration:24,batchDay:new Date(Date.now()+19800000).toISOString().slice(0,10),
    analysis:Object.fromEntries(['angle','audience','story_arc','emotion','sound_plan','cta'].map(k=>[k,'Reviewed gameplay']))};
  const request=body=>new Request('https://example.com/live/short',{method:'POST',headers:{Authorization:'Bearer '+token},body:JSON.stringify(body)});
  assert.equal((await worker.fetch(request(meta),env)).status,200);
  const stored=JSON.parse(saved[2]);
  assert.equal(stored.creator,'clix');
  assert.ok(stored.sources.includes('https://www.twitch.tv/clix'));
  assert.ok(!stored.sources.includes('https://www.twitch.tv/lacy'));
  assert.match(stored.description,/#Clix/);
  assert.equal((await worker.fetch(request({...meta,creator:'unreviewed'}),env)).status,403);
});

test('owner review binds the upload key and inspection to one file and expires', async () => {
  const key = '1'.repeat(64);
  const keyHash = Buffer.from(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key))).toString('hex');
  const cfg = { GTA_REELS_ENABLED:'true', SHORT_PREVIEW_TEST:'true', OWNER_REVIEW_REEL:{
    id:'2026-11-21-g40-short', sha256:'2'.repeat(64), keyHash, expires:Date.now()/1000+60
  }};
  const request = (token) => new Request('https://example.com/owner-review/inspect', {method:'POST',
    headers:{Authorization:'Bearer '+token,'Content-Length':'77'},body:JSON.stringify({sha256:'3'.repeat(64)})});
  assert.equal((await worker.fetch(request('0'.repeat(64)),cfg)).status,403);
  assert.equal((await worker.fetch(request(key),cfg)).status,409);
  const other = {...cfg.OWNER_REVIEW_REEL, id:'2026-11-21-g39-short', keyHash:'0'.repeat(64)};
  const multi = {...cfg, OWNER_REVIEW_REEL:[cfg.OWNER_REVIEW_REEL,other]};
  const original = request(key);
  assert.equal((await worker.fetch(new Request(original.url+'?id='+other.id,original),multi)).status,403);
  assert.equal((await worker.fetch(request(key),multi)).status,409);
  cfg.OWNER_REVIEW_REEL.expires = 0;
  assert.equal((await worker.fetch(request(key),cfg)).status,404);
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

test('private connection checks refresh tokens without returning credentials or publishing', async () => {
  const key='1'.repeat(64);
  const keyHash=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(key))).toString('hex');
  const env={GTA_REELS_ENABLED:'true',WORKER_URL:'https://example.com',TELEGRAM_BOT_TOKEN:'private-bot',
    TELEGRAM_CHAT_ID:'7',TELEGRAM_WEBHOOK_SECRET:'private-webhook',YOUTUBE_CLIENT_ID:'private-id',
    YOUTUBE_CLIENT_SECRET:'private-client',YOUTUBE_REFRESH_TOKEN:'private-refresh',
    OWNER_REVIEW_REEL:{id:'2026-11-21-g39-short',sha256:'2'.repeat(64),keyHash,expires:Date.now()/1000+60}};
  const request=token=>new Request('https://example.com/owner-review/connections',{headers:{Authorization:'Bearer '+token}});
  const oldFetch=globalThis.fetch;
  let calls=0,invalid=false;
  globalThis.fetch=async url=>{
    calls++;
    if(url==='https://api.telegram.org/botprivate-bot/getWebhookInfo') return Response.json({ok:true,result:{url:env.WORKER_URL+'/telegram',pending_update_count:0}});
    assert.equal(url,'https://oauth2.googleapis.com/token');
    return invalid?Response.json({error:'invalid_grant',error_description:'private provider detail'},{status:400}):Response.json({access_token:'private-access'});
  };
  try {
    assert.equal((await worker.fetch(request('0'.repeat(64)),env)).status,403);
    assert.equal(calls,0);
    const good=await (await worker.fetch(request(key),env)).json();
    assert.equal(good.telegram.webhook_matches,true);
    assert.equal(good.youtube.refreshable,true);
    assert.equal(good.instagram.configured,false);
    invalid=true;
    const bad=await (await worker.fetch(request(key),env)).json();
    assert.deepEqual(bad.youtube,{configured:true,refreshable:false,error:'invalid_grant'});
    assert.ok(!JSON.stringify([good,bad]).includes('private-'));
    assert.equal(calls,4);
  } finally {globalThis.fetch=oldFetch;}
});

for (const live of [false, true]) test('GTA preview sends once with correct approval mode: ' + live, async () => {
  const id = live ? '2026-11-04-g01-short' : '2026-11-04-short-test';
  const data = new TextEncoder().encode('inspected video');
  const sha256 = Buffer.from(await crypto.subtle.digest('SHA-256', data)).toString('hex');
  const job = { run_id: '1', status: 'generating', expires: Date.now() / 1000 + 1000,
    metadata: JSON.stringify({ gta: true, title: "GTA VI", inspection: { passed: true, sha256 } }) };
  const DB = { prepare(sql) { return { bind(...values) { return {
    async first() { return job; },
    async run() {
      if (sql.includes("SET status='sending_preview'")) job.status = 'sending_preview';
      else [job.status, job.file_id, job.message_id] = values;
      return { meta: { changes: 1 } };
    }
  }; } }; } };
  let sends = 0;
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, { body }) => {
    assert.equal(url, 'https://api.telegram.org/botprivate/sendVideo');
    assert.equal(body.get('chat_id'), '7');
    assert.equal(body.has('reply_markup'), live);
    if (live) assert.equal(JSON.parse(body.get('reply_markup')).inline_keyboard[0][0].callback_data, 'approve:' + id);
    assert.equal(body.has('disable_notification'), false);
    assert.match(body.get('caption'), live ? /Approve this file/ : /cannot be published/);
    sends++;
    return Response.json({ ok: true, result: { video: { file_id: 'file' }, message_id: 42 } });
  };
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const request = new Request('https://bot.workers.dev/render/preview/' + id,
        { method: 'POST', headers: { 'Content-Length': String(data.length) }, body: data });
      assert.deepEqual(await (await acceptPreview(request, { ...env, DB, TELEGRAM_BOT_TOKEN: 'private' },
        { run_id: '1' }, id)).json(), { received: true });
    }
    assert.equal(sends, 1);
    assert.equal(job.status, live ? 'pending' : 'test_sent');
    const callback = { from: { id: 7 }, message: { chat: { id: 7, type: 'private' }, message_id: 42 } };
    assert.equal(allowedApproval(callback, job, env), live);
  } finally { globalThis.fetch = oldFetch; }
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
    const sign = async payload => {
      const input = base({ alg: 'RS256', kid: 'test-key' }) + '.' + base(payload);
      const signature = Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', pair.privateKey, new TextEncoder().encode(input))).toString('base64url');
      return input + '.' + signature;
    };
    const token = await sign(claims());
    const request = (token, path = '/render/job') => new Request('https://bot.workers.dev' + path,
      { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
    assert.equal((await authenticate(request(token), env)).run_id, '99');
    const input = token.slice(0, token.lastIndexOf('.'));
    await assert.rejects(authenticate(request(input + '.' + Buffer.alloc(256).toString('base64url')), env));
    await assert.rejects(authenticate(request(base({ alg: 'none' }) + '.' + base(claims()) + '.x'), env));

    const DB = { prepare: () => ({ run: async () => ({}), all: async () => ({ results: [] }) }) };
    const testEnv = { ...env, DB, SHORT_PREVIEW_TEST: 'true', AUTOMATION_ENABLED: 'true',
      TELEGRAM_BOT_TOKEN: 'private', TELEGRAM_WEBHOOK_SECRET: 'private' };
    const shortClaims = { ...claims(), workflow_ref: 'owner/repo/.github/workflows/trend-scout.yml@refs/heads/main' };
    const manual = await sign({ ...shortClaims, event_name: 'workflow_dispatch' });
    assert.equal((await worker.fetch(request(token), testEnv)).status, 403);
    assert.equal((await worker.fetch(request(await sign(shortClaims), '/render/short-history'), testEnv)).status, 403);
    assert.equal((await worker.fetch(request(manual, '/render/preview/2026-11-04-short'), testEnv)).status, 403);
    assert.equal((await worker.fetch(request(manual, '/render/preview/2026-11-04-short-test'),
      { ...testEnv, SHORT_PREVIEW_TEST: 'false' })).status, 403);
    assert.equal((await worker.fetch(request(manual, '/telegram'), testEnv)).status, 404);
    assert.deepEqual(await (await worker.fetch(request(manual, '/render/short-history'), testEnv)).json(), []);
    const gtaEnv = { ...testEnv, GTA_REELS_ENABLED: 'true', SHORT_PREVIEW_TEST: 'false' };
    assert.deepEqual(await (await worker.fetch(request(manual, '/render/short-inputs'), gtaEnv)).json(),
      { items: [], catalog: [], gta: true, previewOnly: false, batchDay: new Date(Date.now() + 19800000).toISOString().slice(0,10) });
    assert.equal((await worker.fetch(request(token), gtaEnv)).status, 403);
    let tick;
    await worker.scheduled(null, testEnv, { waitUntil(promise) { tick = promise; } });
    await tick;
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
  const live = {...privateEnv,GTA_REELS_ENABLED:'true',SHORT_PREVIEW_TEST:'true',LIVE_WATCH_ENABLED:'true'};
  assert.deepEqual(await (await worker.fetch(new Request('https://bot.workers.dev/health'),live)).json(),
    {service:'daily-video-approvals',enabled:true});
  assert.equal((await (await worker.fetch(new Request('https://bot.workers.dev/health'),{...live,LIVE_WATCH_ENABLED:'false'})).json()).enabled,false);
});

test('a pinned edit receives only its deployer-reviewed source interval without replacing an existing interval', async () => {
  const writes=[];
  const DB={prepare(sql){assert.match(sql,/start.*IS NULL/);return {bind(...args){return {async run(){writes.push(args);}}}}}};
  const reel={id:'2026-11-21-g39-short',sha256:'b'.repeat(64),metadata:{source_window:{start:1795250845,span:180}}};
  await restorePinnedSourceWindows({DB,OWNER_REVIEW_REEL:[reel,{...reel,sha256:'wrong'},{...reel,metadata:{source_window:{start:2,span:999}}}]});
  assert.deepEqual(writes,[[1795250845,180,reel.id,reel.sha256]]);
});
