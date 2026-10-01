/* ===== Справочники ===== */
let CHARS=[],CN={gm:'Мастер'},GEN={gm:'мастера'};
const TYPES={
  meet:{name:'Встреча',hint:'Сцена между персонажами игроков. Разыгрывается в начале сессии или описывается текстом.',goal:'О чём разговор и чего хочет автор'},
  grow:{name:'Развитие',hint:'Повышение навыка или атрибута, новое заклинание, имплант, инициация. Вступает в силу после подтверждения мастером.',goal:'Что повышается и как персонаж этого добивается: учитель, практика, ритуал, операция'},
  deal:{name:'Дело',hint:'Личное дело персонажа: покупка, визит к контакту, лечение, работа в мастерской.',goal:'Что нужно сделать и зачем'},
  vow:{name:'Обещание',hint:'Обязательство персонажа: что обещано, кому и к какому сроку.',goal:'Кому, что обещано и чем грозит невыполнение'}
};
const STATUS={gm:'на проверке у мастера',reply:'ждёт ответа участников',resched:'нужна другая дата',ok:'подтверждено',done:'состоялось',failed:'сорвано',rejected:'отклонено мастером'};
const PENDING=['gm','reply','resched'], CLOSED=['done','failed','rejected'];
const TALK={open:'в обсуждении',closed:'обсуждение окончено'};
const ANS={'да':'участие подтверждено','нет':'отказ, нужна другая дата','ждёт':'ответа пока нет','сам':'по открытому приглашению'};
const stText=e=>e.type==='vow'&&e.status==='ok'?'действует':STATUS[e.status];
const stCls=s=>PENDING.includes(s)?'s-pending':s==='done'?'s-done':(s==='failed'||s==='rejected')?'s-failed':'';
const entryCls=e=>'t-'+e.type+' '+stCls(e.status)+' talk-'+(e.talk||'open');

/* ===== Состояние и связь с сервером ===== */
const STORE_CHAR='seattle2075-char', STORE_TOKEN='seattle2075-token';
let S=null, V='gm', CFG={}, TOKEN=null, busy=false;
try{TOKEN=sessionStorage.getItem(STORE_TOKEN);}catch(e){}
const UI={section:'now',cal:'lanes',span:'week',anchor:null,month:null,stage:null};

function applyState(st){
  S=st;
  CAL_START=st.calStart;CAL_END=st.calEnd;MONTH_LIST=buildMonths();
  CHARS=st.characters;
  CN=Object.fromEntries(CHARS.map(c=>[c.id,c.name]));CN.gm='Мастер';
  GEN=Object.fromEntries(CHARS.map(c=>[c.id,c.gen]));GEN.gm='мастера';
  if(st.me.gm){if(V!=='gm'&&!CN[V])V='gm';}
  else if(!st.me.chars.includes(V)){let saved=null;try{saved=localStorage.getItem(STORE_CHAR);}catch(e){}V=st.me.chars.includes(saved)?saved:(st.me.chars[0]||'');}
}
const authHeaders=()=>TOKEN?{'Authorization':'Bearer '+TOKEN}:{};
const RO=()=>!!(S&&S.me.gm&&V!=='gm');
function errText(j){if(!j)return 'Не удалось выполнить действие.';const d=j.detail;if(typeof d==='string')return d;if(Array.isArray(d))return 'Портал не принял запрос. Обновите страницу и попробуйте ещё раз.';return (d&&d.message)||'Не удалось выполнить действие.';}
/* От чьего имени действие, добавляется само (V). Форма листа персонажа сама называет персонажа, поэтому для неё keepChar=true. */
async function apiPost(path,body,onError,keepChar){
  if(RO()){toast('Предпросмотр: действия отключены');return null;}
  if(busy)return null;busy=true;
  try{
    const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',...authHeaders()},body:JSON.stringify(keepChar?body:{...body,char:V})});
    let j=null;try{j=await r.json();}catch(e){}
    if(r.status===401){showLogin();return null;}
    if(!r.ok){const m=errText(j);onError?onError(m):toast(m);return null;}
    if(j&&j.state)applyState(j.state);
    return j;
  }catch(e){toast('Нет связи с порталом. Проверьте интернет и попробуйте ещё раз.');return null;}
  finally{busy=false;}
}

/* ===== Видимость (для игрока сервер уже всё отфильтровал; здесь нужен предпросмотр мастера) ===== */
function viewChars(){if(!S.me.gm)return S.me.chars;if(V==='gm')return null;const p=S.players.find(p=>p.chars.includes(V));return p?p.chars:[V];}
function canSee(e){const vc=viewChars();if(!vc)return true;return e.vis!=='лично'||vc.includes(e.author)||e.who.some(c=>vc.includes(c));}
const winVisible=w=>!!w&&(V==='gm'||w.from<=S.now.date);
const winName=w=>V==='gm'&&w.gm?w.gm:w.name;
const winOf=s=>S.windows.find(w=>s>=w.from&&s<=w.to);
const rhythmVisible=r=>V==='gm'||r.vis!=='мастер';
const visEntries=()=>S.entries.filter(canSee);
const involves=(e,c)=>(e.who||[]).includes(c)||e.author===c;
const rhythmOn=s=>S.rhythm.filter(r=>rhythmVisible(r)&&rhythmHits(r,s));
const isActive=e=>!CLOSED.includes(e.status)&&(e.to||'9999-12-31')>=S.now.date;
const canWrite=e=>V==='gm'||involves(e,V);
const canJoin=e=>V!=='gm'&&e.open&&!involves(e,V)&&isActive(e);
const starOf=c=>S.entries.find(e=>isActive(e)&&(e.stars||[]).includes(c));
const EVERY=['каждый понедельник','каждый вторник','каждую среду','каждый четверг','каждую пятницу','каждую субботу','каждое воскресенье'];
const WD_DAT=['понедельникам','вторникам','средам','четвергам','пятницам','субботам','воскресеньям'];
const rhythmWhen=r=>r.monthDay?r.monthDay+'-го числа каждого месяца':r.wd.length>1?'по '+joinNames(r.wd.map(x=>WD_DAT[x])):EVERY[r.wd[0]];
/* Общие события: планы мастера с маской. Игрок видит только текст маски. */
function blocks(){
  if(V==='gm')return [];
  if(S.me.gm)return S.plan.filter(p=>p.cover&&p.cover.title).map(p=>({id:p.id,from:p.from,to:p.to,title:p.cover.title,note:p.cover.note||'',who:p.cover.who||[]}));
  return S.blocks||[];
}
const blockFor=(b,c)=>!b.who.length||b.who.includes(c);
const EYE='<svg class="ico eye" viewBox="0 0 12 12" role="img" aria-label="игроки видят как общее событие"><path d="M1 6s1.8-3.2 5-3.2S11 6 11 6 9.2 9.2 6 9.2 1 6 1 6z" fill="none" stroke="currentColor" stroke-width="1.1"/><circle cx="6" cy="6" r="1.5" fill="currentColor"/></svg>';
const whoText=e=>[...e.who.map(c=>CN[c]||c),...(e.open?['+']:[])].join(', ');

const LOCK='<svg class="lock" viewBox="0 0 12 12" role="img" aria-label="видят только участники и мастер"><rect x="2" y="5.2" width="8" height="5.8" rx="1" fill="currentColor"/><path d="M3.8 5.2V3.8a2.2 2.2 0 0 1 4.4 0v1.4" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';
const CHAT_ICO='<svg class="ico" viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 2h9v6h-5l-2.6 2.2V8H1.5z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>';
function marks(e){
  const n=(e.stars||[]).length;let h='';
  if(n)h+=`<b class="star" title="Приоритет: ${esc(joinNames(e.stars.map(c=>CN[c]||c)))}">★${n>1?n:''}</b>`;
  if(e.open)h+='<b class="plus" title="Можно попроситься">+</b>';
  if(e.vis==='лично')h+=LOCK;
  return h;
}
function chatMark(e){const n=(e.chat||[]).length;return n?`<span class="cc" title="${n} ${plural(n,'сообщение','сообщения','сообщений')} в обсуждении">${CHAT_ICO}${n}</span>`:'';}

/* ===== Каркас портала ===== */
const SECTIONS=[
  {id:'now',name:'Сегодня'},{id:'cal',name:'Календарь'},{id:'chron',name:'Хроника'},
  {id:'dossier',name:'Досье'},{id:'handouts',name:'Раздатки'},{id:'sheet',name:'Лист',needChar:true},{id:'map',name:'Карта'},
  {id:'gm',name:'Панель мастера',gm:true}
];
function renderTop(){
  document.getElementById('nav').innerHTML=SECTIONS.filter(s=>(!s.gm||V==='gm')&&(!s.needChar||V==='gm'||(viewChars()||[]).length)).map(s=>
    `<button type="button" data-nav="${s.id}" ${UI.section===s.id?'aria-current="page"':''}>${s.name}${s.id==='handouts'&&unseenHandouts()?`<b class="nav-badge" aria-label="новых: ${unseenHandouts()}">${unseenHandouts()}</b>`:''}</button>`).join('');
  let who='';
  if(S.me.gm){
    who=`<label class="viewas">Вид <select id="who-select" aria-label="Чьими глазами показать портал"><option value="gm" ${V==='gm'?'selected':''}>Мастер</option>${CHARS.map(c=>`<option value="${c.id}" ${V===c.id?'selected':''}>как видит ${esc(c.name)}</option>`).join('')}</select></label>`;
  }else if(S.me.chars.length>1){
    who=`<label class="viewas">Играю за <select id="who-select">${S.me.chars.map(c=>`<option value="${c}" ${V===c?'selected':''}>${esc(CN[c]||c)}</option>`).join('')}</select></label>`;
  }else{
    who=`<span class="viewas">${esc(S.me.name)}${S.me.chars[0]?', '+esc(CN[S.me.chars[0]]||''):''}</span>`;
  }
  const diaryBtn=V!=='gm'&&(viewChars()||[]).length?'<button type="button" class="btn plain" data-act="open-diary">Мой дневник</button>':'';
  document.getElementById('who-box').innerHTML=who+diaryBtn+'<button type="button" class="btn plain" data-act="open-prefs">Уведомления</button><button type="button" class="btn plain" data-act="logout">Выйти</button>';
  const banner=document.getElementById('banner');
  banner.hidden=!RO();
  banner.textContent=RO()?`Предпросмотр: так портал видит игрок, у которого есть ${CN[V]}. Действия отключены.`:'';
  document.body.classList.toggle('ro',RO());
}
function render(keepScroll){
  if(!S)return;
  if(UI.section==='map'){
    renderTop();document.body.classList.add('on-map');
    const tb=document.getElementById('app-top');document.documentElement.style.setProperty('--top-h',(tb?tb.offsetHeight:60)+'px');
    if(!document.getElementById('leaflet')){document.getElementById('main').innerHTML=rMap();initMap();}
    else{updateMapTools();refreshPlaces();}
    return;
  }
  document.body.classList.remove('on-map');
  if(ADDING||MOVING){ADDING=false;MOVING=null;PENDING_PLACES=false;}
  if(UI.section==='gm'&&V!=='gm')UI.section='now';
  const lw=document.getElementById('lanes-wrap'),sl=lw?lw.scrollLeft:0,sy=window.scrollY;
  renderTop();
  const f={now:rNow,cal:rCal,chron:rChron,gm:rGM,dossier:rDossier,handouts:rHandouts,sheet:rSheet}[UI.section];
  const dqEl=document.getElementById('dq'),dqFocus=!!dqEl&&document.activeElement===dqEl,dqPos=dqFocus?dqEl.selectionStart:0;
  const html=f(),sec=SECTIONS.find(x=>x.id===UI.section);
  document.getElementById('main').innerHTML=(html.includes('<h1')?'':`<h1 class="sr-only">${sec?sec.name:''}</h1>`)+html;
  if(dqFocus){const n=document.getElementById('dq');if(n){n.focus();try{n.setSelectionRange(dqPos,dqPos);}catch(e){}}}
  if(UI.section==='gm')gmLoadExtras();
  if(UI.section==='cal'&&UI.cal==='lanes'){fitLanes();if(keepScroll){const w=document.getElementById('lanes-wrap');if(w)w.scrollLeft=sl;}else scrollToNow();}
  if(keepScroll)window.scrollTo(0,sy);
}

/* ===== Строки списков ===== */
function row(key,cls,title,sub,pre,post){return `<button type="button" class="row ${cls}" data-open="${key}"><i class="sw"></i><span class="rt">${pre||''}${esc(title)}${post?' '+post:''}</span>${sub?`<span class="rs">${esc(sub)}</span>`:''}</button>`;}
const entryRow=(e,sub)=>row('e:'+e.id,entryCls(e),e.title,sub,marks(e),chatMark(e));
function priorityList(){
  const list=S.entries.filter(e=>isActive(e)&&(e.stars||[]).length).sort((a,b)=>a.from<b.from?-1:1);
  return list.length?list.map(e=>entryRow(e,'★ '+joinNames(e.stars.map(c=>CN[c]||c))+', '+fDate(e.from))).join(''):'<p class="muted" style="margin:0">Звёзд пока никто не поставил.</p>';
}

/* ===== Сегодня ===== */
function dayItems(d,first){
  const starts=[],cont=[];
  const put=(from,to,html,title)=>{if(to<first)return;const st=from<first?first:from;if(d===st)starts.push(html);else if(d>st&&d<=to)cont.push(title);};
  if(V==='gm')S.plan.forEach(p=>put(p.from,p.to,row('g:'+p.id,'k-plan',p.title,[p.cover?'игроки видят: «'+p.cover.title+'»':'план мастера',p.to>d?'до '+fDate(p.to):''].filter(Boolean).join(', '),p.cover?EYE+' ':''),p.title));
  else blocks().forEach(b=>{if(blockFor(b,V))put(b.from,b.to,row('b:'+b.id,'k-block',b.title,['общее событие',b.to>d?'до '+fDate(b.to):''].filter(Boolean).join(', ')),b.title);});
  visEntries().forEach(e=>{
    if(V!=='gm'&&!involves(e,V))return;
    const to=e.to||e.from;
    const sub=[V==='gm'?joinNames(e.who.map(c=>CN[c]||c)):'',to>d?'до '+fDate(to):'',stText(e)].filter(Boolean).join(', ');
    put(e.from,to,entryRow(e,sub),e.title);
  });
  return {starts,cont};
}
function quietText(){
  const n=S.now.date,q=S.quietUntil;
  return q&&q>=n
    ?`<p class="quiet-line">Свободное время гарантировано до ${WD_GEN[wdi(q)]}, ${fDate(q)} включительно.</p><p class="muted">После этой даты может прийти новое задание, и планы могут сорваться.</p>`
    :`<p class="quiet-line">Свободное время не гарантировано.</p><p class="muted">Новое задание может прийти в любой день.</p>`;
}
function rNow(){
  const n=S.now,w=winOf(n.date);
  let h=`<section class="now-hero"><div><p class="now-kicker">Дата в игре</p>
    <div class="now-date"><div class="now-wd">${cap(WD[wdi(n.date)])}</div><div class="now-dm">${fDate(n.date)} 2075</div><div class="now-tod">${n.tod}</div></div></div>
    <div class="now-window">${winVisible(w)?`<p class="win-name">Этап: ${esc(winName(w))}</p>`:''}${quietText()}<button type="button" class="btn primary" data-act="add">Добавить запись</button></div>
  </section><div class="now-body"><div>`;
  h+=`<h2>${V==='gm'?'Все планы на 7 дней':'Мои планы на 7 дней'}</h2>`;
  for(const d of range(n.date,addDays(n.date,6))){
    const {starts,cont}=dayItems(d,n.date);
    const empty=!starts.length&&!cont.length;
    h+=`<div class="dl-day ${d===n.date?'is-today':''}"><div class="dl-date"><span>${WDS[wdi(d)]}</span>${fDate(d)}</div><div class="dl-items">${starts.join('')}${
      cont.length?`<p class="cont">Уже идёт: ${esc(joinNames(cont))}</p>`:''}${
      empty?(V==='gm'?'<p class="muted small" style="margin:3px 0">Записей нет.</p>':(d<=CAL_END?`<button type="button" class="free" data-act="add" data-date="${d}">Свободно. Добавить запись на этот день</button>`:'')):''}</div></div>`;
  }
  h+=`</div><div>`;
  const today=rhythmOn(n.date);
  h+=`<div class="side-block"><h2>Регулярные события сегодня</h2>${today.length?today.map(r=>row('r:'+r.id,'k-rhythm',r.title,r.vis==='мастер'?'скрыто от игроков':'')).join(''):'<p class="muted" style="margin:0">Сегодня регулярных событий нет.</p>'}</div>`;
  if(V==='gm'){
    const pend=S.entries.filter(e=>e.status==='gm');
    const stale=S.entries.filter(e=>e.to&&e.to<n.date&&e.status==='ok');
    const wait=S.entries.filter(e=>e.status==='reply'||e.status==='resched');
    const items=[...pend.map(e=>entryRow(e,'заявка на развитие, '+(CN[e.author]||''))),...stale.map(e=>entryRow(e,'прошла, итог не отмечен')),...wait.map(e=>entryRow(e,STATUS[e.status]))];
    h+=`<div class="side-block"><h2>Требуют решения мастера</h2>${items.length?items.join(''):'<p class="muted" style="margin:0">Нерешённых записей нет.</p>'}</div>`;
    h+=`<div class="side-block"><h2>Приоритеты игроков</h2><p class="note">Дела со звездой: игроки хотят, чтобы их сыграли подробно.</p>${priorityList()}</div>`;
    h+=`<div class="side-block"><h2>Скрытые таймеры</h2><p class="note">Угрозы и сроки, которые идут независимо от действий пачки. Игроки их не видят.</p>${S.clocks.length?S.clocks.map(c=>`<button type="button" class="clock" data-open="c:${c.id}"><b>${esc(c.title)}</b>${c.when?` <span class="muted">срок: ${fFull(c.when)}</span>`:''}<span class="p">${esc(c.note||'')}</span></button>`).join(''):'<p class="muted" style="margin:0">Таймеров нет.</p>'}</div>`;
  }else{
    const inv=S.entries.filter(e=>(e.answers||{})[V]==='ждёт');
    const mine=S.entries.filter(e=>e.author===V&&PENDING.includes(e.status));
    const items=[...inv.map(e=>entryRow(e,'приглашение от '+(GEN[e.author]||''))),...mine.map(e=>entryRow(e,STATUS[e.status]))];
    h+=`<div class="side-block"><h2>Ожидают ответа</h2>${items.length?items.join(''):'<p class="muted" style="margin:0">Нет записей, ожидающих ответа.</p>'}</div>`;
    const st=starOf(V);
    h+=`<div class="side-block"><h2>Звезда ${esc(GEN[V]||'')}</h2>${st?entryRow(st,fFull(st.from))+'<p class="note" style="margin-top:6px">Это дело мастер сыграет подробно. Звезду можно перенести в карточке другого дела.</p>':'<p class="muted" style="margin:0">Звезда свободна. Поставьте её в карточке дела, которое хотите сыграть подробно.</p>'}</div>`;
    const open=visEntries().filter(canJoin).sort((a,b)=>a.from<b.from?-1:1);
    h+=`<div class="side-block"><h2>Можно попроситься</h2>${open.length?open.map(e=>entryRow(e,'от '+(GEN[e.author]||'мастера')+', '+fFull(e.from))).join(''):'<p class="muted" style="margin:0">Открытых записей нет.</p>'}</div>`;
  }
  return h+'</div></div>';
}

/* ===== Календарь ===== */
function curStageIdx(){return S.windows.findIndex(w=>S.now.date>=w.from&&S.now.date<=w.to);}
function stageIdx(){
  let i=UI.stage!=null?UI.stage:curStageIdx();
  if(i<0||i>=S.windows.length)return curStageIdx();
  if(V!=='gm'){const cur=curStageIdx();const maxOk=S.windows.reduce((m,w,k)=>w.from<=S.now.date?k:m,-1);if(i>maxOk)i=cur>=0?cur:maxOk;}
  return i;
}
function laneDays(){
  if(UI.span==='stage'){const i=stageIdx();if(i>=0){const w=S.windows[i];return range(w.from,w.to);}}
  const a=clampDate(UI.anchor||addDays(S.now.date,-1));
  const b=addDays(a,6)>CAL_END?CAL_END:addDays(a,6);
  return range(a,b);
}
function pack(items){
  const ends=[];items.sort((a,b)=>a.s-b.s||b.e-a.e);
  for(const it of items){let r=ends.findIndex(end=>end<it.s);if(r<0){r=ends.length;ends.push(it.e);}else ends[r]=it.e;it.r=r;}
  return Math.max(ends.length,1);
}
function laneHTML(label,items,cols,dcls,nowX,extra){
  const K=pack(items),n=dcls.length;
  let h=`<div class="lane ${extra||''}" style="grid-template-columns:${cols};grid-template-rows:repeat(${K},minmax(38px,auto))"><div class="lane-label" style="grid-row:1/${K+1}">${label}</div>`;
  for(let i=0;i<n;i++)h+=`<div class="cell ${dcls[i]}" style="grid-column:${i+2};grid-row:1/${K+1}"></div>`;
  for(const it of items)h+=`<button type="button" class="bar ${it.cls}" style="grid-column:${it.s+2}/${it.e+3};grid-row:${it.r+1}" data-open="${it.key}" title="${esc(it.tip)}">${it.html}</button>`;
  if(nowX!=null)h+=`<div class="nowline" style="--x:${nowX}" aria-hidden="true"></div>`;
  return h+'</div>';
}
function rLanes(days){
  const n=days.length,first=days[0],last=days[n-1];
  const cols=`var(--label) repeat(${n}, var(--day))`;
  const ni=days.indexOf(S.now.date);
  const nowX=ni<0?null:ni+TODX[S.now.tod];
  const dcls=days.map(d=>(wdi(d)>=5?'we ':'')+(d<S.now.date?'past':''));
  const span=(a,b)=>{const s=a<first?first:a,t=(!b||b>last)?last:b;if(s>last||t<first||s>t)return null;return [days.indexOf(s),days.indexOf(t)];};

  let band=`<div class="lane band" style="grid-template-columns:${cols}"><div class="lane-label">Этап</div>`;
  for(let i=0;i<n;){const w=winOf(days[i]);let j=i;while(j+1<n&&winOf(days[j+1])===w)j++;const vis=winVisible(w);
    band+=`<div class="wband ${vis?(w.inter?'inter':'arc'):''}" style="grid-column:${i+2}/${j+3}" title="${vis?esc(winName(w)):''}">${vis?esc(winName(w)):''}</div>`;i=j+1;}
  band+='</div>';

  let head=`<div class="lane head" style="grid-template-columns:${cols}"><div class="lane-label"></div>`;
  days.forEach((d,k)=>{
    const q=d>=S.now.date?(S.quietUntil&&d<=S.quietUntil?'quiet':'unsure'):'';
    head+=`<div class="dayhead ${dcls[k]} ${d===S.now.date?'is-today':''} ${q}"><span class="wd">${WDS[wdi(d)]}</span>${(dOf(d)===1||k===0)?`<span class="mn">${MONTHS_GEN[mOf(d)-1].slice(0,3)}</span>`:''}<span class="dn">${dOf(d)}</span></div>`;
  });
  head+='</div>';

  const lanes=[];
  const rItem=(r,k)=>({s:k,e:k,key:'r:'+r.id,cls:'k-rhythm'+(r.vis==='мастер'?' gmonly':''),html:`<span>${esc(r.title)}</span>`,tip:r.title});
  const reg=[];days.forEach((d,k)=>rhythmOn(d).forEach(r=>{if(!r.who)reg.push(rItem(r,k));}));
  lanes.push(laneHTML('Регулярные события',reg,cols,dcls,nowX,'sys'));
  const past=S.past.map(p=>{const sp=span(p.from,p.to);return sp&&{s:sp[0],e:sp[1],key:'p:'+p.id,cls:'k-past',html:`<span>${esc(p.title)}</span>`,tip:p.title};}).filter(Boolean);
  if(past.length)lanes.push(laneHTML('Сыграно',past,cols,dcls,nowX,'sys'));
  if(V==='gm'){
    const plan=S.plan.map(p=>{const sp=span(p.from,p.to);return sp&&{s:sp[0],e:sp[1],key:'g:'+p.id,cls:'k-plan',html:`${p.cover?EYE:''}<span>${esc(p.title)}</span>`,tip:p.title+(p.cover?'. Игроки видят: '+p.cover.title:'')};}).filter(Boolean);
    S.clocks.forEach(c=>{if(!c.when)return;const sp=span(c.when,c.when);if(sp)plan.push({s:sp[0],e:sp[1],key:'c:'+c.id,cls:'k-clock',html:`<span>${esc(c.title)}</span>`,tip:c.title});});
    lanes.push(laneHTML('План мастера',plan,cols,dcls,nowX,'sys'));
  }
  const ents=visEntries(),mine=viewChars()||[],bls=blocks();
  CHARS.forEach(c=>{
    const extra=[];
    days.forEach((d,k)=>rhythmOn(d).forEach(r=>{if(r.who===c.id)extra.push(rItem(r,k));}));
    bls.forEach(b=>{if(!blockFor(b,c.id))return;const sp=span(b.from,b.to);if(sp)extra.push({s:sp[0],e:sp[1],key:'b:'+b.id,cls:'k-block',html:`<span>${esc(b.title)}</span>`,tip:b.title+', общее событие'});});
    const items=extra.concat(ents.filter(e=>involves(e,c.id)).map(e=>{const sp=span(e.from,e.to);return sp&&{s:sp[0],e:sp[1],key:'e:'+e.id,cls:entryCls(e),html:`${marks(e)}<span>${esc(e.title)}</span>`,tip:e.title+', '+stText(e)+', '+TALK[e.talk||'open']};}).filter(Boolean));
    lanes.push(laneHTML(esc(c.name),items,cols,dcls,nowX,c.id===V?'mine':mine.includes(c.id)?'own':''));
  });
  return `<div class="lanes-wrap ${UI.span==='stage'?'span-stage':''}" id="lanes-wrap"><div class="lanes">${band}${head}${lanes.join('')}</div></div>`;
}
function fitLanes(){
  const w=document.getElementById('lanes-wrap');if(!w)return;
  w.style.removeProperty('--day');
  const cs=getComputedStyle(w),base=parseFloat(cs.getPropertyValue('--day'))||98,label=parseFloat(cs.getPropertyValue('--label'))||100;
  const n=laneDays().length,day=Math.max(base,Math.floor((w.clientWidth-label-2)/n));
  w.style.setProperty('--day',day+'px');
}
let rsz;window.addEventListener('resize',()=>{clearTimeout(rsz);rsz=setTimeout(fitLanes,120);});
function scrollToNow(){
  const w=document.getElementById('lanes-wrap');if(!w||UI.span!=='stage')return;
  const i=laneDays().indexOf(S.now.date);if(i<0){w.scrollLeft=0;return;}
  const day=parseFloat(getComputedStyle(w).getPropertyValue('--day'))||98;
  w.scrollLeft=Math.max(0,i*day-day*1.5);
}
function monthItems(s){
  const r=[];
  S.past.forEach(p=>{if(s>=p.from&&s<=p.to)r.push({t:p.title,cls:'k-past'});});
  if(V!=='gm')blocks().forEach(b=>{if(s>=b.from&&s<=b.to)r.push({t:b.title,cls:'k-block'});});
  if(V==='gm'){S.plan.forEach(p=>{if(s>=p.from&&s<=p.to)r.push({t:p.title,cls:'k-plan'});});S.clocks.forEach(c=>{if(c.when===s)r.push({t:c.title,cls:'k-clock'});});}
  visEntries().forEach(e=>{if(s>=e.from&&s<=(e.to||e.from))r.push({t:((e.stars||[]).length?'★ ':'')+e.title,cls:'t-'+e.type+' talk-'+(e.talk||'open')});});
  return r;
}
const curMonth=()=>UI.month||S.now.date.slice(0,7);
function rMonth(ym){
  const y=+ym.slice(0,4),m=+ym.slice(5,7),first=ym+'-01',dim=new Date(Date.UTC(y,m,0)).getUTCDate(),lead=wdi(first),last=ym+'-'+pad(dim);
  const wins=S.windows.filter(w=>winVisible(w)&&w.from<=last&&w.to>=first);
  let h=`<p class="month-wins">${wins.length?'Этапы месяца: ':''}${wins.map(w=>`<span>${esc(winName(w))}, ${fRange(w.from,w.to)}</span>`).join('')}</p><div class="month">`;
  h+=WDS.map(w=>`<div class="mhead">${w}</div>`).join('');
  for(let i=0;i<lead;i++)h+='<div class="mcell empty"></div>';
  for(let d=1;d<=dim;d++){
    const s=ym+'-'+pad(d),w=winOf(s),vis=winVisible(w),its=monthItems(s);
    h+=`<button type="button" class="mcell ${s===S.now.date?'is-today':''} ${s<S.now.date?'past':''}" data-act="day" data-date="${s}" aria-label="${fFull(s)}, записей: ${its.length}. Открыть неделю"><span class="strip ${vis?(w.inter?'inter':'arc'):''}"></span><span class="mdn">${d}</span>${its.slice(0,3).map(x=>`<span class="mitem ${x.cls}"><i></i><span>${esc(x.t)}</span></span>`).join('')}${its.length>3?`<span class="more">ещё ${its.length-3}</span>`:''}</button>`;
  }
  const tail=(7-(lead+dim)%7)%7;for(let i=0;i<tail;i++)h+='<div class="mcell empty"></div>';
  return h+'</div>';
}
function legend(){
  const lanes=UI.cal==='lanes';
  return `<div class="legend">${Object.entries(TYPES).map(([k,t])=>`<span class="lg"><i class="sw t-${k} talk-closed"></i>${t.name}</span>`).join('')}<span class="lg"><i class="sw k-past"></i>Сыграно</span>${V==='gm'?'<span class="lg"><i class="sw k-plan"></i>План мастера</span><span class="lg">'+EYE+'Игроки видят как общее событие</span><span class="lg"><i class="sw k-clock"></i>Скрытый таймер</span>':'<span class="lg"><i class="sw k-block"></i>Общее событие</span>'}<span class="lg"><i class="sw k-rhythm"></i>Регулярное событие или привычка</span></div>
  <div class="legend"><span class="lg"><i class="sw t-deal talk-open"></i>Бледный цвет: в обсуждении</span><span class="lg"><i class="sw t-deal talk-closed"></i>Насыщенный цвет: обсуждение окончено</span><span class="lg"><b class="star">★</b>Приоритет игрока</span><span class="lg"><b class="plus">+</b>Можно попроситься</span>${lanes?'<span class="lg"><i class="sw pend"></i>Ждёт ответа или проверки</span><span class="lg"><span class="mark">✓</span>Состоялось</span><span class="lg"><span class="strike">Текст</span>Сорвано или отклонено</span><span class="lg"><i class="ln now"></i>Текущий момент</span><span class="lg"><i class="ln quiet"></i>Свободное время гарантировано</span><span class="lg"><i class="ln unsure"></i>Свободное время не гарантировано</span>':''}</div>`;
}
function rCal(){
  let h=`<div class="toolbar"><div class="seg" role="group" aria-label="Вид календаря"><button type="button" data-act="cal-view" data-v="lanes" aria-pressed="${UI.cal==='lanes'}">По персонажам</button><button type="button" data-act="cal-view" data-v="month" aria-pressed="${UI.cal==='month'}">Месяц</button></div>`;
  if(UI.cal==='lanes'){
    const days=laneDays();
    h+=`<div class="seg" role="group" aria-label="Охват"><button type="button" data-act="span" data-v="week" aria-pressed="${UI.span==='week'}">Неделя</button><button type="button" data-act="span" data-v="stage" aria-pressed="${UI.span==='stage'}">Этап целиком</button></div>`;
    if(UI.span==='stage'&&stageIdx()>=0){
      const i=stageIdx(),w=S.windows[i];
      const nextOk=i+1<S.windows.length&&(V==='gm'||S.windows[i+1].from<=S.now.date);
      h+=`<div class="nav-range"><button type="button" class="btn icon" data-act="stage" data-v="-1" aria-label="Предыдущий этап" ${i<=0?'disabled':''}>‹</button><span class="range-label">${esc(winName(w))}</span><button type="button" class="btn icon" data-act="stage" data-v="1" aria-label="Следующий этап" ${nextOk?'':'disabled'}>›</button></div>`;
    }else{
      h+=`<div class="nav-range"><button type="button" class="btn icon" data-act="week" data-v="-1" aria-label="На неделю раньше" ${days[0]<=CAL_START?'disabled':''}>‹</button><span class="range-label">${fRange(days[0],days[days.length-1])}</span><button type="button" class="btn icon" data-act="week" data-v="1" aria-label="На неделю позже" ${days[days.length-1]>=CAL_END?'disabled':''}>›</button></div>`;
    }
    h+=`<button type="button" class="btn plain" data-act="today">К текущему дню</button>`;
  }else{
    const ym=curMonth(),i=MONTH_LIST.indexOf(ym);
    h+=`<div class="nav-range"><button type="button" class="btn icon" data-act="month" data-v="-1" aria-label="Предыдущий месяц" ${i<=0?'disabled':''}>‹</button><span class="range-label">${MONTHS_NOM[+ym.slice(5,7)-1]} ${ym.slice(0,4)}</span><button type="button" class="btn icon" data-act="month" data-v="1" aria-label="Следующий месяц" ${i>=MONTH_LIST.length-1?'disabled':''}>›</button></div>`;
    h+=`<button type="button" class="btn plain" data-act="today">К текущему месяцу</button>`;
  }
  h+=`<span class="grow"></span><button type="button" class="btn primary" data-act="add">Добавить запись</button></div>`;
  if(UI.cal==='lanes'&&UI.span==='stage'&&stageIdx()<0)h+='<p class="note">Текущая дата не входит ни в один этап, показана неделя.</p>';
  h+=UI.cal==='lanes'?rLanes(laneDays()):rMonth(curMonth());
  return h+legend();
}

/* ===== Хроника ===== */
function chEv(p){return `<button type="button" class="ch-ev" data-open="p:${p.id}"><span class="d">${p.from===p.to?fFull(p.from):WDS[wdi(p.from)]+'–'+WDS[wdi(p.to)]+', '+fRange(p.from,p.to)}</span><span><span class="t">${esc(p.title)}</span>${p.note?`<span class="n">${esc(p.note)}</span>`:''}${p.session?`<span class="s">${esc(p.session)}</span>`:''}</span></button>`;}
function rChron(){
  const wins=S.windows.filter(w=>winVisible(w)&&w.from<=S.now.date);
  let h='<div class="chron">';
  if(V==='gm')h+='<div class="chron-top"><button type="button" class="btn" data-act="new-item" data-kind="past">Добавить событие в хронику</button><span class="muted small">Чтобы изменить или удалить событие, откройте его.</span></div>';
  else if(S.recap&&!RO()&&(viewChars()||[]).length)h+='<div class="chron-top"><button type="button" class="btn" data-act="open-recap">Что было раньше</button><span class="muted small">Пересказ того, что вы пропустили, по вашей хронике.</span></div>';
  if(!wins.length)h+='<p class="muted">Хроника начнётся с первого этапа кампании.</p>';
  for(const w of wins){
    const ev=S.past.filter(p=>p.from>=w.from&&p.from<=w.to);
    const doneE=visEntries().filter(e=>e.status==='done'&&e.from>=w.from&&e.from<=w.to);
    h+=`<section class="ch-win"><h2>${esc(winName(w))}</h2><p class="muted">${w.from===w.to?fFull(w.from):fRange(w.from,w.to)}</p>`;
    h+=ev.map(chEv).join('');
    if(!ev.length)h+='<p class="muted">Сыгранных событий пока нет.</p>';
    const hs=handoutsVisible().filter(x=>x.file&&x.date>=w.from&&x.date<=w.to).sort((a,b)=>a.date<b.date?-1:1);
    if(hs.length)h+=`<h3>Раздатки</h3>`+hs.map(x=>`<button type="button" class="ch-ev" data-open="h:${x.id}"><span class="d">${fFull(x.date)}</span><span><span class="t">${esc(x.title)}</span><span class="s">${esc(hWho(x))}</span></span></button>`).join('');
    if(doneE.length)h+=`<h3>Состоявшиеся записи игроков</h3>`+doneE.map(e=>`<button type="button" class="ch-ev" data-open="e:${e.id}"><span class="d">${fFull(e.from)}</span><span><span class="t">${esc(e.title)}</span><span class="s">${esc(joinNames(e.who.map(c=>CN[c]||c)))}</span></span></button>`).join('');
    h+='</section>';
  }
  const loose=S.past.filter(p=>!S.windows.some(w=>p.from>=w.from&&p.from<=w.to&&winVisible(w)));
  if(loose.length)h+=`<section class="ch-win"><h2>Вне этапов</h2><p class="muted">События, даты которых не попадают ни в один этап.</p>${loose.map(chEv).join('')}</section>`;
  return h+'</div>';
}


/* ===== Панель мастера ===== */
function secHead(title,kind,label){return `<div class="sec-head"><h2>${title}</h2>${kind?`<button type="button" class="btn small" data-act="new-item" data-kind="${kind}">${label}</button>`:''}</div>`;}
function rGM(){
  const n=S.now;
  const pend=S.entries.filter(e=>e.status==='gm');
  const stale=S.entries.filter(e=>e.to&&e.to<n.date&&e.status==='ok');
  const plan=S.plan.slice().sort((a,b)=>a.from<b.from?-1:1);
  const qEnd=addDays(n.date,60)>CAL_END?CAL_END:addDays(n.date,60);
  const qopts=range(n.date,qEnd).map(d=>`<option value="${d}" ${d===S.quietUntil?'selected':''}>${fFull(d)}</option>`).join('');
  const jopts=range(CAL_START,CAL_END).map(d=>`<option value="${d}" ${d===n.date?'selected':''}>${fFull(d)}</option>`).join('');
  return `<div class="gm-grid">
  <section><h2>Текущий момент в игре</h2><p class="big">${cap(WD[wdi(n.date)])}, ${fDate(n.date)} 2075, ${n.tod}</p>
    <div class="row-btns"><button type="button" class="btn" data-act="shift" data-v="-1" ${n.date<=CAL_START?'disabled':''}>На день назад</button><button type="button" class="btn" data-act="shift" data-v="1" ${n.date>=CAL_END?'disabled':''}>На день вперёд</button><button type="button" class="btn" data-act="shift" data-v="7" ${n.date>=CAL_END?'disabled':''}>На неделю вперёд</button></div>
    <div class="seg" role="group" aria-label="Время суток">${TOD.map(t=>`<button type="button" data-act="tod" data-v="${t}" aria-pressed="${n.tod===t}">${t}</button>`).join('')}</div>
    <div class="field">Перейти к дате<div class="inline"><select id="jump" aria-label="Дата">${jopts}</select><button type="button" class="btn" data-act="jump">Перейти</button></div></div>
    <label class="field">Свободное время гарантировано до<select id="quiet"><option value="">не гарантировано</option>${qopts}</select><span class="sub">Игроки видят эту дату на главной и полосой над днями в календаре.</span></label>
    <p class="muted small">Если настроен чат стола, бот обновляет в нём закреплённое сообщение с датой и свободным временем.</p></section>
  <section><h2>Приоритеты игроков</h2><p class="note">У каждого персонажа одна звезда. Дело со звездой игрок хочет сыграть подробно.</p>${priorityList()}</section>
  <section><h2>Заявки на развитие</h2>${pend.length?pend.map(e=>`<div class="gm-item">${entryRow(e,CN[e.author]||'')}<button type="button" class="btn" data-act="approve" data-id="${e.id}">Подтвердить</button><button type="button" class="btn" data-act="reject" data-id="${e.id}">Отклонить</button></div>`).join(''):'<p class="muted">Новых заявок нет.</p>'}</section>
  <section><h2>Прошедшие записи без итога</h2><p class="note">Отметьте, состоялось ли запланированное. Состоявшиеся записи попадают в хронику.</p>${stale.length?stale.map(e=>`<div class="gm-item">${entryRow(e,fFull(e.to))}<button type="button" class="btn" data-act="outcome" data-id="${e.id}" data-v="done">Состоялось</button><button type="button" class="btn" data-act="outcome" data-id="${e.id}" data-v="failed">Сорвано</button></div>`).join(''):'<p class="muted">Все прошедшие записи отмечены.</p>'}</section>
  <section>${secHead('План мастера','plan','Добавить событие')}<p class="note">События плана игроки не видят. Если у события включено «Показать игрокам как общее событие», игроки видят на эти дни общее событие с другим текстом (${EYE} на календаре). Сыгранное событие переносится в хронику, а его описание становится там заметкой мастера, которую игроки не видят.</p>${plan.length?plan.map(p=>`<div class="gm-item">${row('g:'+p.id,'k-plan',p.title,fFull(p.from),p.cover?EYE+' ':'')}<button type="button" class="btn" data-act="played" data-id="${p.id}">В хронику</button></div>`).join(''):'<p class="muted">План пуст.</p>'}</section>
  <section>${secHead('Скрытые таймеры','clocks','Добавить таймер')}<p class="note">Угрозы и сроки, которые идут независимо от пачки. Таймер со сроком появляется в строке «План мастера».</p>${S.clocks.length?S.clocks.map(c=>row('c:'+c.id,'k-clock',c.title,c.when?'срок: '+fFull(c.when):'без срока')).join(''):'<p class="muted">Таймеров нет.</p>'}</section>
  <section>${secHead('Регулярные события','rhythm','Добавить событие')}<p class="note">Расписание города и привычки персонажей. Привычка показывается в строке персонажа.</p>${S.rhythm.length?S.rhythm.map(r=>row('r:'+r.id,'k-rhythm',r.title,[r.who?CN[r.who]:'',rhythmWhen(r),r.to?'до '+fDate(r.to):'',r.vis==='мастер'?'скрыто от игроков':''].filter(Boolean).join(', '))).join(''):'<p class="muted">Регулярных событий нет.</p>'}</section>
  <section>${secHead('Транспорт и скорости','travel','Добавить вид транспорта')}<p class="note">Нужен для линейки на карте: время в пути считается по этим скоростям (км/ч).</p>${(S.travel||[]).map(t=>`<button type="button" class="row" data-act="edit-item" data-kind="travel" data-id="${t.id}"><span class="rt">${esc(t.name)}${t.vis==='мастер'?'<span class="tag">скрыто от игроков</span>':''}</span><span class="rs">${t.kind==='straight'?'по прямой, '+t.off+' км/ч':'дороги '+t.motorway+'/'+t.trunk+'/'+t.primary+' км/ч, вне дорог '+t.off}</span></button>`).join('')||'<p class="muted">Видов транспорта нет.</p>'}</section>
  <section>${secHead('Этапы','windows','Добавить этап')}<p class="note">Арки и промежуточные арки. Игроки видят название этапа с его первого дня.</p>${S.windows.map(w=>`<div class="gm-item"><span class="wname">${esc(winName(w))}${w.gm&&w.gm!==w.name?`<span class="muted small" style="display:block">игроки видят: ${esc(w.name)}</span>`:''}</span><span class="muted small">${fRange(w.from,w.to)}</span><button type="button" class="btn" data-act="edit-item" data-kind="windows" data-id="${w.id}">Изменить</button></div>`).join('')}</section>
  <section>${secHead('Хроника','past','Добавить событие')}<p class="note">Сыгранные события. Чтобы изменить или удалить событие, откройте его в разделе «Хроника».</p></section>
  ${gmExtrasHTML()}
  <section><h2>Копия данных для Obsidian</h2><p class="note">Если вы ведёте заметки в программе Obsidian: нажмите кнопку, скопируйте получившийся текст и вставьте его в Obsidian как новую заметку. В нём весь календарь, места, досье и раздатки, в том числе то, что скрыто от игроков.</p><button type="button" class="btn" data-act="export">Собрать текст для копирования</button><textarea id="exp" readonly hidden aria-label="Текст выгрузки"></textarea></section>
  </div>`;
}
function exportMd(){
  let s=`---\ntags: [календарь]\nсейчас: ${S.now.date}\nвремя_суток: ${S.now.tod}\nсвободно_до: ${S.quietUntil||'не гарантировано'}\n---\n\n# Календарь, выгрузка\n\n## Сыграно\n\n`;
  S.past.forEach(p=>{s+=`- ${p.from}${p.to!==p.from?'..'+p.to:''}, ${WDS[wdi(p.from)]}. ${p.title}${p.session?` (${p.session})`:''}${p.note?`. ${p.note.replace(/\n+/g,' ')}`:''}${p.gm_note?` [мастер: ${p.gm_note.replace(/\n+/g,' ')}]`:''}\n`;});
  s+='\n## Записи\n';
  S.entries.forEach(e=>{
    s+=`\n### ${e.title}\n- тип:: ${TYPES[e.type].name.toLowerCase()}\n- начало:: ${e.from}\n- окончание:: ${e.to||'без срока'}\n- кто:: ${whoText(e)}\n- где:: ${e.where||''}\n- условие:: ${e.cond||''}\n- цель:: ${(e.goal||'').replace(/\n/g,' ')}\n- статус:: ${stText(e)}\n- обсуждение:: ${TALK[e.talk||'open']}\n- приоритет:: ${(e.stars||[]).map(c=>CN[c]||c).join(', ')}\n- видимость:: ${e.vis==='лично'?'участники и мастер':'все игроки'}\n`;
    if(e.effect)s+=`- действует_с:: ${e.effect}\n`;
    if((e.chat||[]).length){s+='\n#### Обсуждение\n';e.chat.forEach(m=>{s+=`- ${CN[m.a]||m.a}: ${m.t.replace(/\n/g,' ')}\n`;});}
  });
  s+='\n## План мастера\n\n';
  S.plan.forEach(p=>{s+=`- ${p.from}${p.to!==p.from?'..'+p.to:''}. ${p.title}${p.session?` (${p.session})`:''}${p.cover?`. Игроки видят: ${p.cover.title}`:''}\n`;});
  s+='\n## Скрытые таймеры\n\n';
  S.clocks.forEach(c=>{s+=`- ${c.title}${c.when?`, срок ${c.when}`:''}${c.note?`. ${c.note.replace(/\n/g,' ')}`:''}\n`;});
  s+='\n## Регулярные события\n\n';
  S.rhythm.forEach(r=>{s+=`- ${r.title}: ${rhythmWhen(r)}${r.who?`, ${CN[r.who]||r.who}`:''}${r.from?`, с ${r.from}`:''}${r.to?`, до ${r.to}`:''}${r.vis==='мастер'?', скрыто от игроков':''}\n`;});
  const one=t=>String(t||'').replace(/\n+/g,' ');
  const who=a=>(a||[]).map(x=>CN[x]||x).join(', ');
  s+='\n## Этапы\n\n';
  S.windows.forEach(w=>{s+=`- ${w.from}..${w.to}. ${w.gm||w.name}${w.gm&&w.gm!==w.name?` (игроки видят: ${w.name})`:''}${w.inter?', промежуточная':''}\n`;});
  s+='\n## Места на карте\n\n';
  (S.places||[]).slice().sort((a,b)=>a.name.localeCompare(b.name,'ru')).forEach(p=>{s+=`- ${p.name} (${PLACE_TYPES[p.type]||p.type}${p.bg?', фон':''}; ${DNAMES[districtAt(p.x,p.y)]||'район не определён'}; квадрат ${square(p.x,p.y)}; ${p.vis==='знают'?'знают: '+who(p.known):PVIS[p.vis]||''})${p.note?`. ${one(p.note)}`:''}${p.gm_note?` [мастер: ${one(p.gm_note)}]`:''}\n`;});
  s+='\n## Районы\n\n';
  (S.dnotes||[]).forEach(d=>{s+=`- ${DNAMES[d.id]||d.id}${d.text?`: ${one(d.text)}`:''}${d.gm_text?` [мастер: ${one(d.gm_text)}]`:''}\n`;});
  s+='\n## Раздатки\n\n';
  (S.handouts||[]).slice().sort((a,b)=>a.date<b.date?-1:1).forEach(x=>{const pl=x.place?placeById(x.place):null;s+=`- ${x.date}. ${x.title} (${x.vis==='знают'?'получили: '+who(x.known):x.vis==='мастер'?'черновик':'вся пачка'})${pl?`, ${pl.name}`:''}${x.fname?`, файл ${x.fname}`:''}${x.note?`. ${one(x.note)}`:''}${x.gm_note?` [мастер: ${one(x.gm_note)}]`:''}\n`;});
  s+='\n## Досье\n';
  (S.dossier||[]).slice().sort((a,b)=>a.name.localeCompare(b.name,'ru')).forEach(c=>{
    const pl=c.last_place?placeById(c.last_place):null;
    s+=`\n### ${c.name}${c.alias?` «${c.alias}»`:''}\n- тип:: ${DTYPE[c.type]||c.type}\n- отношение:: ${STANCE[c.stance]||c.stance}\n- видимость:: ${c.vis==='знают'?'только: '+who(c.known):DVIS[c.vis]}\n`;
    if(c.role)s+=`- кто_это:: ${one(c.role)}\n`;
    if(c.org)s+=`- организация:: ${one(c.org)}\n`;
    if((c.met||[]).length)s+=`- знакомы:: ${who(c.met)}\n`;
    if(c.last_date||pl||c.last_note)s+=`- последняя_встреча:: ${[c.last_date,pl?pl.name:'',one(c.last_note)].filter(Boolean).join(', ')}\n`;
    (c.facts||[]).forEach(f=>{s+=`- ${f.date?f.date+': ':''}${one(f.text)} (${f.vis==='знают'?'знают: '+who(f.known):f.vis==='мастер'?'скрыто':'все'})${f.truth?` [на самом деле: ${one(f.truth)}]`:''}\n`;});
    if(c.gm_note)s+=`\n> ${c.gm_note.replace(/\n/g,'\n> ')}\n`;
  });
  return s;
}

/* ===== Панель подробностей ===== */
let lastFocus=null,curKey=null;
const overlayOpen=()=>!document.getElementById('overlay').hidden;
function showPanel(html,keep){
  const p=document.getElementById('panel');
  let draft=null,focused=false;
  if(keep){const ta=p.querySelector('#chat-form textarea');if(ta){draft=ta.value;focused=document.activeElement===ta;}}
  else lastFocus=document.activeElement;
  const top=p.scrollTop;
  p.innerHTML=`<button type="button" class="btn plain x" data-act="close">Закрыть</button>`+html;
  const h2=p.querySelector('h2');if(h2){h2.id='panel-title';p.setAttribute('aria-labelledby','panel-title');}else p.removeAttribute('aria-labelledby');
  document.getElementById('overlay').hidden=false;
  if(keep){p.scrollTop=top;const ta=p.querySelector('#chat-form textarea');if(ta&&draft){ta.value=draft;}if(ta&&focused)ta.focus();return;}
  p.scrollTop=0;
  const f=p.querySelector('input[name="title"]')||p.querySelector('.x');f&&f.focus();
}
function closePanel(){document.getElementById('overlay').hidden=true;curKey=null;if(lastFocus&&document.body.contains(lastFocus))lastFocus.focus();}
function toast(t){const el=document.getElementById('toast');el.textContent=t;el.classList.add('on');clearTimeout(toast.h);toast.h=setTimeout(()=>el.classList.remove('on'),2200);}
function finish(msg){closePanel();render(true);if(msg)toast(msg);}
function refresh(msg){render(true);if(curKey&&overlayOpen())openDetail(curKey,true);if(msg)toast(msg);}

function dEntry(e){
  const ans=e.answers||{},stars=e.stars||[],talk=e.talk||'open';
  const mineChars=viewChars()||[];
  const manage=V==='gm'||mineChars.includes(e.author);
  const live=!CLOSED.includes(e.status);
  const parts=e.who.map(c=>`<li><span>${esc(CN[c]||c)}${stars.includes(c)?' <b class="star" title="Приоритет">★</b>':''}</span><span class="muted">${c===e.author?'автор записи':(ANS[ans[c]]||'участник')}${manage&&c!==e.author&&live?` <button type="button" class="btn plain mini" data-act="kick" data-id="${e.id}" data-v="${c}">убрать</button>`:''}</span></li>`).join('')
    +(e.open?'<li><span><b class="plus">+</b></span><span class="muted">место для любого желающего</span></li>':'');

  let acts='';
  if(ans[V]==='ждёт')acts+=`<button type="button" class="btn primary" data-act="ans" data-id="${e.id}" data-v="да">Принять приглашение</button><button type="button" class="btn" data-act="ans" data-id="${e.id}" data-v="нет">Отказаться: неудобная дата</button>`;
  if(canJoin(e))acts+=`<button type="button" class="btn primary" data-act="join" data-id="${e.id}">Попроситься</button>`;
  if(V==='gm'&&e.status==='gm')acts+=`<button type="button" class="btn primary" data-act="approve" data-id="${e.id}">Подтвердить развитие</button><button type="button" class="btn" data-act="reject" data-id="${e.id}">Отклонить</button>`;
  if(V==='gm'&&e.to&&e.to<S.now.date&&e.status==='ok')acts+=`<button type="button" class="btn" data-act="outcome" data-id="${e.id}" data-v="done">Состоялось</button><button type="button" class="btn" data-act="outcome" data-id="${e.id}" data-v="failed">Сорвано</button>`;
  if(manage&&live)acts+=`<button type="button" class="btn" data-act="edit-entry" data-id="${e.id}">Изменить запись</button>`;
  if(manage&&live)acts+=`<button type="button" class="btn" data-act="talk" data-id="${e.id}">${talk==='open'?'Завершить обсуждение':'Возобновить обсуждение'}</button>`;
  if(V==='gm')acts+=`<button type="button" class="btn plain" data-act="item-history" data-kind="entry" data-id="${e.id}">История</button>`;
  if(manage&&live)acts+=`<button type="button" class="btn plain" data-act="del" data-id="${e.id}">Удалить запись</button>`;

  let star='';
  if(V!=='gm'&&involves(e,V)&&isActive(e)){
    const mine=stars.includes(V),other=starOf(V);
    star=`<div class="star-box"><button type="button" class="btn ${mine?'':'primary'}" data-act="star" data-id="${e.id}">${mine?'Снять звезду':other?'Перенести звезду сюда':'Отметить звездой'}</button><p class="note">${other&&!mine?`Сейчас звезда ${esc(GEN[V]||'')} стоит на записи «${esc(other.title)}». `:''}У каждого персонажа одна звезда. Дело со звездой мастер сыграет подробно.</p></div>`;
  }

  const when=e.to?fSpan(e.from,e.to):'с '+fFull(e.from)+', без срока';
  const chat=e.chat||[];
  let chatH=`<h3>Обсуждение${chat.length?' ('+chat.length+')':''}</h3><div class="chat">${chat.length?chat.map(m=>`<div class="msg ${m.a===V?'mine':''}"><div class="mh"><b>${esc(CN[m.a]||m.a)}</b><span>${fTs(m.ts)}</span></div>${m.r?rollHTML(m):`<p>${rich(m.t)}</p>`}</div>`).join(''):'<p class="muted" style="margin:0">Сообщений пока нет.</p>'}</div>`;
  if(talk==='closed')chatH+='<p class="note" style="margin-top:10px">Обсуждение окончено, новые сообщения недоступны.</p>';
  else if(canWrite(e))chatH+=rollFormHTML(e)+`<form id="chat-form" data-id="${e.id}"><textarea name="msg" rows="2" maxlength="2000" placeholder="Как подойти к делу и кто что делает на игре"></textarea><div class="chat-send"><span class="muted small">Ctrl+Enter отправляет. [[Имя]] ссылается на карточку досье</span><button type="submit" class="btn primary">Отправить</button></div></form>`;
  else chatH+=`<p class="note" style="margin-top:10px">Писать могут участники и мастер.${canJoin(e)?' Чтобы участвовать, попроситесь в запись.':''}</p>`;

  return `<p class="kind t-${e.type}"><i class="sw"></i>${TYPES[e.type].name}<span class="tag">${TALK[talk]}</span>${e.vis==='лично'?'<span class="tag">видят только участники и мастер</span>':''}</p><h2>${esc(e.title)}</h2>
  <dl><dt>Даты</dt><dd>${when}${e.tod?', '+e.tod:''}</dd>${e.type==='grow'&&e.effect?`<dt>Действует с</dt><dd>${fFull(e.effect)}</dd>`:''}<dt>Статус</dt><dd>${stText(e)}</dd><dt>Видимость</dt><dd>${e.vis==='лично'?'участники и мастер':'все игроки'}</dd>${e.author==='gm'?'<dt>Автор</dt><dd>мастер</dd>':''}</dl>
  <h3>Анкета</h3><dl class="anketa-dl"><dt>Кто</dt><dd>${esc(whoText(e))||'не указано'}</dd><dt>Где</dt><dd>${rich(e.where)||'<span class="muted">не указано</span>'}${e.place&&placesVisible().some(p=>p.id===e.place)?` <button type="button" class="btn plain mini" data-act="show-place" data-id="${e.place}">на карте</button>`:''}</dd><dt>Условие</dt><dd>${rich(e.cond)||'<span class="muted">не указано</span>'}</dd><dt>Цель</dt><dd class="goal">${rich(e.goal)||'<span class="muted">не указано</span>'}</dd></dl>
  <h3>Участники</h3><ul class="plist">${parts}</ul>${star}<div class="acts">${acts}</div>${chatH}`;
}
function gmBtns(kind,id,extra){return V==='gm'?`<div class="acts">${extra||''}<button type="button" class="btn" data-act="edit-item" data-kind="${kind}" data-id="${id}">Изменить</button><button type="button" class="btn plain" data-act="item-history" data-kind="${kind}" data-id="${id}">История</button><button type="button" class="btn plain" data-act="del-item" data-kind="${kind}" data-id="${id}">Удалить</button></div>`:'';}
function openDetail(key,keep){
  const i=key.indexOf(':'),k=key.slice(0,i),id=key.slice(i+1);
  if(k==='h'){if(!keep)openHandout(id);return;}
  if(k==='n')return openDossier(id,keep);
  if(k==='m')return openPlace(id,keep);
  if(k==='d')return openDistrict(id,keep);
  curKey=key;
  if(k==='e'){const e=S.entries.find(x=>x.id===id);if(e&&canSee(e))showPanel(dEntry(e),keep);else closePanel();return;}
  if(k==='p'){const p=S.past.find(x=>x.id===id);if(p)showPanel(`<p class="kind k-past"><i class="sw"></i>Сыгранное событие</p><h2>${esc(p.title)}</h2><dl><dt>Даты</dt><dd>${fSpan(p.from,p.to)}</dd>${p.session?`<dt>Сессия</dt><dd>${esc(p.session)}</dd>`:''}</dl>${p.note?`<p class="prose">${rich(p.note)}</p>`:''}${V==='gm'&&p.gm_note?`<h3>Заметка мастера</h3><p class="prose" style="margin-top:0;white-space:pre-wrap">${rich(p.gm_note)}</p>`:''}${gmBtns('past',p.id)}`,keep);else closePanel();return;}
  if(k==='b'){const b=blocks().find(x=>x.id===id);if(!b){closePanel();return;}
    showPanel(`<p class="kind k-block"><i class="sw"></i>Общее событие</p><h2>${esc(b.title)}</h2><dl><dt>Даты</dt><dd>${fSpan(b.from,b.to)}</dd><dt>Кого касается</dt><dd>${b.who.length?esc(joinNames(b.who.map(c=>CN[c]||c))):'вся пачка'}</dd></dl>${b.note?`<p class="prose">${rich(b.note)}</p>`:''}<p class="note" style="margin-top:16px">На эти дни лучше не планировать других дел.</p>`,keep);return;}
  if(V!=='gm'&&(k==='g'||k==='c')){closePanel();return;}
  if(k==='g'){const p=S.plan.find(x=>x.id===id);if(!p){closePanel();return;}
    const c=p.cover;
    const cover=c?`<h3>Что видят игроки</h3><dl><dt>Событие</dt><dd>${esc(c.title)}</dd><dt>Кого касается</dt><dd>${c.who&&c.who.length?esc(joinNames(c.who.map(x=>CN[x]||x))):'вся пачка'}</dd></dl>${c.note?`<p class="prose">${rich(c.note)}</p>`:''}`:'<h3>Что видят игроки</h3><p class="muted" style="margin:0">Ничего: событие скрыто от игроков.</p>';
    showPanel(`<p class="kind k-plan"><i class="sw"></i>План мастера${c?'<span class="tag">игроки видят общее событие</span>':'<span class="tag">скрыто от игроков</span>'}</p><h2>${esc(p.title)}</h2><dl><dt>Даты</dt><dd>${fSpan(p.from,p.to)}</dd>${p.session?`<dt>Сессия</dt><dd>${esc(p.session)}</dd>`:''}</dl>${p.note?`<p class="prose">${rich(p.note)}</p>`:''}${cover}${gmBtns('plan',p.id,`<button type="button" class="btn primary" data-act="played" data-id="${p.id}">Перенести в хронику</button>`)}`,keep);return;}
  if(k==='c'){const c=S.clocks.find(x=>x.id===id);if(c)showPanel(`<p class="kind k-clock"><i class="sw"></i>Скрытый таймер<span class="tag">скрыто от игроков</span></p><h2>${esc(c.title)}</h2><dl><dt>Срок</dt><dd>${c.when?fFull(c.when):'не назначен'}</dd></dl>${c.note?`<p class="prose">${rich(c.note)}</p>`:''}${gmBtns('clocks',c.id)}`,keep);else closePanel();return;}
  if(k==='r'){const r=S.rhythm.find(x=>x.id===id);if(!r||!rhythmVisible(r)){closePanel();return;}
    showPanel(`<p class="kind k-rhythm"><i class="sw"></i>${r.who?'Привычка персонажа':'Регулярное событие'}${r.vis==='мастер'?'<span class="tag">скрыто от игроков</span>':''}</p><h2>${esc(r.title)}</h2><dl><dt>Повторяется</dt><dd>${rhythmWhen(r)}</dd>${r.who?`<dt>Персонаж</dt><dd>${esc(CN[r.who]||r.who)}</dd>`:''}${r.from?`<dt>Начиная с</dt><dd>${fFull(r.from)}</dd>`:''}${r.to?`<dt>Заканчивается</dt><dd>${fFull(r.to)}</dd>`:''}</dl>${r.note?`<p class="prose">${rich(r.note)}</p>`:''}${gmBtns('rhythm',r.id)}`,keep);}
}

/* ===== Формы мастера: этапы, регулярные события, таймеры, план, хроника ===== */
const KIND_LABEL={travel:'Вид транспорта',dossier:'Досье',places:'Место на карте',windows:'Этап',rhythm:'Регулярное событие',clocks:'Скрытый таймер',plan:'План мастера',past:'Хроника'};
const KIND_NEW={travel:'Новый вид транспорта',dossier:'Новая карточка',places:'Новое место',windows:'Новый этап',rhythm:'Новое регулярное событие',clocks:'Новый скрытый таймер',plan:'Новое событие плана',past:'Новое событие хроники'};
function dateOpts(sel,emptyLabel){return (emptyLabel?`<option value="" ${!sel?'selected':''}>${emptyLabel}</option>`:'')+range(CAL_START,CAL_END).map(d=>`<option value="${d}" ${d===sel?'selected':''}>${fFull(d)}</option>`).join('');}
function openItemForm(kind,id,pos){
  if(V!=='gm')return;
  const list={travel:S.travel||[],dossier:S.dossier||[],places:S.places||[],windows:S.windows,rhythm:S.rhythm,clocks:S.clocks,plan:S.plan,past:S.past}[kind];
  const it=id?list.find(x=>x.id===id):null;
  if(id&&!it){toast('Запись не найдена');return;}
  const d0=clampDate(S.now.date),v=x=>esc(x||'');
  let f='';
  if(kind==='travel'){
    const roads=!it||it.kind!=='straight';
    f=`<p class="note" style="margin:0 0 12px">Скорости в километрах в час. По ним линейка на карте считает время в пути.</p>
    <label class="field">Название<input name="name" maxlength="60" value="${v(it&&it.name)}" placeholder="Например: Метролинк, байк, катер"></label>
    <fieldset class="vis"><legend>Как едет</legend><label><input type="radio" name="tkind" value="roads" ${roads?'checked':''}> по дорогам</label><label><input type="radio" name="tkind" value="straight" ${roads?'':'checked'}> по прямой, без дорог (вертолёт, дрон)</label></fieldset>
    <div id="road-speeds" ${roads?'':'hidden'}><div class="two"><label class="field">По магистралям<input name="motorway" type="number" min="0" max="2000" step="0.5" value="${it?it.motorway:60}"></label><label class="field">По трассам<input name="trunk" type="number" min="0" max="2000" step="0.5" value="${it?it.trunk:50}"></label></div>
    <div class="two"><label class="field">По основным дорогам<input name="primary" type="number" min="0" max="2000" step="0.5" value="${it?it.primary:35}"></label><label class="field">Вне дорог и до дороги<input name="off" type="number" min="0.1" max="2000" step="0.5" value="${it?it.off:15}"></label></div>
    <span class="sub">Ноль на каком-то классе дорог значит, что по таким дорогам этот транспорт не ездит.</span></div>
    <label class="field" id="speed-box" ${roads?'hidden':''}>Скорость по прямой<input name="speed" type="number" min="0.1" max="2000" step="0.5" value="${it&&!roads?it.off:200}"></label>
    <div class="two"><label class="field">Сборы и остановки, минут<input name="delay" type="number" min="0" max="1440" value="${it?it.delay:0}"><span class="sub">Прибавляются один раз за поездку.</span></label>
    <label class="field">Пропускной пункт Догтауна, минут<input name="wall" type="number" min="0" max="1440" value="${it?it.wall:0}"><span class="sub">Если поездка начинается или кончается внутри стены.</span></label></div>
    <fieldset class="vis"><legend>Кто видит</legend><label><input type="radio" name="vis" value="стол" ${it&&it.vis==='мастер'?'':'checked'}> Все игроки</label><label><input type="radio" name="vis" value="мастер" ${it&&it.vis==='мастер'?'checked':''}> Только мастер</label></fieldset>
    <label class="field">Заметка<input name="note" maxlength="300" value="${v(it&&it.note)}"></label>`;
  }else if(kind==='dossier'){
    const vis=it?it.vis:'мастер';
    const plc=(S.places||[]).slice().sort((a,b)=>a.name.localeCompare(b.name,'ru'));
    f=`<p class="note" style="margin:0 0 12px">Игроки, которым открыта карточка, видят всё, кроме заметки мастера. Сведения добавляются в окне карточки.</p>
    <label class="field">Имя или название<input name="name" maxlength="80" value="${v(it&&it.name)}"></label>
    <label class="field">Позывной, прозвище или второе имя<input name="alias" maxlength="80" value="${v(it&&it.alias)}"><span class="sub">Показывается рядом с именем: у людей в кавычках.</span></label>
    <fieldset class="vis"><legend>Кто это</legend>${Object.entries(DTYPE).map(([k,t])=>`<label><input type="radio" name="dtype" value="${k}" ${(it?it.type:'person')===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <label class="field">Коротко: кто это<input name="role" maxlength="140" value="${v(it&&it.role)}" placeholder="Например: фиксер"></label>
    <label class="field">Как пачка к нему относится<select name="stance">${Object.entries(STANCE).map(([k,t])=>`<option value="${k}" ${(it?it.stance:'unknown')===k?'selected':''}>${t}</option>`).join('')}</select></label>
    <label class="field">Организация<input name="org" maxlength="120" value="${v(it&&it.org)}" placeholder="Например: Кенран-кай"></label>
    <fieldset class="vis"><legend>Карточка открыта</legend>${Object.entries(DVIS).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${vis===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <fieldset class="who" id="known-box" ${vis==='знают'?'':'hidden'}><legend>Кто из персонажей видит карточку</legend>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${c.id}" ${it&&(it.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</fieldset>
    <fieldset class="who"><legend>Кто из персонажей знаком лично (у организаций: имел дело)</legend>${CHARS.map(c=>`<label><input type="checkbox" name="met" value="${c.id}" ${it&&(it.met||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</fieldset>
    <div class="two"><label class="field">Последняя встреча<select name="last_date">${dateOpts(it&&it.last_date,'не указано')}</select></label>
    <label class="field">Где<select name="last_place"><option value="">не указано</option>${plc.map(p=>`<option value="${p.id}" ${it&&it.last_place===p.id?'selected':''}>${esc(p.name)}${placeTag(p)}</option>`).join('')}</select></label></div>
    <label class="field">Подробность о встрече<input name="last_note" maxlength="200" value="${v(it&&it.last_note)}"></label>
    <label class="field">Заметка мастера<textarea name="gm_note" rows="5" maxlength="4000">${v(it&&it.gm_note)}</textarea><span class="sub">Игроки её не видят. Сведения для игроков добавляются в самой карточке.</span></label>`;
  }else if(kind==='places'){
    const vis=it?it.vis:'стол';
    f=`<label class="field">Название<input name="name" maxlength="80" value="${v(it&&it.name)}" placeholder="Например: «Тузы»"></label>
    <label class="field">Тип<select name="type">${Object.entries(PLACE_TYPES).map(([k,t])=>`<option value="${k}" ${(it?it.type:'other')===k?'selected':''}>${t}</option>`).join('')}</select></label>
    <fieldset class="vis"><legend>Кто видит</legend>${Object.entries(PVIS).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${vis===k?'checked':''}> ${cap(t)}</label>`).join('')}</fieldset>
    <fieldset class="who" id="known-box" ${vis==='знают'?'':'hidden'}><legend>Кто из персонажей знает</legend>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${c.id}" ${it&&(it.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</fieldset>
    <label class="field">Описание для игроков<textarea name="note" rows="3" maxlength="2000">${v(it&&it.note)}</textarea></label>
    <label class="check imp-bgbox"><input type="checkbox" name="bg" ${it&&it.bg?'checked':''}> Фоновое место <span class="muted">(магазин, еда, ночлег; прячется переключателем «Фон» на карте)</span></label>
    <label class="field">Заметка мастера<textarea name="gm_note" rows="3" maxlength="2000">${v(it&&it.gm_note)}</textarea><span class="sub">Игроки её не видят.</span></label>`;
  }else if(kind==='windows'){
    f=`<label class="field">Название для игроков<input name="name" maxlength="80" value="${v(it&&it.name)}" placeholder="Например: Арка 3"></label>
    <label class="field">Название для мастера<input name="gm" maxlength="120" value="${v(it&&it.gm)}" placeholder="Например: Арка 3. Та, что выжила"><span class="sub">Игроки видят название этапа с его первого дня. Если поле пустое, мастер видит то же название.</span></label>
    <div class="two"><label class="field">Начало<select name="from">${dateOpts(it?it.from:d0)}</select></label><label class="field">Окончание<select name="to">${dateOpts(it?it.to:d0)}</select></label></div>
    <label class="check"><input type="checkbox" name="inter" ${it&&it.inter?'checked':''}> Промежуточная арка</label>`;
  }else if(kind==='rhythm'){
    const monthly=!!(it&&it.monthDay);
    f=`<label class="field">Название<input name="title" maxlength="120" value="${v(it&&it.title)}" placeholder="Например: Риг варит кофе с кардамоном"></label>
    <fieldset class="vis"><legend>Повторяется</legend><label><input type="radio" name="mode" value="weekly" ${monthly?'':'checked'}> по дням недели</label><label><input type="radio" name="mode" value="monthly" ${monthly?'checked':''}> раз в месяц</label></fieldset>
    <fieldset class="who" id="wd-box" ${monthly?'hidden':''}><legend>Дни недели</legend>${WDS.map((w,i)=>`<label><input type="checkbox" name="wd" value="${i}" ${it&&(it.wd||[]).includes(i)?'checked':''}> ${w}</label>`).join('')}</fieldset>
    <label class="field" id="md-box" ${monthly?'':'hidden'}>Число месяца<input name="monthDay" type="number" min="1" max="31" value="${it&&it.monthDay||1}"></label>
    <label class="field">Чья привычка<select name="who"><option value="">ничья: событие города</option>${CHARS.map(c=>`<option value="${c.id}" ${it&&it.who===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select><span class="sub">Привычка персонажа показывается в его строке календаря.</span></label>
    <div class="two"><label class="field">Начиная с<select name="from">${dateOpts(it&&it.from,'с начала кампании')}</select></label><label class="field">Заканчивается<select name="to">${dateOpts(it&&it.to,'не заканчивается')}</select></label></div>
    <label class="field">Описание<textarea name="note" rows="3" maxlength="1000">${v(it&&it.note)}</textarea></label>
    <fieldset class="vis"><legend>Видимость</legend><label><input type="radio" name="vis" value="стол" ${it&&it.vis==='мастер'?'':'checked'}> Все игроки</label><label><input type="radio" name="vis" value="мастер" ${it&&it.vis==='мастер'?'checked':''}> Только мастер</label></fieldset>`;
  }else if(kind==='clocks'){
    f=`<label class="field">Название<input name="title" maxlength="120" value="${v(it&&it.title)}" placeholder="Например: Рекламация 2075-0726-К"></label>
    <label class="field">Срок<select name="when">${dateOpts(it&&it.when,'без срока')}</select><span class="sub">Таймер со сроком появляется в строке «План мастера» в этот день.</span></label>
    <label class="field">Описание<textarea name="note" rows="4" maxlength="1000" placeholder="Что должно случиться и что будет, когда срок наступит">${v(it&&it.note)}</textarea></label>`;
  }else{
    f=`<label class="field">Название<input name="title" maxlength="120" value="${v(it&&it.title)}"></label>
    <div class="two"><label class="field">Начало<select name="from">${dateOpts(it?it.from:d0)}</select></label><label class="field">Окончание<select name="to">${dateOpts(it?it.to:d0)}</select></label></div>
    <label class="field">Сессия<input name="session" maxlength="60" value="${v(it&&it.session)}" placeholder="Например: сессия 2"></label>
    <label class="field">${kind==='plan'?'Описание для мастера':'Описание для игроков'}<textarea name="note" rows="4" maxlength="2000">${v(it&&it.note)}</textarea>${kind==='plan'?'<span class="sub">При переносе в хронику станет заметкой мастера, игроки её не увидят.</span>':''}</label>${kind==='past'?`<label class="field">Заметка мастера<textarea name="gm_note" rows="3" maxlength="2000">${v(it&&it.gm_note)}</textarea><span class="sub">Игроки её не видят.</span></label>`:''}`;
    if(kind==='plan'){
      const c=it&&it.cover;
      f+=`<fieldset class="anketa"><legend>Что видят игроки</legend>
      <label class="check"><input type="checkbox" name="cover_on" ${c?'checked':''}> Показать игрокам как общее событие</label>
      <p class="muted small" style="margin:4px 0 0">Игроки увидят на эти дни только этот текст. Настоящее описание останется скрытым. Так можно занять дату, чтобы на неё ничего не планировали.</p>
      <div id="cover-box" ${c?'':'hidden'}>
        <label class="field">Что видят игроки<input name="cover_title" maxlength="120" value="${v(c&&c.title)}" placeholder="Например: Риг позвал всех к себе в ангар"></label>
        <label class="field">Подробности для игроков<textarea name="cover_note" rows="2" maxlength="1000">${v(c&&c.note)}</textarea></label>
        <fieldset class="who"><legend>Кого касается</legend>${CHARS.map(x=>`<label><input type="checkbox" name="cover_who" value="${x.id}" ${c&&(c.who||[]).includes(x.id)?'checked':''}> ${esc(x.name)}</label>`).join('')}<span class="muted small" style="flex-basis:100%">Если никто не отмечен, событие касается всей пачки.</span></fieldset>
      </div></fieldset>`;
    }
  }
  curKey=null;
  showPanel(`<p class="kind">${KIND_LABEL[kind]}</p><h2>${it?'Изменить':KIND_NEW[kind]}</h2><form id="item-form" data-kind="${kind}" data-id="${it?it.id:''}" data-x="${pos?pos.x:(it&&it.x!=null?it.x:'')}" data-y="${pos?pos.y:(it&&it.y!=null?it.y:'')}" novalidate>${f}
  <p class="err" id="form-err" role="alert"></p>
  <div class="acts"><button type="submit" class="btn primary">${it?'Сохранить':'Добавить'}</button>${kind==='dossier'&&it?`<button type="button" class="btn" data-act="dback" data-id="${it.id}">Отмена</button>`:'<button type="button" class="btn" data-act="close">Отмена</button>'}${it?`<button type="button" class="btn plain" data-act="del-item" data-kind="${kind}" data-id="${it.id}">Удалить</button>`:''}</div></form>`);
  const form=document.getElementById('item-form'),F=n=>form.elements.namedItem(n);
  form.addEventListener('input',()=>{document.getElementById('form-err').textContent='';});
  form.addEventListener('change',ev=>{
    const nm=ev.target.name;
    if(nm==='mode'){const m=ev.target.value==='monthly';document.getElementById('wd-box').hidden=m;document.getElementById('md-box').hidden=!m;}
    if(nm==='cover_on')document.getElementById('cover-box').hidden=!ev.target.checked;
    if(nm==='tkind'){const r=ev.target.value==='roads';document.getElementById('road-speeds').hidden=!r;document.getElementById('speed-box').hidden=r;}
    if(nm==='vis'&&document.getElementById('known-box'))document.getElementById('known-box').hidden=ev.target.value!=='знают';
    if(nm==='from'&&F('to')&&F('from').value&&F('to').value&&F('to').value<F('from').value)F('to').value=F('from').value;
  });
}
function collectItem(form){
  const kind=form.dataset.kind,F=n=>form.elements.namedItem(n),val=n=>(F(n)?F(n).value:'').trim();
  const checked=n=>[...form.querySelectorAll(`input[name="${n}"]:checked`)].map(x=>x.value);
  const radio=n=>{const x=form.querySelector(`input[name="${n}"]:checked`);return x?x.value:'';};
  const b={id:form.dataset.id||undefined};
  if(kind==='travel'){const straight=radio('tkind')==='straight';Object.assign(b,{name:val('name'),kind:straight?'straight':'roads',motorway:straight?'0':val('motorway'),trunk:straight?'0':val('trunk'),primary:straight?'0':val('primary'),off:straight?val('speed'):val('off'),delay:val('delay')||'0',wall:val('wall')||'0',vis:radio('vis'),note:val('note')});}
  else if(kind==='dossier'){const old=(S.dossier||[]).find(x=>x.id===form.dataset.id);Object.assign(b,{name:val('name'),alias:val('alias'),type:radio('dtype'),role:val('role'),stance:val('stance'),org:val('org'),vis:radio('vis'),known:checked('known'),met:checked('met'),last_date:val('last_date'),last_place:val('last_place'),last_note:val('last_note'),gm_note:val('gm_note'),facts:old?old.facts:[]});}
  else if(kind==='places'){Object.assign(b,{name:val('name'),type:val('type'),vis:radio('vis'),known:checked('known'),note:val('note'),gm_note:val('gm_note'),bg:!!(form.elements.namedItem('bg')&&form.elements.namedItem('bg').checked),x:+form.dataset.x,y:+form.dataset.y});}
  else if(kind==='windows'){Object.assign(b,{name:val('name'),gm:val('gm'),from:val('from'),to:val('to'),inter:F('inter').checked});}
  else if(kind==='rhythm'){Object.assign(b,{title:val('title'),mode:radio('mode'),wd:checked('wd').map(Number),monthDay:+val('monthDay'),who:val('who'),from:val('from'),to:val('to'),note:val('note'),vis:radio('vis')});}
  else if(kind==='clocks'){Object.assign(b,{title:val('title'),when:val('when'),note:val('note')});}
  else{Object.assign(b,{title:val('title'),from:val('from'),to:val('to'),session:val('session'),note:val('note')});
    if(kind==='past')b.gm_note=val('gm_note');
    if(kind==='plan'&&F('cover_on').checked)b.cover={title:val('cover_title'),note:val('cover_note'),who:checked('cover_who')};}
  return b;
}


/* ===== Форма новой записи ===== */
function openForm(date,ed){
  if(RO()){toast('Предпросмотр: действия отключены');return;}
  curKey=null;
  const days=range(CAL_START,CAL_END);
  const d0=ed?ed.from:(days.includes(date)?date:clampDate(S.now.date));
  const opts=sel=>days.map(d=>`<option value="${d}" ${d===sel?'selected':''}>${fFull(d)}</option>`).join('');
  const me=ed?(ed.author==='gm'?null:ed.author):(V==='gm'?null:V);
  showPanel(`<h2>${ed?'Изменить запись':'Новая запись'}</h2><form id="entry-form" novalidate>
  <fieldset class="types"><legend>Тип записи</legend>${Object.entries(TYPES).map(([k,t],i)=>`<label class="tchip t-${k}"><input type="radio" name="type" value="${k}" ${i===0?'checked':''}><span>${t.name}</span></label>`).join('')}</fieldset>
  <p class="hint muted small" id="type-hint">${TYPES.meet.hint}</p>
  <label class="field">Название<input name="title" maxlength="80" autocomplete="off" placeholder="Например: новый прикид для Кару"></label>
  <div class="two"><label class="field">Начало<select name="from">${opts(d0)}</select></label><label class="field">Окончание<select name="to">${opts(d0)}</select></label></div>
  <p class="note" id="block-hint" hidden></p>
  <label class="field">Время суток<select name="tod"><option value="">не указано</option>${TOD.map(t=>`<option value="${t}">${t}</option>`).join('')}</select></label>
  <div class="free-box" id="free-box" aria-live="polite"></div>
  <fieldset class="anketa"><legend>Анкета</legend>
    <fieldset class="who"><legend>Кто</legend>${CHARS.map(c=>`<label><input type="checkbox" name="who" value="${c.id}" ${c.id===me?'checked disabled':''}> ${esc(c.name)}</label>`).join('')}<label id="plus-opt" class="plus-opt"><input type="checkbox" name="open" value="1"> <b class="plus">+</b> <span class="muted small">любой может попроситься в участники</span></label></fieldset>
    <label class="field">Место на карте<select name="place"><option value="">не выбрано</option>${placesVisible().slice().sort((a,b)=>a.name.localeCompare(b.name,'ru')).map(p=>`<option value="${p.id}">${esc(p.name)}${placeTag(p)}</option>`).join('')}</select>${V==='gm'?'<span class="sub">Название скрытого места не подставляется в «Где», чтобы не показать его игрокам.</span>':''}</label>
  <label class="field">Где<input name="where" maxlength="120" autocomplete="off" placeholder="Например: любой целевой магазин"></label>
    <label class="field">Условие<input name="cond" maxlength="160" autocomplete="off" placeholder="Например: 1000¥ на шопинг, можно без"></label>
    <label class="field">Цель<textarea name="goal" rows="3" maxlength="2000" placeholder="${TYPES.meet.goal}"></textarea><span class="sub">Сослаться на карточку досье можно так: [[Имя]].</span></label>
  </fieldset>
  <label class="field" id="effect-field" hidden>Изменение действует с<select name="effect">${opts(addDays(d0,1)>CAL_END?CAL_END:addDays(d0,1))}</select><span class="sub">С этой даты повышение учитывается в игре.</span></label>
  <fieldset class="vis"><legend>Видимость</legend><label><input type="radio" name="vis" value="стол" checked> Все игроки</label><label><input type="radio" name="vis" value="лично" id="vis-private"> Только участники и мастер</label><span class="sub muted small" id="vis-note" hidden>Записи с «+» видны всем игрокам.</span></fieldset>
  <p class="err" id="form-err" role="alert"></p>
  <div class="acts"><button type="submit" class="btn primary">${ed?'Сохранить':'Добавить запись'}</button><button type="button" class="btn" data-act="close">Отмена</button></div></form>`);
  const f=document.getElementById('entry-form');const F=n=>f.elements.namedItem(n);
  if(ed){
    f.querySelectorAll('input[name="type"]').forEach(x=>{x.checked=x.value===ed.type;x.disabled=true;});
    document.getElementById('type-hint').textContent=TYPES[ed.type].hint+(ed.type==='grow'&&V!=='gm'?' После правки заявка снова уйдёт мастеру на проверку.':'');
    F('title').value=ed.title;F('to').value=ed.to||ed.from;F('tod').value=ed.tod||'';
    f.querySelectorAll('input[name="who"]').forEach(x=>{x.checked=ed.who.includes(x.value)||x.value===ed.author;if(x.value===ed.author)x.disabled=true;});
    F('open').checked=!!ed.open;F('where').value=ed.where||'';if(ed.place&&placeById(ed.place))F('place').value=ed.place;F('cond').value=ed.cond||'';F('goal').value=ed.goal||'';F('goal').placeholder=TYPES[ed.type].goal;
    const vr=f.querySelector(`input[name="vis"][value="${ed.vis==='лично'?'лично':'стол'}"]`);if(vr)vr.checked=true;
    document.getElementById('effect-field').hidden=ed.type!=='grow';if(ed.effect)F('effect').value=ed.effect;
    document.getElementById('plus-opt').hidden=ed.type==='grow';
  }
  const syncHint=()=>{
    const hint=document.getElementById('block-hint');if(V==='gm'){hint.hidden=true;return;}
    const who=[...f.querySelectorAll('input[name="who"]:checked')].map(x=>x.value).concat(me?[me]:[]);
    const a=F('from').value,z=F('to').value;
    const hits=blocks().filter(b=>b.from<=z&&b.to>=a&&who.some(c=>blockFor(b,c)));
    hint.textContent=hits.length?'В эти дни общее событие: '+hits.map(b=>'«'+b.title+'», '+fRange(b.from,b.to)).join('; ')+'. Лучше выбрать другие дни.':'';
    hint.hidden=!hits.length;
  };
  const syncOpen=()=>{const on=F('open').checked;const priv=document.getElementById('vis-private');priv.disabled=on;if(on)f.querySelector('input[name="vis"][value="стол"]').checked=true;document.getElementById('vis-note').hidden=!on;};
  f.addEventListener('input',()=>{document.getElementById('form-err').textContent='';});
  f.addEventListener('change',ev=>{
    const nm=ev.target.name;
    if(nm==='type'){const t=ev.target.value;document.getElementById('type-hint').textContent=TYPES[t].hint;document.getElementById('effect-field').hidden=t!=='grow';F('goal').placeholder=TYPES[t].goal;
      document.getElementById('plus-opt').hidden=t==='grow';if(t==='grow'){F('open').checked=false;syncOpen();}}
    if(nm==='open')syncOpen();
    if(nm==='place'&&!F('where').value.trim()){const w=placeWhere(placeById(F('place').value));if(w)F('where').value=w;}
    if(nm==='from'){if(F('to').value<F('from').value)F('to').value=F('from').value;if(F('effect').value<F('from').value)F('effect').value=F('from').value;}
    if(nm==='from'||nm==='to'||nm==='who')syncHint();
    if(nm==='from'||nm==='to'||nm==='who'||nm==='tod')freeRefresh(f,ed,me);
  });
  syncOpen();syncHint();freeRefresh(f,ed,me);
  f.addEventListener('submit',async ev=>{
    ev.preventDefault();
    const err=m=>{document.getElementById('form-err').textContent=m;};
    const type=ed?ed.type:f.querySelector('input[name="type"]:checked').value;
    const title=F('title').value.trim();
    const who=[...f.querySelectorAll('input[name="who"]:checked')].map(x=>x.value);
    if(me&&!who.includes(me))who.unshift(me);
    const open=type!=='grow'&&F('open').checked;
    const from=F('from').value,to=F('to').value,goal=F('goal').value.trim();
    if(!title)return err('Укажите название записи.');
    if(!who.length&&!open)return err('Выберите хотя бы одного участника или отметьте «+».');
    if(to<from)return err('Дата окончания раньше даты начала.');
    if(type==='grow'&&who.length!==1)return err('Развитие оформляется на одного персонажа.');
    if(type==='grow'&&!goal)return err('Для развития заполните цель: что повышается и как персонаж этого добивается.');
    const body={type,title,from,to,tod:F('tod').value,who,open,place:F('place').value,where:F('where').value.trim(),cond:F('cond').value.trim(),goal,
      vis:open?'стол':f.querySelector('input[name="vis"]:checked').value,effect:type==='grow'?F('effect').value:''};
    const j=await apiPost(ed?`/api/entries/${encodeURIComponent(ed.id)}/edit`:'/api/entries',body,err);
    if(j)finish(j.msg);
  });
}
