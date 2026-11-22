import test from 'node:test';
import assert from 'node:assert/strict';
import {saveConnection,readConnection,socialEnv,issueConnectLink,connectRoute} from './connect.mjs';
import worker from './worker.mjs';

test('public app information works without credentials or account access',async()=>{
  for(const path of ['/','/privacy','/terms']){
    const response=await worker.fetch(new Request('https://bot.example.com'+path),{});
    assert.equal(response.status,200);
    assert.match(response.headers.get('Content-Type'),/text\/html/);
    const html=await response.text();
    assert.match(html,/Daily Video Bot/);
    assert.ok(html.includes('href="/privacy"'));
    assert.ok(!html.includes('/connect/youtube/start'));
  }
});

function environment(){
  const rows=new Map();
  return {WORKER_URL:'https://bot.example.com',SOCIAL_TOKEN_KEY:'1'.repeat(64),
    YOUTUBE_CLIENT_ID:'existing-client',YOUTUBE_CLIENT_SECRET:'secret-client',YOUTUBE_REFRESH_TOKEN:'expired-refresh',rows,
    DB:{prepare(sql){return {bind(name,value){return {
      async first(){return rows.has(name)?{value:rows.get(name)}:null;},
      async run(){
        if(sql.startsWith('DELETE')){const changed=rows.has(name)&&(value===undefined||rows.get(name)===value);if(changed)rows.delete(name);return {meta:{changes:Number(changed)}};}
        rows.set(name,value);return {meta:{changes:1}};
      }
    };}};}}};
}
async function open(env){
  const url=await issueConnectLink(env);
  assert.equal((await connectRoute(new Request(url),env)).status,200);
  const response=await connectRoute(new Request(url,{method:'POST',headers:{Origin:env.WORKER_URL}}),env);
  assert.equal(response.status,303);
  const cookie=response.headers.get('Set-Cookie').split(';')[0];
  return (path,body)=>new Request(env.WORKER_URL+path,{method:body===undefined?'GET':'POST',
    headers:{Cookie:cookie,...(body===undefined?{}:{Origin:env.WORKER_URL,'Content-Type':'application/x-www-form-urlencoded'})},
    ...(body===undefined?{}:{body:new URLSearchParams(body)})});
}
test('social credentials are encrypted, bound to their record name and preferred only after activation',async()=>{
  const env=environment();
  assert.equal((await socialEnv(env)).YOUTUBE_REFRESH_TOKEN,'expired-refresh');
  await saveConnection(env,'youtube',{refresh_token:'new-private-refresh',visibility:'public',name:'My channel'});
  assert.ok(!JSON.stringify([...env.rows.values()]).includes('new-private-refresh'));
  assert.equal((await socialEnv(env)).YOUTUBE_REFRESH_TOKEN,'new-private-refresh');
  assert.equal((await socialEnv(env)).YOUTUBE_PRIVACY,'public');
  env.rows.set('social:secret:instagram',env.rows.get('social:secret:youtube'));
  await assert.rejects(readConnection(env,'instagram'));
});
test('private setup links are single-use and expired links and cross-origin forms are denied',async()=>{
  const env=environment(),url=await issueConnectLink(env);
  assert.equal((await connectRoute(new Request(env.WORKER_URL+'/connect'),env)).status,400);
  assert.equal((await connectRoute(new Request(url),env)).status,200);
  assert.equal((await connectRoute(new Request(url),env)).status,200);
  const first=await connectRoute(new Request(url,{method:'POST',headers:{Origin:env.WORKER_URL}}),env);
  assert.match(first.headers.get('Set-Cookie'),/Secure; HttpOnly; SameSite=Lax/);
  assert.equal((await connectRoute(new Request(url),env)).status,400);
  const request=await open(env);
  const home=await connectRoute(request('/connect'),env);
  assert.equal(home.status,200);
  assert.equal(home.headers.get('Referrer-Policy'),'no-referrer');
  assert.match(home.headers.get('Content-Security-Policy'),/frame-ancestors 'none'/);
  const forged=request('/connect/youtube/start',{});
  forged.headers.set('Origin','https://attacker.example.com');
  assert.equal((await connectRoute(forged,env)).status,403);
  const expired=await issueConnectLink(env);
  const last=[...env.rows.keys()].filter(x=>x.startsWith('social:link:')).at(-1);
  env.rows.set(last,JSON.stringify({expires:0}));
  assert.equal((await connectRoute(new Request(expired),env)).status,400);
});

test('issuing a setup link requires a separate unexpired bootstrap credential',async()=>{
  const env={...environment(),SOCIAL_SETUP_ADMIN:JSON.stringify({key:'3'.repeat(64),expires:Date.now()/1000+600})};
  const request=token=>new Request(env.WORKER_URL+'/connect/admin-link',{method:'POST',headers:{Authorization:'Bearer '+token}});
  assert.equal((await connectRoute(request('1'.repeat(64)),env)).status,403);
  assert.equal((await connectRoute(request('3'.repeat(64)),env)).status,200);
  env.SOCIAL_SETUP_ADMIN=JSON.stringify({key:'3'.repeat(64),expires:0});
  assert.equal((await connectRoute(request('3'.repeat(64)),env)).status,403);
});

test('browsers without Origin must present the private form token and cannot use another session',async()=>{
  const env=environment(),url=await issueConnectLink(env);
  const html=await (await connectRoute(new Request(url),env)).text();
  const csrf=/name="csrf" value="([a-f0-9]{64})"/.exec(html)[1];
  const post=(target,body,cookie)=>new Request(target,{method:'POST',headers:cookie?{Cookie:cookie}:{},body:new URLSearchParams(body)});
  assert.equal((await connectRoute(post(url,{}),env)).status,400);
  const opened=await connectRoute(post(url,{csrf}),env);
  assert.equal(opened.status,303);
  const cookie=opened.headers.get('Set-Cookie').split(';')[0];
  const home=await (await connectRoute(new Request(env.WORKER_URL+'/connect',{headers:{Cookie:cookie}}),env)).text();
  const sessionToken=/name="csrf" value="([a-f0-9]{64})"/.exec(home)[1];
  const start=env.WORKER_URL+'/connect/youtube/start';
  assert.equal((await connectRoute(post(start,{},cookie),env)).status,400);
  assert.equal((await connectRoute(post(start,{csrf},cookie),env)).status,400);
  assert.equal((await connectRoute(post(start,{csrf:sessionToken},cookie),env)).status,303);
  const foreign=post(start,{csrf:sessionToken},cookie);foreign.headers.set('Origin','https://attacker.example.com');
  assert.equal((await connectRoute(foreign,env)).status,403);
});
test('YouTube OAuth is session-bound, single-use and needs explicit channel confirmation',async()=>{
  const env=environment(),request=await open(env),other=await open(env);
  const started=await connectRoute(request('/connect/youtube/start',{}),env);
  const authorization=new URL(started.headers.get('Location'));
  assert.equal(authorization.origin,'https://accounts.google.com');
  assert.equal(authorization.searchParams.get('redirect_uri'),env.WORKER_URL+'/connect/youtube/callback');
  const state=authorization.searchParams.get('state');
  const callback='/connect/youtube/callback?code=one-time-code&state='+state;
  const old=globalThis.fetch;let exchanges=0;
  globalThis.fetch=async(url,init)=>{
    if(url==='https://oauth2.googleapis.com/token'){
      exchanges++;assert.equal(init.body.get('client_secret'),'secret-client');
      return Response.json({access_token:'private-access',refresh_token:'private-refresh',scope:'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'});
    }
    assert.equal(url,'https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true');
    return Response.json({items:[{id:'UC'+'a'.repeat(22),snippet:{title:'Channel <script>bad()</script>',customUrl:'@my-channel'}}]});
  };
  try{
    assert.equal((await connectRoute(other(callback),env)).status,400);
    assert.equal(exchanges,0);
    assert.equal((await connectRoute(request(callback),env)).status,303);
    assert.equal((await connectRoute(request(callback),env)).status,400);
    assert.equal(exchanges,1);
    assert.equal(await readConnection(env,'youtube'),null);
    const html=await (await connectRoute(request('/connect'),env)).text();
    assert.ok(!html.includes('private-refresh')&&!html.includes('private-access')&&!html.includes('secret-client'));
    assert.ok(!html.includes('<script>bad()'));
    assert.match(html,/&lt;script&gt;/);
    assert.equal((await connectRoute(request('/connect/youtube/enable',{visibility:'public'}),env)).status,303);
    assert.equal((await socialEnv(env)).YOUTUBE_REFRESH_TOKEN,'private-refresh');
    assert.equal((await socialEnv(env)).YOUTUBE_PRIVACY,'public');
  }finally{globalThis.fetch=old;}
});
test('Instagram setup keeps app and Page tokens private and only activates an owned publishing account',async()=>{
  const env=environment(),request=await open(env),old=globalThis.fetch;
  let tokenCalls=0,publishingChecks=0;
  globalThis.fetch=async(url)=>{
    if(url.endsWith('/oauth/access_token'))return Response.json({access_token:++tokenCalls===1?'short-private-token':'long-private-token'});
    if(url.includes('/me/accounts?'))return Response.json({data:[{id:'12',name:'My page',access_token:'page-private-token',instagram_business_account:{id:'12345',username:'my_instagram'}}]});
    assert.match(url,/\/12345\/content_publishing_limit\?/);publishingChecks++;
    return Response.json({data:[{quota_usage:0,config:{quota_total:100}}]});
  };
  try{
    assert.equal((await connectRoute(request('/connect/instagram/app',{id:'42',secret:'b'.repeat(32)}),env)).status,303);
    const started=await connectRoute(request('/connect/instagram/start',{}),env);
    const url=new URL(started.headers.get('Location'));
    assert.equal(url.origin,'https://www.facebook.com');
    assert.equal((await connectRoute(request('/connect/instagram/callback?code=one-time-code&state='+url.searchParams.get('state')),env)).status,303);
    const html=await (await connectRoute(request('/connect'),env)).text();
    assert.ok(!html.includes('page-private-token')&&!html.includes('long-private-token')&&!html.includes('b'.repeat(32)));
    assert.equal((await connectRoute(request('/connect/instagram/enable',{account:'999'}),env)).status,400);
    assert.equal(await readConnection(env,'instagram'),null);
    assert.equal((await connectRoute(request('/connect/instagram/enable',{account:'12345'}),env)).status,303);
    assert.equal(publishingChecks,1);
    const effective=await socialEnv(env);
    assert.equal(effective.INSTAGRAM_USER_ID,'12345');
    assert.equal(effective.INSTAGRAM_ACCESS_TOKEN,'page-private-token');
  }finally{globalThis.fetch=old;}
});
test('OAuth provider errors never echo credentials or activate an account',async()=>{
  const env=environment(),request=await open(env),old=globalThis.fetch;
  const started=await connectRoute(request('/connect/youtube/start',{}),env);
  const state=new URL(started.headers.get('Location')).searchParams.get('state');
  globalThis.fetch=async()=>Response.json({error:'invalid_client',error_description:'secret-client and private-access'},{status:400});
  try{
    const response=await connectRoute(request('/connect/youtube/callback?code=test&state='+state),env);
    assert.equal(response.status,400);
    assert.ok(!(await response.text()).includes('secret-client'));
    assert.equal(await readConnection(env,'youtube'),null);
  }finally{globalThis.fetch=old;}
});

test('paused Instagram hides its setup and blocks all connection actions',async()=>{
  const env={...environment(),INSTAGRAM_ENABLED:'false'},request=await open(env),old=globalThis.fetch;
  globalThis.fetch=async()=>{assert.fail('Paused Instagram must not contact Meta');};
  try{
    const html=await (await connectRoute(request('/connect'),env)).text();
    assert.match(html,/Instagram paused/);
    assert.ok(html.includes('/connect/youtube/start'));
    assert.ok(!html.includes('/connect/instagram/'));
    for(const action of ['app','start','enable','callback']){
      const call=action==='callback'?request('/connect/instagram/callback?code=test'):request('/connect/instagram/'+action,{});
      assert.equal((await connectRoute(call,env)).status,409);
    }
    assert.equal(await readConnection(env,'instagram'),null);
  }finally{globalThis.fetch=old;}
});

test('only the Telegram owner in the private approval chat can request a fresh setup link',async()=>{
  const env={...environment(),GTA_REELS_ENABLED:'true',LIVE_WATCH_ENABLED:'true',SHORT_PREVIEW_TEST:'true',
    TELEGRAM_BOT_TOKEN:'bot',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_USER_ID:'7',TELEGRAM_CHAT_ID:'7'};
  const old=globalThis.fetch;let sent=0;
  globalThis.fetch=async(url,{body})=>{
    if(url.endsWith('/sendMessage')){sent++;assert.match(JSON.parse(body).reply_markup.inline_keyboard[0][0].url,/^https:\/\/bot\.example\.com\/connect\/[a-f0-9]{64}$/);}
    return Response.json({ok:true,result:{}});
  };
  const request=(user,chatType='private')=>new Request(env.WORKER_URL+'/telegram',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':'secret'},
    body:JSON.stringify({callback_query:{id:'query',data:'connect-accounts',from:{id:user},message:{chat:{id:7,type:chatType},message_id:1}}})});
  try{
    assert.equal((await worker.fetch(request(8),env)).status,200);assert.equal(sent,0);
    assert.equal((await worker.fetch(request(7,'group'),env)).status,200);assert.equal(sent,0);
    assert.equal((await worker.fetch(request(7),env)).status,200);assert.equal(sent,1);
  }finally{globalThis.fetch=old;}
});
