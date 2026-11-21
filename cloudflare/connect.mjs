const encoder=new TextEncoder();
const now=()=>Math.floor(Date.now()/1000);
const random=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
const encode=bytes=>btoa(String.fromCharCode(...bytes));
const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'};
async function get(env,name){const row=await env.DB.prepare('SELECT value FROM settings WHERE name=?').bind(name).first();return row?JSON.parse(row.value):null;}
async function put(env,name,value){await env.DB.prepare('INSERT OR REPLACE INTO settings(name,value) VALUES(?,?)').bind(name,JSON.stringify(value)).run();}
async function take(env,name){
  const row=await env.DB.prepare('SELECT value FROM settings WHERE name=?').bind(name).first();
  if(!row) throw new Error('This connection link has expired. Request a fresh link.');
  const value=JSON.parse(row.value);
  if(value.expires<=now()) throw new Error('This connection link has expired. Request a fresh link.');
  const used=await env.DB.prepare('DELETE FROM settings WHERE name=? AND value=?').bind(name,row.value).run();
  if(!used.meta.changes) throw new Error('This connection step was already used. Please start again.');
  return value;
}
async function key(env){
  if(!/^[0-9a-f]{64}$/.test(env.SOCIAL_TOKEN_KEY||'')) throw new Error('Secure connection storage is not configured.');
  return crypto.subtle.importKey('raw',Uint8Array.from(env.SOCIAL_TOKEN_KEY.match(/../g),x=>parseInt(x,16)),{name:'AES-GCM'},false,['encrypt','decrypt']);
}
export async function saveConnection(env,name,value){
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:encoder.encode(name)},await key(env),encoder.encode(JSON.stringify(value)));
  await put(env,'social:secret:'+name,{iv:encode(iv),data:encode(new Uint8Array(encrypted))});
}
export async function readConnection(env,name){
  const saved=await get(env,'social:secret:'+name);
  if(!saved) return null;
  const plaintext=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(saved.iv),additionalData:encoder.encode(name)},await key(env),decode(saved.data));
  return JSON.parse(new TextDecoder().decode(plaintext));
}
export async function socialEnv(env){
  if(!env.DB||!env.SOCIAL_TOKEN_KEY) return env;
  const youtube=await readConnection(env,'youtube'),instagram=await readConnection(env,'instagram');
  return {...env,...(youtube?{YOUTUBE_REFRESH_TOKEN:youtube.refresh_token,YOUTUBE_PRIVACY:youtube.visibility}:{}),
    ...(instagram?{INSTAGRAM_ACCESS_TOKEN:instagram.access_token,INSTAGRAM_USER_ID:instagram.id,META_API_VERSION:instagram.version}:{})};
}
export async function issueConnectLink(env){
  await key(env);
  const token=random();
  await put(env,'social:link:'+await hash(token),{expires:now()+3600});
  return env.WORKER_URL+'/connect/'+token;
}
function redirect(location,extra={}){return new Response(null,{status:303,headers:{...headers,Location:location,...extra}});}
function page(body,status=200){
  return new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect your Reel bot</title><style>body{font:17px system-ui;max-width:680px;margin:30px auto;padding:16px;line-height:1.5;background:#101014;color:#f4f4f4}section{padding:18px;border:1px solid #555;border-radius:14px;margin:20px 0}a{color:#98c8ff}input,button,select{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;font:inherit;border-radius:8px}button{background:#a9ddff;color:#101014;border:0;cursor:pointer}code{overflow-wrap:anywhere}.note{color:#c4c4ce}</style><h1>Connect your Reel bot</h1>'+body+'</html>',
    {status,headers:{...headers,'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://accounts.google.com https://www.facebook.com; base-uri 'none'; frame-ancestors 'none'"}});
}
async function api(url,options={}){
  const response=await fetch(url,{...options,redirect:'manual',signal:AbortSignal.timeout(20000)});
  if(!response.ok) throw new Error(new URL(url).hostname.includes('google')?'Google did not accept this connection. Check the selected account and app settings, then try again.':'Meta did not accept this connection. Check app permissions, Page access and the linked professional Instagram account.');
  return response.json();
}
async function session(env,request){
  const token=/(?:^|;\s*)reel_connect=([a-f0-9]{64})(?:;|$)/.exec(request.headers.get('Cookie')||'')?.[1];
  if(!token) throw new Error('Open your private connection link first.');
  const id=await hash(token),saved=await get(env,'social:session:'+id);
  if(!saved||saved.expires<=now()) throw new Error('Your setup session expired. Request a fresh connection link.');
  return id;
}
async function start(env,provider,id){
  const state=random();
  await put(env,'social:state:'+await hash(state),{provider,session:id,expires:now()+600});
  const callback=env.WORKER_URL+'/connect/'+provider+'/callback';
  if(provider==='youtube'){
    if(!env.YOUTUBE_CLIENT_ID||!env.YOUTUBE_CLIENT_SECRET) throw new Error('YouTube client credentials are missing.');
    const url=new URL('https://accounts.google.com/o/oauth2/v2/auth');
    url.search=new URLSearchParams({client_id:env.YOUTUBE_CLIENT_ID,redirect_uri:callback,response_type:'code',
      scope:'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',access_type:'offline',prompt:'consent select_account',state});
    return redirect(url.href);
  }
  const app=await readConnection(env,'instagram-app');
  if(!app) throw new Error('Save your Meta app details below first.');
  const url=new URL('https://www.facebook.com/'+app.version+'/dialog/oauth');
  url.search=new URLSearchParams({client_id:app.id,redirect_uri:callback,response_type:'code',state,
    scope:'instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement',...(app.config_id?{config_id:app.config_id}:{})});
  return redirect(url.href);
}
async function callback(env,request,provider,id){
  const url=new URL(request.url),state=url.searchParams.get('state')||'';
  if(!/^[0-9a-f]{64}$/.test(state)) throw new Error('Invalid authorization state. Please start again.');
  const stateKey='social:state:'+await hash(state),expected=await get(env,stateKey);
  if(!expected||expected.provider!==provider||expected.session!==id) throw new Error('This authorization belongs to another setup session.');
  await take(env,stateKey);
  if(url.searchParams.has('error')) throw new Error('Authorization was declined. You can try again when ready.');
  const code=url.searchParams.get('code');
  if(!code||code.length>2048) throw new Error('Authorization code is missing. Please start again.');
  const redirect_uri=env.WORKER_URL+'/connect/'+provider+'/callback';
  if(provider==='youtube'){
    const token=await api('https://oauth2.googleapis.com/token',{method:'POST',body:new URLSearchParams({code,redirect_uri,
      client_id:env.YOUTUBE_CLIENT_ID,client_secret:env.YOUTUBE_CLIENT_SECRET,grant_type:'authorization_code'})});
    if(typeof token.refresh_token!=='string'||!token.scope?.split(' ').includes('https://www.googleapis.com/auth/youtube.upload')) throw new Error('Google did not grant offline upload access. Reconnect and grant the requested permissions.');
    const channels=await api('https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',{headers:{Authorization:'Bearer '+token.access_token}});
    const channel=channels.items?.[0];
    if(!channel||!/^UC[\w-]{22}$/.test(channel.id)) throw new Error('No YouTube channel was found for this account. Choose the account that owns your channel.');
    await saveConnection(env,'pending:youtube:'+id,{refresh_token:token.refresh_token,id:channel.id,name:channel.snippet?.title||channel.id,
      handle:channel.snippet?.customUrl||'',expires:now()+3600,grant_expires:Number.isFinite(token.refresh_token_expires_in)?now()+token.refresh_token_expires_in:null});
  }else{
    const app=await readConnection(env,'instagram-app');
    const base='https://graph.facebook.com/'+app.version+'/';
    const short=await api(base+'oauth/access_token',{method:'POST',body:new URLSearchParams({client_id:app.id,client_secret:app.secret,redirect_uri,code})});
    if(typeof short.access_token!=='string'||!short.access_token) throw new Error('Meta did not grant account access. Please reconnect.');
    const token=await api(base+'oauth/access_token',{method:'POST',body:new URLSearchParams({client_id:app.id,client_secret:app.secret,grant_type:'fb_exchange_token',fb_exchange_token:short.access_token})});
    if(typeof token.access_token!=='string'||!token.access_token) throw new Error('Meta did not grant long-lived access. Please reconnect.');
    // shortcut: lists the first 100 Pages; paginate if the owner manages more.
    const pages=await api(base+'me/accounts?limit=100&fields=id,name,access_token,instagram_business_account%7Bid,username%7D',{headers:{Authorization:'Bearer '+token.access_token}});
    const accounts=(pages.data||[]).filter(p=>/^\d+$/.test(p.instagram_business_account?.id||'')&&typeof p.access_token==='string')
      .map(p=>({id:p.instagram_business_account.id,name:p.instagram_business_account.username||p.name,page:p.name,access_token:p.access_token,version:app.version}));
    if(!accounts.length) throw new Error('No linked professional Instagram account was found. Link your Instagram Creator or Business account to a Facebook Page, then reconnect.');
    await saveConnection(env,'pending:instagram:'+id,{accounts,expires:now()+3600});
  }
  return redirect('/connect');
}
async function home(env,id){
  const youtube=await readConnection(env,'youtube'),instagram=await readConnection(env,'instagram');
  const pendingY=await readConnection(env,'pending:youtube:'+id),pendingI=await readConnection(env,'pending:instagram:'+id);
  const app=await readConnection(env,'instagram-app');
  const ycallback=env.WORKER_URL+'/connect/youtube/callback',icallback=env.WORKER_URL+'/connect/instagram/callback';
  let body='<p>Only clips you approve on Telegram can upload. Confirm each destination account below.</p>';
  body+='<section><h2>YouTube</h2><p>'+ (youtube?'Connected to '+escape(youtube.name)+' ('+escape(youtube.visibility)+').':'Not connected yet.')+'</p>';
  body+='<p>One-time Google setup: in your OAuth client, add this <strong>Authorized redirect URI</strong></p><p><code>'+escape(ycallback)+'</code></p><p><a href="https://console.cloud.google.com/auth/clients">Open Google OAuth clients</a>. Edit the existing client with this ID</p><p><code>'+escape(env.YOUTUBE_CLIENT_ID)+'</code></p><p>If the Google app Audience says <strong>Testing</strong>, move it to Production before reconnecting to avoid seven-day refresh tokens.</p><form method="post" action="/connect/youtube/start"><button>Sign in with the channel’s Google account</button></form>';
  if(pendingY?.expires>now()) body+='<h3>Confirm your channel</h3><p>'+escape(pendingY.name)+' '+escape(pendingY.handle)+'</p><p><a href="https://www.youtube.com/channel/'+escape(pendingY.id)+'">View this channel</a></p>'+(pendingY.grant_expires?'<p>This Google grant expires on '+escape(new Date(pendingY.grant_expires*1000).toISOString().slice(0,10))+'. Check your Google app publishing status if this is only seven days away.</p>':'')+'<form method="post" action="/connect/youtube/enable"><label>Upload visibility<select name="visibility"><option value="public">Public</option><option value="unlisted">Unlisted</option><option value="private">Private</option></select></label><button>Enable Telegram-approved uploads to this channel</button></form>';
  body+='</section><section><h2>Instagram</h2><p>'+(instagram?'Connected to @'+escape(instagram.name)+'.':'Not connected yet.')+'</p><p>Use an Instagram Creator or Business account linked to a Facebook Page you manage. Your Meta app needs Instagram publishing permissions and your Facebook account must have an app role.</p><p><a href="https://developers.facebook.com/apps/">Open Meta apps</a>. Add Facebook Login for Business and register this valid OAuth redirect URI</p><p><code>'+escape(icallback)+'</code></p><form method="post" action="/connect/instagram/app"><label>Meta app ID<input name="id" inputmode="numeric" required></label><label>Meta app secret<input type="password" name="secret" autocomplete="off" required></label><label>Facebook Login configuration ID, if provided<input name="config_id" inputmode="numeric"></label><button>Save app details securely</button></form>';
  if(app) body+='<p>App details saved. Version '+escape(app.version)+'.</p><form method="post" action="/connect/instagram/start"><button>Connect Instagram through Facebook</button></form>';
  if(pendingI?.expires>now()) body+='<h3>Choose your Instagram account</h3><form method="post" action="/connect/instagram/enable"><label>Account<select name="account">'+pendingI.accounts.map(a=>'<option value="'+escape(a.id)+'">@'+escape(a.name)+' — '+escape(a.page)+'</option>').join('')+'</select></label><button>Enable Telegram-approved Reels for this account</button></form>';
  return page(body+'</section><p class="note">This private setup session lasts one hour. Enter credentials only on this page or on Google and Meta’s official pages.</p>');
}
export async function connectRoute(request,env){
  try{
    if(new URL(request.url).origin!==new URL(env.WORKER_URL).origin) return page('<p>Wrong setup host.</p>',403);
    await key(env);
    const path=new URL(request.url).pathname;
    if(path==='/connect/admin-link'&&request.method==='POST'){
      const admin=JSON.parse(env.SOCIAL_SETUP_ADMIN||'{}');
      const token=/^Bearer ([a-f0-9]{64})$/.exec(request.headers.get('Authorization')||'')?.[1];
      if(!token||!/^[a-f0-9]{64}$/.test(admin.key||'')||!Number.isFinite(admin.expires)||admin.expires<=now()||
          await hash(token)!==await hash(admin.key)) return page('<p>Invalid setup authorization.</p>',403);
      return Response.json({url:await issueConnectLink(env)},{headers});
    }
    const link=/^\/connect\/([a-f0-9]{64})$/.exec(path);
    if(link&&request.method==='GET'){
      await take(env,'social:link:'+await hash(link[1]));
      const token=random();await put(env,'social:session:'+await hash(token),{expires:now()+3600});
      return redirect('/connect',{'Set-Cookie':'reel_connect='+token+'; Path=/connect; Secure; HttpOnly; SameSite=Lax; Max-Age=3600'});
    }
    const id=await session(env,request);
    if(path==='/connect'&&request.method==='GET') return home(env,id);
    const action=/^\/connect\/(youtube|instagram)\/(start|callback|enable|app)$/.exec(path);
    if(!action) return page('<p>Page not found.</p>',404);
    const [,provider,verb]=action;
    if(verb==='callback'&&request.method==='GET') return await callback(env,request,provider,id);
    if(request.method!=='POST'||request.headers.get('Origin')!==new URL(env.WORKER_URL).origin) return page('<p>Invalid setup request.</p>',403);
    if(Number(request.headers.get('Content-Length'))>8000) return page('<p>Form too large.</p>',413);
    if(verb==='start') return await start(env,provider,id);
    const raw=await request.text();
    if(raw.length>8000) return page('<p>Form too large.</p>',413);
    const form=new URLSearchParams(raw);
    if(provider==='instagram'&&verb==='app'){
      const app={id:form.get('id')?.trim(),secret:form.get('secret')?.trim(),config_id:form.get('config_id')?.trim()||'',version:'v27.0'};
      if(!/^\d+$/.test(app.id||'')||!/^[a-f0-9]{32}$/i.test(app.secret||'')||(app.config_id&&!/^\d+$/.test(app.config_id))) throw new Error('Copy the app ID and app secret exactly from Meta app settings.');
      await saveConnection(env,'instagram-app',app);return redirect('/connect');
    }
    if(verb==='enable'){
      const pending=await readConnection(env,'pending:'+provider+':'+id);
      if(!pending||pending.expires<=now()) throw new Error('This account confirmation expired. Please reconnect.');
      if(provider==='youtube'){
        const visibility=form.get('visibility');
        if(!['public','unlisted','private'].includes(visibility)) throw new Error('Choose an upload visibility.');
        await saveConnection(env,'youtube',{...pending,visibility});
      }else{
        const account=pending.accounts.find(a=>a.id===form.get('account'));
        if(!account) throw new Error('Choose one of your connected Instagram accounts.');
        await api('https://graph.facebook.com/'+account.version+'/'+account.id+'/content_publishing_limit?fields=config,quota_usage',{headers:{Authorization:'Bearer '+account.access_token}});
        await saveConnection(env,'instagram',account);
      }
      await env.DB.prepare('DELETE FROM settings WHERE name=?').bind('social:secret:pending:'+provider+':'+id).run();
      return redirect('/connect');
    }
    return page('<p>Page not found.</p>',404);
  }catch(error){
    const safe=error instanceof Error&&/^(This |Your |Open |Invalid |Authorization |Google |Meta |No |Choose |Copy |Secure |YouTube )/.test(error.message);
    return page('<h2>Connection needs attention</h2><p>'+escape(safe?error.message:'The connection could not be completed. Return to setup and try again.')+'</p><p><a href="/connect">Return to setup</a></p>',400);
  }
}
