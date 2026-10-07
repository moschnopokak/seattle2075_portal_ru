/* ===== Загрузка разбора арки (только мастер) =====
   Ответ чата с разбором арки вставляется целиком: здесь из него вынимаются данные (json), а проверка, отчёт и запись идут на портале.
   Сначала «Проверить»: портал показывает, что добавится, что уже есть и что не пройдёт проверку, и ничего не пишет. Потом «Добавить».
   Чистые функции (поиск данных в тексте, строки отчёта) проверяют автотесты в Node. */
const ARC_KEYS=['windows','plan','clocks','rhythm','entries','past','dossier','places','handouts'];
const ARC_LABELS=[['windows','Этапы'],['plan','План мастера'],['clocks','Скрытые таймеры'],['rhythm','Регулярные события'],['entries','Записи календаря'],['past','Хроника'],['dossier','Досье'],['places','Места'],['handouts','Раздатки']];
const ARC_STATUS={add:'добавится',skip:'уже есть',error:'не пройдёт'};
const ARC_STATUS_DONE={add:'добавлено',skip:'уже было',error:'не добавлено'};

function arcParse(s){
  try{const d=JSON.parse(s);return d&&typeof d==='object'&&!Array.isArray(d)?d:null;}catch(e){return null;}
}
const arcLooksRight=d=>!!d&&ARC_KEYS.some(k=>Array.isArray(d[k]));
/* Данные разбора из вставленного текста: чистый JSON, блок кода в ответе чата или первый объект {…} посреди текста. */
function arcExtract(text){
  const src=String(text||'').trim();
  if(!src)return {error:'Вставьте ответ чата с разбором арки.'};
  const tries=[src];
  for(const m of src.matchAll(/```[a-zA-Z]*\s*([\s\S]*?)```/g))tries.push(m[1]);
  const a=src.indexOf('{'),b=src.lastIndexOf('}');
  if(a>=0&&b>a)tries.push(src.slice(a,b+1));
  for(const t of tries){const d=arcParse(t.trim());if(arcLooksRight(d))return {data:d};}
  return {error:/```|\{/.test(src)
    ?'Нашёл в тексте данные, но прочитать их не получилось. Скопируйте ответ чата целиком, вместе с блоком json: в нём не должно быть пропущенных кавычек и запятых.'
    :'Не нашёл в тексте блок json. Вставьте ответ чата целиком.'};
}
/* Одна строка итога: «Добавится: 11. Уже есть: 2. Не пройдёт проверку: 1.» (done: время прошедшее) */
function arcSummaryLine(rep,done){
  const parts=[`${done?'Добавлено':'Добавится'}: ${rep.add}`];
  if(rep.skip)parts.push(`${done?'Уже было':'Уже есть'}: ${rep.skip}`);
  if(rep.error)parts.push(`${done?'Не добавлено':'Не пройдёт проверку'}: ${rep.error}`);
  return parts.join('. ')+'.';
}
/* Сколько чего добавится по разделам: «План мастера 2, Досье 1». */
function arcBreakdown(rep){
  return ARC_LABELS.filter(([k])=>rep.counts[k]&&rep.counts[k].add).map(([k,l])=>`${l} ${rep.counts[k].add}`).join(', ');
}
function arcReportHTML(rep,done,msg){
  const st=done?ARC_STATUS_DONE:ARC_STATUS;
  const groups=ARC_LABELS.map(([k,label])=>{
    const items=rep.items.filter(i=>i.kind===k);
    if(!items.length)return '';
    return `<h3 class="arc-h">${esc(label)}</h3>`+items.map(i=>`<div class="arc-row ${i.status}"><span class="arc-st">${st[i.status]}</span><b>${esc(i.title)}</b>${i.msg?`<span class="muted small">${esc(i.msg)}</span>`:''}</div>`).join('');
  }).join('');
  const qs=rep.questions&&rep.questions.length?`<h3 class="arc-h">Вопросы из разбора</h3><ol class="arc-q">${rep.questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ol>`:'';
  const acts=done
    ?`<div class="dl-acts"><button type="button" class="btn primary" data-act="close">Готово</button></div>`
    :`<div class="dl-acts">${rep.add?`<button type="button" class="btn primary" data-act="arc-go">Добавить: ${rep.add}</button>`:'<button type="button" class="btn primary" disabled>Добавлять нечего</button>'}<button type="button" class="btn" data-act="arc-back">Другой текст</button><button type="button" class="btn" data-act="close">Закрыть</button></div>`;
  const note=done
    ?'Игрокам ничего не отправлено. Места стоят рядом с центром района: перетащите их кнопкой «Переместить» в карточке места.'
    :'Пока ничего не записано. Что не пройдёт проверку, добавлено не будет, остальное добавится. Игрокам при загрузке ничего не отправляется.';
  return `<p class="kind">Панель мастера</p><h2>${done?'Разбор арки загружен':'Загрузить разбор арки'}</h2>
  <p><b>${esc(msg||arcSummaryLine(rep,done))}</b>${arcBreakdown(rep)?`<br><span class="muted small">${esc(arcBreakdown(rep))}</span>`:''}</p><p class="note">${note}</p>${groups}${qs}${acts}`;
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={ARC_KEYS,arcExtract,arcSummaryLine,arcBreakdown,arcReportHTML};
}

/* ----- окно (только в браузере) ----- */
let ARC=null;
function arcSectionHTML(){
  return `<section id="gm-arc"><div class="sec-head"><h2>Загрузить разбор арки</h2><button type="button" class="btn" data-act="arc-open">Вставить разбор</button></div>
  <p class="note">События арки, подготовленные в другом чате по промпту (файл ПРОМПТ_РАЗБОР_АРОК.md в проекте): план, таймеры, записи календаря, досье, места и раздатки добавляются разом. Сначала портал покажет, что добавится. Уже существующее он не дублирует и не меняет.</p></section>`;
}
function openArcImport(err){
  if(V!=='gm')return;
  curKey=null;
  showPanel(`<p class="kind">Панель мастера</p><h2>Загрузить разбор арки</h2>
  <p class="note">Вставьте ответ чата с разбором арки целиком. Портал сам найдёт в нём данные и покажет, что добавится. Пока вы не нажмёте «Добавить», ничего не записывается.</p>
  <label class="field"><span class="sr-only">Ответ чата с разбором арки</span><textarea id="arc-text" rows="12" maxlength="400000" placeholder="Вставьте сюда ответ чата">${esc(UI.arcText||'')}</textarea></label>
  <p class="err" id="arc-err" role="alert">${esc(err||'')}</p>
  <div class="dl-acts"><button type="button" class="btn primary" data-act="arc-check">Проверить</button><button type="button" class="btn" data-act="close">Закрыть</button></div>`);
}
async function arcCheck(){
  const ta=document.getElementById('arc-text');
  if(!ta)return;
  UI.arcText=ta.value;
  const err=m=>{const n=document.getElementById('arc-err');if(n)n.textContent=m;};
  const x=arcExtract(ta.value);
  if(x.error){err(x.error);return;}
  const j=await apiPost('/api/gm/arc/preview',{data:x.data},err,true);
  if(!j)return;
  ARC={data:x.data};
  showPanel(arcReportHTML(j.report,false));
}
async function arcGo(){
  if(!ARC||!ARC.data)return;
  const j=await apiPost('/api/gm/arc/import',{data:ARC.data},null,true);
  if(!j)return;
  ARC=null;UI.arcText='';
  render(true);toast(j.msg);
  showPanel(arcReportHTML(j.report,true,j.msg));
}
