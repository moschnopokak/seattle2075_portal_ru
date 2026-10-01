/* ===== «Что было раньше»: пересказ для того, кто пропустил сессию =====
   Пересказ пишет Claude на сервере и только по тому, что видит сам игрок (хроника, сведения, раздатки, его сыгранные записи).
   Здесь выбор периода и показ результата. Выбор периода (чистые функции) проверяют автотесты в Node. */
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

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={RECAP_NOTE,recapSessions,recapPresets};
}

/* ----- окно (только в браузере) ----- */
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
    <p class="muted small">${RECAP_NOTE}</p>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Пересказать</button><button type="button" class="btn" data-act="close">Закрыть</button></div>
  </form>`);
  document.getElementById('recap-form').addEventListener('change',ev=>{
    if(ev.target.name==='since')document.getElementById('recap-date-box').hidden=ev.target.value!=='custom';
    document.getElementById('form-err').textContent='';
  });
}
async function submitRecap(form){
  const err=m=>{document.getElementById('form-err').textContent=m;};
  const pick=form.querySelector('input[name="since"]:checked').value,since=pick==='custom'?form.elements.namedItem('date').value:pick;
  const btn=form.querySelector('button[type="submit"]');btn.disabled=true;btn.textContent='Пишу пересказ…';
  try{
    const j=await apiPost('/api/me/recap',{since},err);
    if(!j)return;
    UI.recapText=j.text;
    showPanel(`<p class="kind">Что было раньше</p><h2>${esc(CN[V]||'')}</h2><p class="note">С ${esc(fFull(j.since))}${j.cached?' · ранее сделанный пересказ':''}</p>
    <div class="recap-text">${esc(j.text)}</div><p class="muted small">${RECAP_NOTE}</p>
    <div class="dl-acts"><button type="button" class="btn primary" data-act="recap-copy">Скопировать</button><button type="button" class="btn" data-act="open-recap">Другой период</button><button type="button" class="btn" data-act="close">Закрыть</button></div>`);
  }finally{if(document.body.contains(btn)){btn.disabled=false;btn.textContent='Пересказать';}}
}
async function copyRecap(b){
  try{await navigator.clipboard.writeText(UI.recapText||'');toast('Пересказ скопирован');}
  catch(e){const r=document.createRange();const n=document.querySelector('.recap-text');if(n){r.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(r);toast('Выделено: нажмите «Копировать» в меню');}}
  if(b)b.blur();
}
