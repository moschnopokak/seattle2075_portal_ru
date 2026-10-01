/* ===== Обновления от других игроков ===== */
async function poll(){
  if(!S||document.hidden)return;
  try{
    const r=await fetch('/api/state?since='+S.version,{headers:authHeaders(),credentials:'same-origin'});
    if(r.status===401){showLogin();return;}
    if(!r.ok)return;
    const j=await r.json();
    if(j.unchanged)return;
    applyState(j);
    render(true);
    if(curKey&&overlayOpen())openDetail(curKey,true);
  }catch(e){}
}
setInterval(poll,20000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});

/* ===== Вход ===== */
function setToken(t){TOKEN=t;try{t?sessionStorage.setItem(STORE_TOKEN,t):sessionStorage.removeItem(STORE_TOKEN);}catch(e){}}
function showLogin(denied){
  S=null;closePanel();
  document.getElementById('app-top').hidden=true;
  document.getElementById('banner').hidden=true;
  let h=`<section class="login"><h1>Сиэтл 2075</h1><p class="prose">Портал кампании: календарь, хроника и планы между сессиями.</p>`;
  if(/[?&]auth=failed/.test(location.search))h+=`<p class="err">Telegram не подтвердил вход. Попробуйте ещё раз.</p>`;
  if(LAUNCH.data&&!denied)h+=`<p class="err">Не удалось войти по данным из Telegram. Закройте портал и откройте его снова кнопкой «Календарь» в чате с ботом.</p>`;
  if(denied){
    h+=`<p class="quiet-line">Вашего Telegram нет в списке игроков.</p><p>Передайте мастеру этот номер, он добавит его в список: <b class="tgid">${esc(denied.tg_id)}</b></p><p><button type="button" class="btn" id="retry">Проверить ещё раз</button> <button type="button" class="btn plain" id="relogin">Войти под другим аккаунтом</button></p>`;
  }else if(CFG.bot_username){
    h+=`<p>Войдите через Telegram. Портал узнаёт игроков по их аккаунту, пароль не нужен.</p><div id="tg-login"></div><p class="muted small" style="margin-top:14px">Если кнопка входа не появилась, откройте портал из Telegram: кнопка «Календарь» в чате с ботом @${esc(CFG.bot_username)}.</p>`;
  }else{
    h+=`<p class="err">На сервере не указан BOT_USERNAME, вход через Telegram недоступен.</p>`;
  }
  if(CFG.dev_login)h+=`<form id="dev-login" class="dev"><p class="muted small">Режим проверки без Telegram (DEV_LOGIN=1). На рабочем сервере его нужно выключить.</p><div class="inline"><input name="tg" inputmode="numeric" placeholder="Telegram ID из players.toml" aria-label="Telegram ID"><button type="submit" class="btn">Войти</button></div></form>`;
  h+='</section>';
  document.getElementById('main').innerHTML=h;
  if(!denied&&CFG.bot_username){
    const s=document.createElement('script');
    s.async=true;s.src='https://telegram.org/js/telegram-widget.js?22';
    s.setAttribute('data-telegram-login',CFG.bot_username);s.setAttribute('data-size','large');
    // redirect: Telegram сам переводит браузер на /auth/telegram с подписанными данными (не требует eval, совместимо со строгим CSP);
    // callback: старый способ с JS-обработчиком, включается переменной TG_WIDGET_MODE=callback
    if(CFG.widget_mode==='callback')s.setAttribute('data-onauth','onTelegramAuth(user)');
    else s.setAttribute('data-auth-url','/auth/telegram');
    s.setAttribute('data-request-access','write');
    document.getElementById('tg-login').appendChild(s);
  }
  const retry=document.getElementById('retry');retry&&retry.addEventListener('click',boot);
  const rl=document.getElementById('relogin');rl&&rl.addEventListener('click',logout);
  const dev=document.getElementById('dev-login');
  dev&&dev.addEventListener('submit',async ev=>{ev.preventDefault();const r=await fetch('/api/auth/dev',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({tg_id:dev.elements.namedItem('tg').value})});if(r.ok){setToken((await r.json()).token);boot();}else toast('Вход не удался');});
}
window.onTelegramAuth=async user=>{
  const r=await fetch('/api/auth/widget',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(user)});
  let j=null;try{j=await r.json();}catch(e){}
  if(!r.ok){toast(errText(j));return;}
  setToken(j.token);boot();
};
async function logout(){
  await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'}).catch(()=>{});
  setToken(null);showLogin();
}
/* Данные запуска Mini App. Telegram кладёт их прямо в адрес страницы (#tgWebAppData=…),
   поэтому вход изнутри Telegram не зависит от загрузки скриптов с telegram.org. */
let LAUNCH={data:'',theme:''};
function launchParams(){
  const p=new URLSearchParams((location.hash||'').replace(/^#/,''));
  let data=p.get('tgWebAppData')||'',theme=p.get('tgWebAppThemeParams')||'';
  try{
    if(data){sessionStorage.setItem('seattle2075-initdata',data);if(theme)sessionStorage.setItem('seattle2075-theme',theme);}
    else{data=sessionStorage.getItem('seattle2075-initdata')||'';theme=sessionStorage.getItem('seattle2075-theme')||'';}
  }catch(e){}
  const tg=window.Telegram&&window.Telegram.WebApp;
  if(!data&&tg&&tg.initData)data=tg.initData;
  return {data,theme};
}
function themeFrom(json){
  try{const bg=JSON.parse(json).bg_color;if(!bg)return null;const n=parseInt(bg.slice(1),16);
    return (0.2126*(n>>16&255)+0.7152*(n>>8&255)+0.0722*(n&255))/255<0.5?'dark':'light';}catch(e){return null;}
}
function tgReady(){const tg=window.Telegram&&window.Telegram.WebApp;if(tg&&tg.initData){try{tg.ready();tg.expand&&tg.expand();}catch(e){}}}
async function webappLogin(){
  if(!LAUNCH.data)return false;
  try{
    const r=await fetch('/api/auth/webapp',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:LAUNCH.data})});
    if(!r.ok)return false;
    setToken((await r.json()).token);return true;
  }catch(e){return false;}
}
const getState=()=>fetch('/api/state',{headers:authHeaders(),credentials:'same-origin'});
async function boot(){
  try{CFG=await (await fetch('/api/config')).json();}catch(e){CFG={};}
  LAUNCH=launchParams();
  if(LAUNCH.data){
    const th=themeFrom(LAUNCH.theme);if(th)document.documentElement.dataset.theme=th;
    tgReady();window.addEventListener('load',tgReady);
    if(!TOKEN)await webappLogin();
  }
  let r=await getState();
  if(r.status===401&&LAUNCH.data&&await webappLogin())r=await getState();
  if(r.status===401){setToken(null);return showLogin();}
  if(r.status===403){let j=null;try{j=await r.json();}catch(e){}return showLogin((j&&j.detail)||{tg_id:'?'});}
  if(!r.ok){document.getElementById('main').innerHTML='<p class="err" style="padding-top:40px">Сервер не отвечает. Обновите страницу через минуту.</p>';return;}
  applyState(await r.json());
  document.getElementById('app-top').hidden=false;
  const want=new URLSearchParams(location.search).get('open');
  if(want){if(SECTIONS.some(x=>x.id===want&&(!x.gm||S.me.gm)))UI.section=want;try{history.replaceState(null,'',location.pathname+location.hash);}catch(e){}}
  render();
}
boot();

document.addEventListener('input',ev=>{if(ev.target.id==='hq'){UI.hq=ev.target.value;const f=document.getElementById('hq'),pos=f.selectionStart;render(true);const n=document.getElementById('hq');if(n){n.focus();try{n.setSelectionRange(pos,pos);}catch(e){}}return;}if(ev.target.id==='dq'){UI.dq=ev.target.value;const l=document.getElementById('dlist');if(l)l.innerHTML=dList();}});
