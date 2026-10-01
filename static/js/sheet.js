/* ===== Лист персонажа (Shadowrun): нуйены, репутация по фракциям, контакты =====
   Данные ведёт мастер. Игрок видит только свои проводки, контакты и репутацию, и только у фракций, о которых его персонаж знает:
   сервер отдаёт уже отфильтрованное, а sheetView повторяет те же правила для предпросмотра мастера «как видит игрок».
   Чистые функции вынесены наверх, их проверяют автотесты в Node. */
const FACTION_KIND={corp:'Корпорация',gang:'Банда',gov:'Власть',org:'Организация',other:'Другое'};
const FACTION_VIS={'стол':'Все персонажи о ней знают','знают':'Знают только отмеченные персонажи','мастер':'Скрыта от игроков'};
const STANDING_LBL={'-5':'Объявлена охота','-4':'Враг','-3':'Неприязнь','-2':'Недоверие','-1':'Настороженность','0':'Нейтрально','1':'Знакомы','2':'Доверие','3':'Уважение','4':'Друг','5':'Свой'};
const SR_KINDS=['money','factions','standing','contacts'];
const SR_LEDGER_SHOWN=8;

const standingLabel=v=>STANDING_LBL[String(v)]||'';
const signed=n=>(n>0?'+':n<0?'−':'')+Math.abs(n);
const fmtNuyen=n=>signed(n).replace(/\B(?=(\d{3})+(?!\d))/g,' ')+' ¥';
const fmtBalance=n=>(n<0?'−':'')+String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g,' ')+' ¥';
const sheetBalance=(char,money)=>(money||[]).filter(m=>m.char===char).reduce((a,m)=>a+m.delta,0);
/* Проводки персонажа, новые сверху: по дате, при равной дате позже внесённые выше. */
const sheetLedger=(char,money)=>(money||[]).map((m,i)=>({m,i})).filter(x=>x.m.char===char)
  .sort((a,b)=>a.m.date<b.m.date?1:a.m.date>b.m.date?-1:b.i-a.i).map(x=>x.m);
/* У фракции из ответа сервера поля vis нет: он уже отфильтровал. У полного списка мастера оно есть. */
const factionOpen=(f,c)=>f.vis===undefined||f.vis==='стол'||(f.vis==='знают'&&(f.known||[]).includes(c));
function sheetView(d,chars,cardIds){
  const mine=new Set(chars),F=new Map((d.factions||[]).map(f=>[f.id,f]));
  const standing=(d.standing||[]).filter(s=>mine.has(s.char)&&F.has(s.faction)&&factionOpen(F.get(s.faction),s.char))
    .map(s=>({id:s.id,char:s.char,faction:s.faction,value:s.value,note:s.note||''}));
  const shown=new Set(standing.map(s=>s.faction));
  return {
    money:(d.money||[]).filter(m=>mine.has(m.char)).map(m=>({id:m.id,char:m.char,delta:m.delta,note:m.note||'',date:m.date})),
    standing,
    factions:[...F.values()].filter(f=>f.vis===undefined||chars.some(c=>factionOpen(f,c))||shown.has(f.id)).map(f=>({id:f.id,name:f.name,kind:f.kind||'other',note:f.note||''})),
    contacts:(d.contacts||[]).filter(c=>mine.has(c.char)).map(c=>({id:c.id,char:c.char,name:c.name,connection:c.connection,loyalty:c.loyalty,services:c.services||'',note:c.note||'',
      ...(cardIds.has(c.card)?{card:c.card}:{})})),
  };
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={FACTION_KIND,STANDING_LBL,standingLabel,signed,fmtNuyen,fmtBalance,sheetBalance,sheetLedger,factionOpen,sheetView};
}

/* ----- вывод (только в браузере) ----- */
Object.assign(UI,{sheetChar:null,ledgerAll:{}});
const srEdit=(kind,id)=>V==='gm'?`<span class="sh-acts"><button type="button" class="btn plain mini" data-act="sr-edit" data-kind="${kind}" data-id="${esc(id)}">Изменить</button><button type="button" class="btn plain mini" data-act="item-history" data-kind="${kind}" data-id="${esc(id)}">История</button><button type="button" class="btn plain mini" data-act="del-item" data-kind="${kind}" data-id="${esc(id)}">Удалить</button></span>`:'';
const srGm=t=>V==='gm'&&t?`<span class="sh-gm"><b>Мастер:</b> ${esc(t)}</span>`:'';
function ledgerHTML(c,d){
  const all=sheetLedger(c,d.money),open=!!UI.ledgerAll[c],list=open?all:all.slice(0,SR_LEDGER_SHOWN);
  if(!all.length)return '<p class="muted">Записей пока нет.</p>';
  return `<ul class="ledger">${list.map(m=>`<li><span class="lg-d">${esc(fDate(m.date))}</span><b class="lg-a ${m.delta<0?'neg':'pos'}">${fmtNuyen(m.delta)}</b><span class="lg-n">${esc(m.note||'')}${srGm(m.gm_note)}</span>${srEdit('money',m.id)}</li>`).join('')}</ul>`
    +(all.length>SR_LEDGER_SHOWN?`<button type="button" class="btn plain mini" data-act="sr-ledger" data-id="${esc(c)}">${open?'Свернуть':`Показать все (${all.length})`}</button>`:'');
}
function standingHTML(c,d){
  const F=new Map((d.factions||[]).map(f=>[f.id,f])),list=(d.standing||[]).filter(s=>s.char===c);
  if(!list.length)return '<p class="muted">Записей пока нет.</p>';
  return `<ul class="standings">${list.map(s=>{const f=F.get(s.faction);
    return `<li class="st-row"><div class="st-top"><span class="st-f">${f?esc(f.name):'<i class="muted">фракция удалена</i>'}</span><b class="st-v st-${s.value<0?'neg':s.value>0?'pos':'zero'}">${signed(s.value)}</b><span class="st-l">${esc(standingLabel(s.value))}</span></div>
    <span class="st-bar" role="img" aria-label="Репутация ${signed(s.value)} из ±5"><i style="left:${(s.value+5)*10}%"></i></span>
    ${s.note?`<span class="st-n">${esc(s.note)}</span>`:''}${f&&f.note?`<span class="st-n muted">${esc(f.note)}</span>`:''}${srGm(s.gm_note)}${srEdit('standing',s.id)}</li>`;}).join('')}</ul>`;
}
function contactsHTML(c,d){
  const list=(d.contacts||[]).filter(x=>x.char===c);
  if(!list.length)return '<p class="muted">Записей пока нет.</p>';
  return `<ul class="contacts">${list.map(x=>`<li class="ct-row"><div class="ct-top">${x.card?`<button type="button" class="dlink" data-open="n:${esc(x.card)}">${esc(x.name)}</button>`:`<b>${esc(x.name)}</b>`}
    <span class="ct-r" title="Связи (влияние и знакомства) и лояльность">Связи ${x.connection} · Лояльность ${x.loyalty}</span></div>
    ${x.services?`<span class="ct-s">${esc(x.services)}</span>`:''}${x.note?`<span class="ct-n">${rich(x.note)}</span>`:''}${srGm(x.gm_note)}${srEdit('contacts',x.id)}</li>`).join('')}</ul>`;
}
function charSheetHTML(c,d){
  const gm=V==='gm',bal=sheetBalance(c,d.money);
  return `<article class="sh-char" aria-label="${esc(CN[c]||c)}"><h2>${esc(CN[c]||c)}</h2><div class="sh-grid">
  <section class="sh-box"><h3>Нуйены</h3><p class="sh-bal ${bal<0?'neg':''}">${fmtBalance(bal)}</p>${ledgerHTML(c,d)}${gm?`<div class="acts"><button type="button" class="btn small" data-act="sr-new" data-kind="money" data-char="${esc(c)}">Добавить проводку</button></div>`:''}</section>
  <section class="sh-box"><h3>Репутация</h3>${standingHTML(c,d)}${gm?`<div class="acts"><button type="button" class="btn small" data-act="sr-new" data-kind="standing" data-char="${esc(c)}">Записать репутацию</button></div>`:''}</section>
  <section class="sh-box"><h3>Контакты</h3>${contactsHTML(c,d)}${gm?`<div class="acts"><button type="button" class="btn small" data-act="sr-new" data-kind="contacts" data-char="${esc(c)}">Добавить контакт</button></div>`:''}</section>
  </div></article>`;
}
function factionsHTML(){
  const list=S.factions||[];
  return `<section class="sh-fac"><div class="sec-head"><h2>Фракции</h2><button type="button" class="btn small" data-act="sr-new" data-kind="factions">Добавить фракцию</button></div>
  <p class="note">Корпорации, банды и другие силы, с которыми у персонажей складывается репутация. Фракцию видят персонажи, которым вы её открыли.</p>
  ${list.length?`<ul class="factions">${list.map(f=>`<li class="fc-row"><div class="fc-top"><b>${esc(f.name)}</b><span class="tag">${esc(FACTION_KIND[f.kind]||'Другое')}</span><span class="muted small">${esc(f.vis==='знают'?'знают: '+joinNames((f.known||[]).map(c=>CN[c]||c)):FACTION_VIS[f.vis]||'')}</span></div>
    ${f.note?`<span class="ct-n">${esc(f.note)}</span>`:''}${srGm(f.gm_note)}${srEdit('factions',f.id)}</li>`).join('')}</ul>`:'<p class="muted">Фракций пока нет. Добавьте первую, чтобы записывать репутацию.</p>'}</section>`;
}
function rSheet(){
  const gm=V==='gm';
  if(gm){
    if(!CHARS.length)return '<section class="sheet"><div class="d-top"><h1>Лист</h1></div><p class="muted">В players.toml нет ни одного персонажа.</p></section>';
    const cur=CHARS.some(c=>c.id===UI.sheetChar)?UI.sheetChar:CHARS[0].id,d={money:S.money||[],standing:S.standing||[],factions:S.factions||[],contacts:S.contacts||[]};
    return `<section class="sheet"><div class="d-top"><h1>Лист</h1></div>
    <p class="note">Нуйены, репутация и контакты персонажей. Игрок видит только своё и только у фракций, о которых его персонаж знает; заметки мастера до игроков не доходят.</p>
    <table class="sh-sum"><caption class="sr-only">Нуйены персонажей</caption><thead><tr><th scope="col">Персонаж</th><th scope="col">Нуйены</th><th scope="col">Репутация</th><th scope="col">Контакты</th></tr></thead><tbody>${CHARS.map(c=>`<tr><th scope="row"><button type="button" class="btn plain mini" data-act="sr-char" data-id="${esc(c.id)}">${esc(c.name)}</button></th><td class="${sheetBalance(c.id,d.money)<0?'neg':''}">${fmtBalance(sheetBalance(c.id,d.money))}</td><td>${d.standing.filter(s=>s.char===c.id).length}</td><td>${d.contacts.filter(x=>x.char===c.id).length}</td></tr>`).join('')}</tbody></table>
    <div class="seg" role="group" aria-label="Персонаж">${CHARS.map(c=>`<button type="button" data-act="sr-char" data-id="${esc(c.id)}" aria-pressed="${c.id===cur}">${esc(c.name)}</button>`).join('')}</div>
    ${charSheetHTML(cur,d)}${factionsHTML()}</section>`;
  }
  const chars=viewChars()||[],d=sheetView(S,chars,new Set(dossierVisible().map(c=>c.id)));
  if(!chars.length)return '<section class="sheet"><div class="d-top"><h1>Лист</h1></div><p class="muted">За вами не закреплён персонаж.</p></section>';
  return `<section class="sheet"><div class="d-top"><h1>Лист</h1></div><p class="note">Нуйены, репутация и контакты вашего персонажа. Данные ведёт мастер.</p>${chars.map(c=>charSheetHTML(c,d)).join('')}</section>`;
}

/* ----- формы мастера ----- */
function srCharSelect(sel){return `<label class="field">Персонаж<select name="char">${CHARS.map(c=>`<option value="${esc(c.id)}" ${c.id===sel?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>`;}
function srGmNote(it,limit){return `<label class="field">Заметка мастера<textarea name="gm_note" rows="2" maxlength="${limit}">${esc(it&&it.gm_note)}</textarea><span class="sub">Игроки её не видят.</span></label>`;}
function openSrForm(kind,id,char){
  if(V!=='gm')return;
  const it=id?(S[kind]||[]).find(x=>x.id===id):null;
  if(id&&!it){toast('Запись не найдена');return;}
  const c0=it?it.char:(char||(CHARS[0]||{}).id),v=x=>esc(x||'');
  let title,f;
  if(kind==='money'){
    const neg=it&&it.delta<0;title=it?'Изменить проводку':'Новая проводка';
    f=`${srCharSelect(c0)}
    <fieldset class="vis"><legend>Что это</legend><label><input type="radio" name="sign" value="1" ${neg?'':'checked'}> Доход</label><label><input type="radio" name="sign" value="-1" ${neg?'checked':''}> Расход</label></fieldset>
    <label class="field">Сумма, нуйенов<input name="amount" type="number" min="1" max="1000000000" step="1" inputmode="numeric" value="${it?Math.abs(it.delta):''}"></label>
    <label class="field">За что<input name="note" maxlength="200" value="${v(it&&it.note)}" placeholder="Например: плата за работу, ремонт кибердеки"></label>
    <label class="field">Когда<select name="date">${dateOpts(it?it.date:S.now.date)}</select></label>${srGmNote(it,500)}`;
  }else if(kind==='factions'){
    const vis=it?it.vis:'мастер';title=it?'Изменить фракцию':'Новая фракция';
    f=`<label class="field">Название<input name="name" maxlength="60" value="${v(it&&it.name)}" placeholder="Например: Ареса, Кенран-кай"></label>
    <label class="field">Что это<select name="fkind">${Object.entries(FACTION_KIND).map(([k,t])=>`<option value="${k}" ${(it?it.kind:'corp')===k?'selected':''}>${t}</option>`).join('')}</select></label>
    <fieldset class="vis"><legend>Кто о ней знает</legend>${Object.entries(FACTION_VIS).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${vis===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <fieldset class="who" id="known-box" ${vis==='знают'?'':'hidden'}><legend>Какие персонажи знают</legend>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${esc(c.id)}" ${it&&(it.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</fieldset>
    <label class="field">Описание для тех, кто о ней знает<textarea name="note" rows="3" maxlength="1000">${v(it&&it.note)}</textarea></label>${srGmNote(it,1000)}`;
  }else if(kind==='standing'){
    const fs=S.factions||[];title=it?'Изменить репутацию':'Репутация у фракции';
    if(!fs.length){toast('Сначала добавьте хотя бы одну фракцию');return;}
    f=`${srCharSelect(c0)}
    <label class="field">Фракция<select name="faction">${fs.map(x=>`<option value="${esc(x.id)}" ${it&&it.faction===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label>
    <label class="field">Отношение<select name="value">${Object.keys(STANDING_LBL).map(Number).sort((a,b)=>b-a).map(n=>`<option value="${n}" ${(it?it.value:0)===n?'selected':''}>${signed(n)} ${STANDING_LBL[String(n)]}</option>`).join('')}</select></label>
    <label class="field">Что известно игроку<input name="note" maxlength="300" value="${v(it&&it.note)}" placeholder="Например: помог с эвакуацией, но задолжал"></label>${srGmNote(it,500)}`;
  }else{
    const cards=(S.dossier||[]).slice().sort((a,b)=>a.name.localeCompare(b.name,'ru'));title=it?'Изменить контакт':'Новый контакт';
    f=`${srCharSelect(c0)}
    <label class="field">Карточка досье<select name="card"><option value="">нет карточки</option>${cards.map(x=>`<option value="${esc(x.id)}" ${it&&it.card===x.id?'selected':''}>${esc(x.name)}${x.alias?` («${esc(x.alias)}»)`:''}</option>`).join('')}</select><span class="sub">Игрок увидит ссылку, только если карточка открыта его персонажу.</span></label>
    <label class="field">Имя контакта<input name="name" maxlength="80" value="${v(it&&it.name)}" placeholder="Подставится из карточки, если оставить пустым"></label>
    <div class="two"><label class="field">Связи (1–12)<input name="connection" type="number" min="1" max="12" step="1" value="${it?it.connection:1}"><span class="sub">Насколько влиятелен.</span></label>
    <label class="field">Лояльность (1–6)<input name="loyalty" type="number" min="1" max="6" step="1" value="${it?it.loyalty:1}"><span class="sub">Насколько предан персонажу.</span></label></div>
    <label class="field">Чем помогает<input name="services" maxlength="300" value="${v(it&&it.services)}" placeholder="Например: достаёт оружие, чинит технику"></label>
    <label class="field">Заметка для игрока<textarea name="note" rows="2" maxlength="1000">${v(it&&it.note)}</textarea></label>${srGmNote(it,1000)}`;
  }
  curKey=null;
  showPanel(`<p class="kind">Лист персонажа</p><h2>${title}</h2><form id="sr-form" data-kind="${kind}" data-id="${it?esc(it.id):''}" novalidate>${f}
  <p class="err" id="form-err" role="alert"></p><div class="acts"><button type="submit" class="btn primary">${it?'Сохранить':'Добавить'}</button><button type="button" class="btn" data-act="close">Отмена</button></div></form>`);
  const form=document.getElementById('sr-form');
  form.addEventListener('input',()=>{document.getElementById('form-err').textContent='';});
  form.addEventListener('change',ev=>{if(ev.target.name==='vis'&&document.getElementById('known-box'))document.getElementById('known-box').hidden=ev.target.value!=='знают';});
}
async function submitSrForm(form){
  const kind=form.dataset.kind,F=n=>form.elements.namedItem(n),val=n=>(F(n)?F(n).value:'').trim(),err=m=>{document.getElementById('form-err').textContent=m;};
  const b={id:form.dataset.id||undefined,char:F('char')?F('char').value:undefined,gm_note:val('gm_note')};
  if(kind==='money'){
    const n=Number(val('amount'));
    if(!val('amount')||!Number.isInteger(n)||n<1)return err('Укажите сумму: целое число нуйенов.');
    Object.assign(b,{delta:n*Number(form.querySelector('input[name="sign"]:checked').value),note:val('note'),date:val('date')});
  }else if(kind==='factions'){
    Object.assign(b,{name:val('name'),kind:val('fkind'),vis:form.querySelector('input[name="vis"]:checked').value,known:[...form.querySelectorAll('input[name="known"]:checked')].map(x=>x.value),note:val('note')});
  }else if(kind==='standing'){
    Object.assign(b,{faction:val('faction'),value:Number(val('value')),note:val('note')});
  }else{
    Object.assign(b,{card:val('card'),name:val('name'),connection:Number(val('connection')),loyalty:Number(val('loyalty')),services:val('services'),note:val('note')});
  }
  const j=await apiPost('/api/gm/items/'+kind,b,err,true);
  if(j)finish(j.msg);
}
function srAct(a,b){
  if(a==='sr-char'){UI.sheetChar=b.dataset.id;render(true);}
  else if(a==='sr-ledger'){UI.ledgerAll[b.dataset.id]=!UI.ledgerAll[b.dataset.id];render(true);}
  else if(a==='sr-new')openSrForm(b.dataset.kind,null,b.dataset.char);
  else if(a==='sr-edit')openSrForm(b.dataset.kind,b.dataset.id);
}
