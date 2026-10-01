/* ===== Ссылки [[Имя]] на карточки досье =====
   В свободном тексте (цель записи, обсуждение, хроника, заметки, сведения) можно написать [[Имя]] или [[Имя|как показать]].
   Ссылка ищет карточку по имени или позывному среди карточек, которые ВИДИТ этот человек. Если такой нет (или она скрыта от него),
   выводится просто имя без ссылки: так по тексту нельзя узнать, что скрытая карточка существует. Мастер видит неработающую
   ссылку выделенной, чтобы заметить опечатку. Разбор и поиск чистые, их проверяют автотесты в Node. */
const LINK_RE=/\[\[([^[\]\n|]{1,60})(?:\|([^[\]\n]{1,60}))?\]\]/g;
const normName=s=>String(s??'').toLowerCase().replace(/ё/g,'е').replace(/\s+/g,' ').trim();

/* Текст по частям: {text} обычный кусок или {name,label} ссылка. */
function linkSegments(text){
  const s=String(text??''),out=[];let last=0;
  for(const m of s.matchAll(LINK_RE)){
    if(m.index>last)out.push({text:s.slice(last,m.index)});
    out.push({name:m[1].trim(),label:(m[2]||'').trim()||m[1].trim()});
    last=m.index+m[0].length;
  }
  if(last<s.length)out.push({text:s.slice(last)});
  return out;
}
/* Карточка по имени, а если такого имени нет, по позывному. */
function findCard(name,cards){
  const n=normName(name);if(!n)return null;
  return cards.find(c=>normName(c.name)===n)||cards.find(c=>c.alias&&normName(c.alias)===n)||null;
}
/* Какие из источников ссылаются на карточку. sources: [{key,title,kind,texts}]. */
function mentionsOf(card,cards,sources){
  return sources.filter(src=>(src.texts||[]).some(t=>linkSegments(t).some(s=>s.name!==undefined&&(findCard(s.name,cards)||{}).id===card.id)));
}
/* Для сообщений бота: [[Имя]] и [[Имя|подпись]] становятся просто именем. */
const stripLinks=text=>linkSegments(text).map(s=>s.text!==undefined?s.text:s.label).join('');

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={LINK_RE,normName,linkSegments,findCard,mentionsOf,stripLinks};
}

/* ----- вывод (только в браузере) ----- */
function rich(text){
  const cards=dossierVisible(),gm=V==='gm';
  return linkSegments(text).map(s=>{
    if(s.text!==undefined)return esc(s.text);
    const c=findCard(s.name,cards);
    if(c)return `<button type="button" class="dlink" data-open="n:${esc(c.id)}">${esc(s.label)}</button>`;
    return gm?`<span class="dlink-missing" title="Карточки с таким именем нет">${esc(s.label)}</span>`:esc(s.label);
  }).join('');
}
function mentionSources(){
  const src=[];
  for(const e of visEntries())src.push({key:'e:'+e.id,cls:'t-'+e.type,title:e.title,kind:'Запись',texts:[e.goal,e.cond,e.where,...(e.chat||[]).map(m=>m.t)]});
  for(const p of S.past)src.push({key:'p:'+p.id,cls:'k-past',title:p.title,kind:'Хроника',texts:[p.note]});
  for(const p of placesVisible())src.push({key:'m:'+p.id,cls:'',title:p.name,kind:'Место',texts:[p.note,...(V==='gm'?[p.gm_note]:[])]});
  if(V==='gm')for(const p of S.plan)src.push({key:'g:'+p.id,cls:'k-plan',title:p.title,kind:'План мастера',texts:[p.note]});
  return src;
}
function mentionsHTML(card){
  const list=mentionsOf(card,dossierVisible(),mentionSources()).slice(0,12);
  if(!list.length)return '';
  return `<h3>Упоминается</h3><div class="mentions">${list.map(m=>row(m.key,m.cls,m.title,m.kind)).join('')}</div>`;
}
