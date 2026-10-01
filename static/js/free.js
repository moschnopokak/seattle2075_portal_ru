/* ===== «Кто свободен» при создании записи =====
   Занятость считается только по тому, что видит сам человек: его записи, общие события и привычки. Чужие личные дела не показываются.
   Встречи и дела занимают время (с учётом времени суток), развитие и обещания нет. Приглашение без ответа и запись, которой нужна
   другая дата, дают «возможно занят». Чистые функции вынесены отдельно, их проверяют автотесты в Node. */
const FREE_BUSY_TYPES=['meet','deal'];
const FREE_CLOSED=['done','failed','rejected'];
const FREE_HORIZON=60;          // на сколько дней вперёд искать день, когда свободны все

const rhythmHits=(r,s)=>(!r.from||s>=r.from)&&(!r.to||s<=r.to)&&((r.wd&&r.wd.includes(wdi(s)))||(r.monthDay&&dOf(s)===r.monthDay));
const todClash=(a,b)=>!a||!b||a===b;

/* Что занимает персонажа в этот день и время суток (tod пустое: любое). data: {entries, blocks, rhythm, ignoreId}. */
function busyReasons(c,day,tod,data){
  const out=[];
  for(const e of data.entries||[]){
    if(e.id===data.ignoreId||!FREE_BUSY_TYPES.includes(e.type)||FREE_CLOSED.includes(e.status))continue;
    if(!(e.who||[]).includes(c)&&e.author!==c)continue;
    if(day<e.from||day>(e.to||e.from))continue;
    const ans=(e.answers||{})[c];
    if(ans==='нет'||!todClash(tod,e.tod))continue;
    const wait=ans==='ждёт';
    out.push({kind:'entry',id:e.id,title:e.title,tod:e.tod||'',hard:!wait&&e.status!=='resched',why:wait?'ещё не ответил(а)':e.status==='resched'?'нужна другая дата':''});
  }
  for(const b of data.blocks||[]){
    if(day>=b.from&&day<=b.to&&(!(b.who||[]).length||b.who.includes(c)))out.push({kind:'block',id:b.id,title:b.title,tod:'',hard:true,why:'общее событие'});
  }
  for(const r of data.rhythm||[]){
    if(r.who===c&&rhythmHits(r,day))out.push({kind:'habit',id:r.id,title:r.title,tod:'',hard:false,why:'привычка'});
  }
  return out;
}

/* Сводка по персонажу за период: свободен, возможно занят или занят, и что именно мешает (с днями). */
function busyReport(c,from,to,tod,data){
  const found=new Map();
  for(let d=from;d<=to;d=addDays(d,1)){
    for(const r of busyReasons(c,d,tod,data)){
      const k=r.kind+':'+(r.id||r.title);
      if(!found.has(k))found.set(k,{...r,days:[]});
      found.get(k).days.push(d);
    }
  }
  const reasons=[...found.values()];
  return {char:c,status:reasons.some(r=>r.hard)?'busy':reasons.length?'maybe':'free',reasons};
}

/* Начала периода той же длины, на которые все персонажи свободны (free) или хотя бы не заняты наверняка (maybe). */
function freeStarts(chars,start,length,tod,data,calEnd,limit=5){
  const free=[],maybe=[];
  for(let d=start,i=0;i<FREE_HORIZON&&addDays(d,length-1)<=calEnd&&free.length<limit;d=addDays(d,1),i++){
    const end=addDays(d,length-1);
    const st=chars.map(c=>busyReport(c,d,end,tod,data).status);
    if(st.every(s=>s==='free'))free.push(d);
    else if(!st.includes('busy')&&maybe.length<limit)maybe.push(d);
  }
  return {free,maybe};
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={FREE_BUSY_TYPES,rhythmHits,todClash,busyReasons,busyReport,freeStarts};
}

/* ----- вывод в форме записи (только в браузере) ----- */
const allBlocks=()=>S.me.gm?S.plan.filter(p=>p.cover&&p.cover.title).map(p=>({id:p.id,from:p.from,to:p.to,title:p.cover.title,who:p.cover.who||[]})):(S.blocks||[]);
const freeData=ignoreId=>({entries:visEntries(),blocks:allBlocks(),rhythm:S.rhythm.filter(rhythmVisible),ignoreId});
const todTag=t=>t?', '+esc(t):'';
function freeReasonText(r,span){
  const days=span>1?' ('+r.days.length+' '+plural(r.days.length,'день','дня','дней')+')':'';
  const why=r.why&&r.kind!=='block'?', '+esc(r.why):'';
  if(r.kind==='habit')return 'привычка «'+esc(r.title)+'»'+days;
  if(r.kind==='block')return 'общее событие «'+esc(r.title)+'»'+days;
  return '«'+esc(r.title)+'»'+todTag(r.tod)+why+days;
}
const FREE_WORD={free:'свободен(а)',maybe:'возможно занят(а)',busy:'занят(а)'};
function freeHTML(chars,from,to,tod,data){
  if(!chars.length)return '<p class="muted small">Отметьте участников, чтобы увидеть, кто свободен.</p>';
  if(!from||!to||to<from)return '';
  const span=range(from,to).length;
  const rows=chars.map(c=>busyReport(c,from,to,tod,data));
  let h='<ul class="free-list">'+rows.map(r=>`<li class="free-${r.status}"><b>${esc(CN[r.char]||r.char)}</b> <span class="free-tag">${FREE_WORD[r.status]}</span>${r.reasons.length?'<span class="free-why">'+r.reasons.map(x=>freeReasonText(x,span)).join('; ')+'</span>':''}</li>`).join('')+'</ul>';
  if(rows.every(r=>r.status==='free'))h+='<p class="free-sum">В выбранное время свободны все.</p>';
  else{
    const s=freeStarts(chars,clampDate(S.now.date),span,tod,data,CAL_END);
    const pick=days=>days.map(d=>`<button type="button" class="btn small" data-act="free-pick" data-d="${d}">${esc(fFull(d))}</button>`).join(' ');
    h+=s.free.length?`<p class="free-sum">Ближайшие дни, когда свободны все: ${pick(s.free)}</p>`
      :s.maybe.length?`<p class="free-sum">Дня, когда точно свободны все, в ближайшие ${FREE_HORIZON} дней нет. Никто не занят наверняка: ${pick(s.maybe)}</p>`
      :`<p class="free-sum">В ближайшие ${FREE_HORIZON} дней нет подходящего дня: у кого-то всегда что-то стоит.</p>`;
  }
  return h+'<p class="muted small free-note">По записям, которые видите вы. Личные дела других игроков здесь не показаны.</p>';
}
function freeRefresh(form,ed,me){
  const box=document.getElementById('free-box');if(!box)return;
  const F=n=>form.elements.namedItem(n);
  const who=[...form.querySelectorAll('input[name="who"]:checked')].map(x=>x.value);
  if(me&&!who.includes(me))who.unshift(me);
  box.innerHTML=freeHTML(who,F('from').value,F('to').value,F('tod').value,freeData(ed?ed.id:undefined));
}
function freePick(form,day){
  const F=n=>form.elements.namedItem(n);
  const span=range(F('from').value,F('to').value).length;
  F('from').value=day;
  F('to').value=clampDate(addDays(day,span-1));
  if(F('effect')&&F('effect').value<day)F('effect').value=day;
  form.dispatchEvent(new Event('change',{bubbles:true}));
}
