/* ===== «Что было раньше»: пересказ для того, кто пропустил сессию =====
   Пересказ пишет Claude по ключу или, если включён режим «через мастера», сам мастер в своём чате с Claude. В обоих случаях только по тому,
   что видит сам игрок (хроника, сведения, раздатки, его сыгранные записи). Здесь выбор периода, показ результата, список просьб игрока
   и очередь просьб у мастера. Чистые функции (выбор периода, строка о просьбе) проверяют автотесты в Node. */
const RECAP_NOTE_GM='Пересказ готовит мастер с помощью нейросети (Claude) по вашей хронике, сведениям и раздаткам, поэтому он может ошибаться. Мастер видит ровно то, что видите вы, и ничего больше. Ответ приходит не сразу: когда мастер вставит пересказ, он появится в этом окне.';
const RECAP_NOTE='Пересказ пишет нейросеть (Claude) по вашей хронике, сведениям и раздаткам, поэтому он может ошибаться. Для этого их текст отправляется в Anthropic.';

/* Сессии из хроники: по подписи сессии, в порядке первой даты. */
function recapSessions(past){
  const groups=[],seen=new Map();
  for(const p of [...(past||[])].sort((a,b)=>a.from<b.from?-1:a.from>b.from?1:0)){
    const k=(p.session||'').trim();if(!k)continue;
    if(!seen.has(k)){const g={label:k,from:p.from};seen.set(k,g);groups.push(g);}
  }
  return groups;
}
/* Что можно пересказать: последняя сессия, две последних, всё за неделю. since не позже сегодняшнего дня. */
function recapPresets(past,today,addDaysFn){
  const g=recapSessions(past),out=[];
  if(g.length)out.push({id:'last',label:`Последнюю сессию (${g[g.length-1].label})`,since:g[g.length-1].from});
  if(g.length>1)out.push({id:'two',label:`Две последние сессии (с «${g[g.length-2].label}»)`,since:g[g.length-2].from});
  out.push({id:'week',label:'Всё за последнюю неделю игры',since:addDaysFn(today,-7)});
  return out.map(p=>({...p,since:p.since>today?today:p.since}));
}

/* Что сейчас с просьбой игрока: подпись и «тон» для цвета. fmt превращает дату в текст (в браузере fFull). */
function recapRequestLine(r,fmt){
  const when=(fmt||(x=>x))(r.since);
  if(r.status==='done')return {tone:'ok',text:`пересказ готов, с ${when}`};
  if(r.status==='declined')return {tone:'no',text:`мастер пока не может, с ${when}`+(r.text?`: ${r.text}`:'')};
  return {tone:'wait',text:`ждёт мастера, с ${when}`};
}
/* Подпись на кнопке «Что было раньше»: ответ готов, ждёт мастера или ничего. Только в режиме «через мастера». */
function recapButtonLabel(st){
  if(!st||st.recap_mode!=='gm')return 'Что было раньше';
  if(st.recap_ready>0)return 'Что было раньше (ответ готов)';
  if(st.recap_open>0)return 'Что было раньше (ждёт мастера)';
  return 'Что было раньше';
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={RECAP_NOTE,RECAP_NOTE_GM,recapSessions,recapPresets,recapRequestLine,recapButtonLabel};
}

/* ----- окно (только в браузере) ----- */
const recapManual=()=>!!S&&S.recap_mode==='gm';
function openRecap(){
  if(V==='gm'||RO()||!S.recap)return;
  const presets=recapPresets(S.past,S.now.date,addDays),days=range(CAL_START,S.now.date);
  curKey=null;UI.recapText='';
  showPanel(`<p class="kind">Что было раньше</p><h2>${esc(CN[V]||'')}</h2>
  <p class="note">Короткий пересказ того, что вы пропустили, только по тому, что известно вашему персонажу.</p>
  <form id="recap-form" novalidate>
    <fieldset class="vis"><legend>Что пересказать</legend>${presets.map((p,i)=>`<label><input type="radio" name="since" value="${esc(p.since)}" ${i===0?'checked':''}> ${esc(p.label)}</label>`).join('')}
      <label><input type="radio" name="since" value="custom"> Начиная с даты</label></fieldset>
    <label class="field" id="recap-date-box" hidden>С какой даты<select name="date">${days.map(d=>`<option value="${d}" ${d===(presets[0]||{}).since?'selected':''}>${esc(fFull(d))}</option>`).join('')}</select></label>
    <p class="muted small">${recapManual()?RECAP_NOTE_GM:RECAP_NOTE}</p>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">${recapManual()?'Попросить пересказ':'Пересказать'}</button><button type="button" class="btn" data-act="close">Закрыть</button></div>
  </form>${recapManual()?'<div id="recap-mine"></div>':''}`);
  document.getElementById('recap-form').addEventListener('change',ev=>{
    if(ev.target.name==='since')document.getElementById('recap-date-box').hidden=ev.target.value!=='custom';
    document.getElementById('form-err').textContent='';
  });
  if(recapManual())loadRecapMine();
}
/* Просьбы игрока и ответы мастера (режим «через мастера»). Открыв список, игрок видит все ответы, метка «ответ готов» гаснет. */
function recapMineHTML(){
  const list=UI.recapMine||[];
  if(!list.length)return '';
  return `<h3 class="recap-h">Ваши просьбы</h3>`+list.map(r=>{const l=recapRequestLine(r,fFull);
    return `<div class="recap-req ${l.tone}"><span>${esc(CN[r.char]||'')}: ${esc(l.text)}</span>${r.status==='done'?`<button type="button" class="btn small" data-act="recap-show" data-id="${r.id}">Открыть</button>`:''}</div>`;}).join('');
}
async function loadRecapMine(){
  const j=await getJson('/api/me/recap/requests');
  if(!j)return;
  UI.recapMine=j.items;
  const box=document.getElementById('recap-mine');
  if(box)box.innerHTML=recapMineHTML();
  if(S.recap_ready){S.recap_ready=0;render(true);}
}
function showRecapText(j){
  UI.recapText=j.text;
  showPanel(`<p class="kind">Что было раньше</p><h2>${esc(CN[V]||'')}</h2><p class="note">С ${esc(fFull(j.since))}${j.cached?' · ранее сделанный пересказ':''}</p>
    <div class="recap-text">${esc(j.text)}</div><p class="muted small">${recapManual()?RECAP_NOTE_GM:RECAP_NOTE}</p>
    <div class="dl-acts"><button type="button" class="btn primary" data-act="recap-copy">Скопировать</button><button type="button" class="btn" data-act="open-recap">Другой период</button><button type="button" class="btn" data-act="close">Закрыть</button></div>`);
}
async function submitRecap(form){
  const err=m=>{document.getElementById('form-err').textContent=m;};
  const pick=form.querySelector('input[name="since"]:checked').value,since=pick==='custom'?form.elements.namedItem('date').value:pick;
  const btn=form.querySelector('button[type="submit"]'),label=btn.textContent;btn.disabled=true;btn.textContent=recapManual()?'Отправляю просьбу…':'Пишу пересказ…';
  try{
    const j=await apiPost('/api/me/recap',{since},err);
    if(!j)return;
    if(j.pending){
      UI.recapMine=null;
      showPanel(`<p class="kind">Что было раньше</p><h2>${esc(CN[V]||'')}</h2><p class="note">С ${esc(fFull(j.since))}</p>
      <p>Просьба отправлена мастеру. Когда он вставит пересказ, вы увидите его здесь: откройте «Что было раньше» ещё раз.</p>
      <div class="dl-acts"><button type="button" class="btn primary" data-act="close">Понятно</button></div>`);
      return;
    }
    showRecapText(j);
  }finally{if(document.body.contains(btn)){btn.disabled=false;btn.textContent=label;}}
}
function showRecapMine(id){
  const r=(UI.recapMine||[]).find(x=>String(x.id)===String(id));
  if(r&&r.status==='done')showRecapText({text:r.text,since:r.since,cached:false});
}
async function copyRecap(b){
  try{await navigator.clipboard.writeText(UI.recapText||'');toast('Пересказ скопирован');}
  catch(e){const r=document.createRange();const n=document.querySelector('.recap-text');if(n){r.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(r);toast('Выделено: нажмите «Копировать» в меню');}}
  if(b)b.blur();
}

/* ----- очередь просьб у мастера (режим «через мастера») ----- */
function recapQueueItem(r){
  const draft=(UI.recapDrafts||{})[r.id]||'';
  return `<div class="recap-q" data-id="${r.id}">
    <div class="hist-top"><b>${esc(r.name)}</b> просит пересказ с ${esc(fFull(r.since))} <span class="muted small">событий в хронике: ${r.events}; ${fTs(r.created)}</span></div>
    <div class="acts"><button type="button" class="btn small primary" data-act="recap-copy-prompt" data-id="${r.id}">Скопировать запрос для Claude</button></div>
    <details class="recap-prompt"><summary>Показать запрос</summary><pre>${esc(r.prompt)}</pre></details>
    <label class="field"><span>Ответ Claude</span><textarea class="recap-answer" data-id="${r.id}" rows="6" maxlength="6000" placeholder="Вставьте сюда пересказ, который написал Claude">${esc(draft)}</textarea></label>
    <div class="acts"><button type="button" class="btn small primary" data-act="recap-send" data-id="${r.id}">Отправить игроку</button>
    <input class="recap-note" data-id="${r.id}" maxlength="300" aria-label="Причина отказа" placeholder="Причина (по желанию)"><button type="button" class="btn small plain" data-act="recap-decline" data-id="${r.id}">Отказать</button></div>
  </div>`;
}
function recapQueueInner(){
  if(!S.recap_open)return '<p class="muted">Просьб нет.</p>';
  const q=UI.recapQueue;
  if(q==null)return '<p class="muted">Загружаю…</p>';
  return q.length?q.map(recapQueueItem).join(''):'<p class="muted">Просьб нет.</p>';
}
function recapGmHTML(){
  if(!S||S.recap_mode!=='gm')return '';
  return `<section id="gm-recap"><div class="sec-head"><h2>Просьбы о пересказе${S.recap_open?` (${S.recap_open})`:''}</h2></div>
  <p class="note">Игрок нажал «Что было раньше». Скопируйте запрос, вставьте его в свой чат с Claude, а ответ Claude вставьте ниже и отправьте игроку. В запросе только то, что игрок и так видит на портале: ваших заметок и скрытого там нет. Прочитайте пересказ перед отправкой, нейросеть может ошибиться.</p>
  <div id="recap-queue">${recapQueueInner()}</div></section>`;
}
/* Пока мастер вставляет ответ, страница может перерисоваться (кто-то что-то изменил): текст и место курсора сохраняются. */
function recapFocus(){
  const a=document.activeElement;
  return a&&a.classList&&a.classList.contains('recap-answer')?{id:a.dataset.id,pos:a.selectionStart}:null;
}
function recapRefocus(f){
  if(!f)return;
  const n=document.querySelector(`.recap-answer[data-id="${f.id}"]`);
  if(n){n.focus();try{n.setSelectionRange(f.pos,f.pos);}catch(e){}}
}
function patchRecapQueue(){
  const box=document.getElementById('recap-queue');
  if(!box)return;
  const f=recapFocus();
  box.innerHTML=recapQueueInner();
  recapRefocus(f);
}
if(typeof document!=='undefined'){
  document.addEventListener('input',ev=>{
    const t=ev.target;
    if(t.classList&&t.classList.contains('recap-answer')){UI.recapDrafts=UI.recapDrafts||{};UI.recapDrafts[t.dataset.id]=t.value;}
  });
}
async function copyRecapPrompt(b){
  const r=(UI.recapQueue||[]).find(x=>String(x.id)===b.dataset.id);
  if(!r)return;
  try{await navigator.clipboard.writeText(r.prompt);toast('Запрос скопирован: вставьте его в чат с Claude');}
  catch(e){
    const d=b.closest('.recap-q').querySelector('details'),pre=d&&d.querySelector('pre');
    if(pre){d.open=true;const rg=document.createRange();rg.selectNodeContents(pre);const s=getSelection();s.removeAllRanges();s.addRange(rg);}
    toast('Запрос выделен: скопируйте его вручную');
  }
  b.blur();
}
async function recapGmAct(a,b){
  if(a==='recap-copy-prompt'){copyRecapPrompt(b);return;}
  const id=b.dataset.id,box=b.closest('.recap-q');
  const j=a==='recap-send'?await apiPost(`/api/gm/recap/${id}/answer`,{text:box.querySelector('.recap-answer').value},null,true)
    :await apiPost(`/api/gm/recap/${id}/decline`,{note:box.querySelector('.recap-note').value},null,true);
  if(!j)return;
  if(UI.recapDrafts)delete UI.recapDrafts[id];
  UI.recapQueue=(UI.recapQueue||[]).filter(x=>String(x.id)!==String(id));
  UI.extrasVer=-1;render(true);if(j.msg)toast(j.msg);gmLoadExtras(true);
}
