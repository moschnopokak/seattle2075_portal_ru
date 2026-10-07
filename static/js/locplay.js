/* ===== Карты локаций: то, что помогает на игре =====
   Сроки, фишка группы «Мы здесь», прогресс, журнал с отменой, вопросы мастеру, счётчик мастера, связи с досье и раздатками,
   значок «новое» и картинка карты с отметками. Всё, что пришло с портала, выводится через esc(). Чистые функции проверяют автотесты в Node. */
const LM_FILL={cleared:'#4B7A36',danger:'#A3453A',scouted:'#33629F',found:'#D08A22',lost:'#56646D'};          // цвета состояний на картинке карты
const LM_PIN_KINDS={note:'Заметка',danger:'Опасность',find:'Находка',question:'Вопрос мастеру'};
const LM_PIN_GLYPH={note:'',danger:'⚠ ',find:'◆ ',question:'? '};                                           // знак перед текстом пометки: цвет не единственный признак
const LM_SAME_WORDS=['этой','эта','сама','self'];

/* --- чистые функции --- */
/* Прогресс по зонам рисунка: сколько расчищено, сколько опасных. Зона это метка с контуром на этом рисунке. */
function lmProgress(objects,role){
  const zones=(objects||[]).filter(o=>lmShape(o,role));
  return {total:zones.length,cleared:zones.filter(o=>o.status==='cleared').length,danger:zones.filter(o=>o.status==='danger').length,scouted:zones.filter(o=>o.status==='scouted').length};
}
/* Точка внутри контура (луч вправо). */
function lmInside(pt,poly){
  let c=false;
  for(let i=0,j=poly.length-1;i<poly.length;j=i++){
    const [xi,yi]=poly[i],[xj,yj]=poly[j];
    if((yi>pt[1])!==(yj>pt[1])&&pt[0]<(xj-xi)*(pt[1]-yi)/(yj-yi)+xi)c=!c;
  }
  return c;
}
const lmArea=poly=>Math.abs(poly.reduce((t,p,i)=>{const q=poly[(i+1)%poly.length];return t+p[0]*q[1]-q[0]*p[1];},0))/2;
/* В какой зоне стоит точка. Если контуры вложены, берётся самый маленький. */
function lmZoneAt(objects,role,pt){
  let best=null,ba=Infinity;
  for(const o of objects||[]){
    const sh=lmShape(o,role);
    if(sh&&lmInside(pt,sh)){const a=lmArea(sh);if(a<ba){ba=a;best=o;}}
  }
  return best;
}
/* Разница дат ГГГГ-ММ-ДД в днях. */
const lmDays=(from,to)=>Math.round((Date.UTC(+to.slice(0,4),+to.slice(5,7)-1,+to.slice(8,10))-Date.UTC(+from.slice(0,4),+from.slice(5,7)-1,+from.slice(8,10)))/864e5);
/* Сколько осталось до срока словами. */
function lmDueText(date,today){
  const n=lmDays(today,date);
  if(n===0)return 'сегодня';
  return n>0?`через ${n} ${plural(n,'день','дня','дней')}`:`${-n} ${plural(-n,'день','дня','дней')} назад`;
}
/* Сколько записей ленты новее той, что человек видел последней. */
const lmNewCount=(fresh,seenId)=>(fresh||[]).filter(id=>id>(seenId||0)).length;
/* Правила расчистки как текст («этой −2; Сердце −1») и обратно. */
const lmSigned=n=>(n<0?'−':'+')+Math.abs(n);
const lmFxText=fx=>(fx||[]).map(e=>`${e.to==='self'?'этой':e.to} ${lmSigned(e.delta)}`).join('; ');
function lmParseFx(text){
  const fx=[];
  for(const part of String(text||'').split(/[;\n]/).map(x=>x.trim()).filter(Boolean)){
    const m=/^(.+?)\s*([+\-−–]?\s*\d+)$/.exec(part);
    if(!m)return {fx:[],error:`Не понял «${part}». Пишите название зоны и число, например: этой −2; Сердце −1.`};
    const delta=Number(m[2].replace(/[−–]/g,'-').replace(/\s/g,'')),to=m[1].trim();
    fx.push({to:LM_SAME_WORDS.includes(to.toLowerCase())?'self':to,delta});
  }
  return {fx,error:''};
}
/* Последствия срока словами (для мастера). */
function lmEffectsText(d,objName){
  const p=[];
  if(d.status)p.push(`состояние «${LM_STATUS[d.status]}»`);
  if(d.reveal)p.push('открыть метку игрокам');
  if(d.delta)p.push(`счётчик ${lmSigned(d.delta)} ${d.obj?'у зоны':'везде'}`);
  return p.length?(objName?`«${objName}»: `:'')+p.join(', '):'без последствий';
}
/* Значок «новое»: игроку число свежих записей по всем картам, мастеру наступившие сроки и неотвеченные вопросы. */
function lmBadgeCount(maps,seen,gm){
  return (maps||[]).reduce((t,m)=>t+(gm?(m.due||0)+(m.open_q||0):lmNewCount(m.fresh,(seen||{})[m.id])),0);
}
/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={LM_FILL,LM_PIN_KINDS,LM_PIN_GLYPH,lmProgress,lmInside,lmArea,lmZoneAt,lmDays,lmDueText,lmNewCount,lmSigned,lmFxText,lmParseFx,lmEffectsText,lmBadgeCount};
}

/* --- значок «новое» --- */
const lmSeenKey=()=>'seattle2075-seen-maps:'+(S&&S.me?S.me.name:'')+':'+(V||'');
function lmSeen(){try{return JSON.parse(localStorage.getItem(lmSeenKey())||'{}')||{};}catch(e){return {};}}
function lmMarkSeen(mapId){
  const m=(S.locmaps||[]).find(x=>x.id===mapId);
  if(!m||!m.fresh||!m.fresh.length||S.me.gm)return;
  const top=Math.max(...m.fresh),seen=lmSeen();
  if((seen[mapId]||0)>=top)return;
  seen[mapId]=top;
  try{localStorage.setItem(lmSeenKey(),JSON.stringify(seen));}catch(e){}
  renderTop();
}
const lmBadge=()=>S?lmBadgeCount(lmList(),lmSeen(),V==='gm'&&S.me.gm):0;

/* --- строка над картой: прогресс и где группа --- */
function lmInfoHTML(d){
  if(!d||d.id!==LM.id||LM.as!==V)return '';
  const role=lmRole(),pr=lmProgress(d.objects,role),out=[];
  if(pr.total>=2){
    out.push(`<span class="lm-prog-line"><progress class="lm-prog" max="${pr.total}" value="${pr.cleared}" aria-label="Расчищено ${pr.cleared} из ${pr.total}"></progress> <b>Расчищено ${pr.cleared} из ${pr.total}</b>${pr.danger||pr.scouted?`<span class="muted">${pr.danger?` опасно ${pr.danger}`:''}${pr.danger&&pr.scouted?' ·':''}${pr.scouted?` разведано ${pr.scouted}`:''}</span>`:''}</span>`);
  }
  if(d.party){
    const z=lmZoneAt(d.objects,'player',[d.party.x,d.party.y]),by=d.party.by==='gm'?'мастер':CN[d.party.by]||'';
    out.push(`<span class="lm-party-line">Группа: <b>${z?esc(z.name):'на карте'}</b>${by?`, отметил ${esc(by)}`:''}${d.party.date?`, ${esc(fFull(d.party.date))}`:''}</span>`);
  }
  return out.join('');
}
function lmInfoRefresh(){const n=document.getElementById('lm-info');if(n)n.innerHTML=lmInfoHTML(LM.data);}
/* Фишка группы видна на рисунке игроков, а на рисунке мастера только если рисунки одного размера (положение одно и то же). */
const lmSameSize=d=>!!(d.dw&&d.dw.player&&d.dw.gm&&d.dw.player.w===d.dw.gm.w&&d.dw.player.h===d.dw.gm.h);
const lmPartyShown=d=>!!(d.party&&(lmRole()==='player'||lmSameSize(d)));
function lmPartyLayer(){
  const d=LM.data;
  if(!LM.group||!d||!lmPartyShown(d))return;
  LM.group.addLayer(L.marker(lmLL(d.party.x,d.party.y),{interactive:false,keyboard:false,zIndexOffset:900,icon:L.divIcon({className:'lm-party',html:'<span>Мы здесь</span>',iconSize:[0,0]})}));
}
/* Кнопки «Мы здесь» и «Убрать отметку»: игрокам и мастеру, но не в предпросмотре и не на рисунке мастера другого размера. */
function lmPartyTools(){
  const d=LM.data;
  if(lmPreview()||!d||d.id!==LM.id||(lmRole()==='gm'&&!lmSameSize(d)))return '';
  return `<button type="button" class="btn" data-act="lm-mode" data-v="party" aria-pressed="${LM.mode==='party'}">Мы здесь</button>${d.party?'<button type="button" class="btn small plain" data-act="lm-party-clear">Убрать отметку</button>':''}`;
}
async function lmPartyPlace(x,y){
  const j=await apiPost(`/api/locmaps/${encodeURIComponent(LM.id)}/party`,{x,y},null,true);
  if(j)lmRefresh(j.msg);
}

/* --- сроки --- */
function lmDeadlinesHTML(d){
  const gm=lmGM(),today=S.now.date,names=Object.fromEntries(d.objects.map(o=>[o.id,o.name]));
  const list=d.deadlines.slice().sort((a,b)=>a.done-b.done||(a.done?(a.date<b.date?1:-1):(a.date<b.date?-1:1)));
  const add=gm?'<div class="acts lm-dlbar"><button type="button" class="btn small" data-act="lm-dl-new">Добавить срок</button></div>':'';
  if(!list.length)return add+`<p class="muted">${gm?'Сроков пока нет. Добавьте то, что наступит в игровой день: смену патруля, цветение, полнолуние.':'Сроков пока нет.'}</p>`;
  return add+list.map(x=>{
    const late=!x.done&&x.date<=today;
    return `<div class="lm-dl${x.done?' lm-done':''}${late&&gm?' lm-late':''}"><div><span class="muted small">${esc(fFull(x.date))}</span> <b>${esc(x.title)}</b>
      <span class="muted small">${x.done?(gm?'выполнен'+(x.done_date?', '+esc(fFull(x.done_date)):''):'наступил'):esc(lmDueText(x.date,today))}${x.obj&&names[x.obj]?', '+esc(names[x.obj]):''}${gm?', '+esc(LM_VIS[x.vis]||'').replace('скрыта','скрыт').replace('видна','виден'):''}</span></div>
      ${gm?`<div class="muted small">${esc(lmEffectsText(x,''))}${x.note?`. Заметка: ${esc(x.note)}`:''}</div><div class="lm-dlacts">${x.done?'':`<button type="button" class="btn small primary" data-act="lm-dl-apply" data-id="${esc(x.id)}">Применить</button><button type="button" class="btn small" data-act="lm-dl-skip" data-id="${esc(x.id)}">Отметить выполненным</button>`}<button type="button" class="btn small" data-act="lm-dl-edit" data-id="${esc(x.id)}">Править</button><button type="button" class="btn small plain" data-act="lm-dl-del" data-id="${esc(x.id)}">Убрать</button></div>`:''}</div>`;
  }).join('');
}
function lmDeadlineForm(id){
  if(!lmGM()||!LM.data)return;
  const x=id?LM.data.deadlines.find(d=>d.id===id):null,v=t=>esc(t||''),vis=x?x.vis:'мастер';
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>${x?'Срок':'Новый срок'}</h2>
  <form class="lm-form" data-lm="deadline" data-id="${v(x&&x.id)}" novalidate>
    <label class="field">Что наступит<input name="title" maxlength="120" value="${v(x&&x.title)}" placeholder="Например: Тедди Мур становится статуей"></label>
    <label class="field">День в игре<input type="date" name="date" min="${esc(S.calStart)}" max="${esc(S.calEnd)}" value="${v(x?x.date:S.now.date)}"></label>
    <label class="field">К какой метке относится<select name="obj"><option value="">ни к какой</option>${LM.data.objects.map(o=>`<option value="${esc(o.id)}" ${x&&x.obj===o.id?'selected':''}>${esc((o.key?o.key+' ':'')+o.name)}</option>`).join('')}</select></label>
    <fieldset class="vis"><legend>Кто видит срок</legend>${Object.entries({'мастер':'только мастер','стол':'все игроки','знают':'выбранные игроки'}).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${k===vis?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <div class="lm-chars" ${vis==='знают'?'':'hidden'}>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${esc(c.id)}" ${x&&(x.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</div>
    <p class="muted small">Когда срок наступит, портал напомнит вам. Последствия вы применяете кнопкой «Применить»:</p>
    <div class="lm-line"><label class="field">Состояние метки<select name="status"><option value="">не менять</option>${Object.entries(LM_STATUS).filter(([k])=>k).map(([k,t])=>`<option value="${k}" ${x&&x.status===k?'selected':''}>${t}</option>`).join('')}</select></label>
    <label class="field">Счётчик на<input type="number" name="delta" min="-99" max="99" value="${x&&x.delta?x.delta:''}" placeholder="например, +1"></label></div>
    <label class="lm-ck"><input type="checkbox" name="reveal" ${x&&x.reveal?'checked':''}> открыть метку игрокам</label>
    <label class="field">Заметка мастера<textarea name="note" rows="3" maxlength="1000">${v(x&&x.note)}</textarea></label>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Сохранить</button><button type="button" class="btn" data-act="close">Отмена</button></div>
  </form>`);
}

/* --- журнал и отмена (мастеру) --- */
function lmLogHTML(d){
  if(!d.log||!d.log.length)return '<p class="muted">Журнал пока пуст. Здесь видно, кто и что менял на карте, и можно вернуть прежнее состояние.</p>';
  return d.log.map(r=>`<div class="lm-feed${r.undone?' lm-done':''}"><span class="muted small">${esc(fTs(r.ts))}</span> ${esc(r.text)}${r.undone?' <span class="muted small">(отменено)</span>':''}${r.undoable?` <button type="button" class="btn small" data-act="lm-undo" data-id="${r.id}">Вернуть прежнее</button>`:''}</div>`).join('');
}

/* --- пометки группы: тип и ответ мастера --- */
function lmPinKindRadios(){
  return `<fieldset class="vis"><legend>Что это</legend>${Object.entries(LM_PIN_KINDS).map(([k,t],i)=>`<label><input type="radio" name="kind" value="${k}" ${i===0?'checked':''}> ${t}</label>`).join('')}</fieldset>`;
}
function lmAnswerForm(id){
  const p=LM.data&&LM.data.pins.find(x=>x.id===id);if(!p||!lmGM())return;
  curKey=null;
  showPanel(`<p class="kind">Вопрос мастеру</p><h2>${esc(CN[p.char]||'')}</h2><p class="lm-notebody">${esc(p.text)}</p>
    <form class="lm-form" data-lm="answer" data-id="${p.id}" novalidate><label class="field">Ответ<textarea name="text" rows="4" maxlength="300">${esc(p.answer||'')}</textarea><span class="sub">Ответ увидят все игроки, у которых открыта карта, и он запишется в ленту.</span></label>
    <label class="lm-ck"><input type="checkbox" name="notify"> написать игрокам в Telegram</label><p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Ответить</button><button type="button" class="btn" data-act="close">Отмена</button></div></form>`);
}

/* --- счётчик мастера --- */
function lmCounterHTML(o){
  if(!lmGM())return '';
  const name=lmCur().counter||'Счётчик';
  return `<div class="lm-counter"><span class="muted small">${esc(name)}:</span> <button type="button" class="btn small" data-act="lm-count" data-id="${esc(o.id)}" data-d="-1" aria-label="Уменьшить">−</button>
    <b class="lm-cval">${o.count===null||o.count===undefined?'не задан':o.count}</b><button type="button" class="btn small" data-act="lm-count" data-id="${esc(o.id)}" data-d="1" aria-label="Увеличить">+</button>
    ${(o.fx||[]).length?`<span class="muted small">при расчистке: ${esc(lmFxText(o.fx))}</span>`:''}</div>`;
}
function lmBumpTools(){
  const c=lmCur().counter;
  return lmGM()&&c?`<span class="lm-bump"><span class="muted small">${esc(c)} везде:</span><button type="button" class="btn small" data-act="lm-bump" data-v="-1">−1</button><button type="button" class="btn small" data-act="lm-bump" data-v="1">+1</button></span>`:'';
}

/* --- связи с досье и раздатками --- */
function lmLinkedItems(o){
  const dossier=dossierVisible(),handouts=handoutsVisible(),out=[];
  for(const l of o.links||[]){
    if(l.kind==='dossier'){const c=dossier.find(x=>x.id===l.id);if(c)out.push({key:'n:'+c.id,title:c.name,sub:'досье'});}
    else if(l.kind==='handouts'){const h=handouts.find(x=>x.id===l.id);if(h)out.push({key:'h:'+h.id,title:h.title,sub:'раздатка'});}
  }
  return out;
}
function lmLinksHTML(o){
  const items=lmLinkedItems(o);
  return items.length?`<h3 class="lm-h">Связано</h3>`+items.map(i=>`<button type="button" class="row" data-open="${esc(i.key)}"><span class="rt">${esc(i.title)}</span><span class="rs">${i.sub}</span></button>`).join(''):'';
}
function lmLinksPanel(id){
  const o=lmFind(id);if(!o||!lmGM())return;
  const has=(k,i)=>(o.links||[]).some(l=>l.kind===k&&l.id===i);
  const row=(k,i,t,s)=>`<div class="lm-file"><span><b>${esc(t)}</b> <span class="muted small">${s}</span></span><button type="button" class="btn small ${has(k,i)?'primary':''}" data-act="lm-link" data-id="${esc(o.id)}" data-kind="${k}" data-ref="${esc(i)}" aria-pressed="${has(k,i)}">${has(k,i)?'Связана':'Связать'}</button></div>`;
  curKey=null;
  showPanel(`<p class="kind">Связи метки</p><h2>${esc(o.name)}</h2><p class="note">Связанные карточки появятся в карточке метки; игрок увидит только те, что открыты ему на портале.</p>
    <h3>Досье</h3>${(S.dossier||[]).map(c=>row('dossier',c.id,c.name,c.role||'')).join('')||'<p class="muted">Карточек пока нет.</p>'}
    <h3>Раздатки</h3>${(S.handouts||[]).map(h=>row('handouts',h.id,h.title,h.date?fDate(h.date):'')).join('')||'<p class="muted">Раздаток пока нет.</p>'}
    <div class="dl-acts"><button type="button" class="btn" data-act="lm-obj" data-id="${esc(o.id)}">Назад к метке</button></div>`);
}
/* Записи календаря, привязанные к месту, с которым связана карта. */
function lmEntriesHTML(){
  const cur=lmCur();if(!cur.place)return '';
  const es=(S.entries||[]).filter(e=>e.place===cur.place&&canSee(e)).sort((a,b)=>a.from<b.from?1:-1).slice(0,6);
  return es.length?`<details class="lm-entries"><summary>Записи календаря по этому месту (${es.length})</summary>${es.map(e=>entryRow(e,fFull(e.from))).join('')}</details>`:'';
}

/* --- картинка карты с отметками --- */
function lmRoundRect(ctx,x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
async function lmExport(){
  const d0=LM.data,role=lmRole();
  if(!d0||!d0.dw||!d0.dw[role]){toast('У карты нет рисунка');return;}
  const d=lmGM()&&role==='player'?lmPlayerView(d0,[],''):d0,size=d0.dw[role];       // картинку «для игроков» мастер получает без скрытого
  const img=new Image();img.src=`/locmap/${encodeURIComponent(d0.id)}/${role}.svg?v=${size.v}`;
  try{await img.decode();}catch(e){toast('Не удалось подготовить картинку');return;}
  const foot=64,cv=document.createElement('canvas');cv.width=size.w;cv.height=size.h+foot;
  const ctx=cv.getContext('2d');
  ctx.fillStyle='#ffffff';ctx.fillRect(0,0,cv.width,cv.height);
  ctx.drawImage(img,0,0,size.w,size.h);
  const unit=Math.max(1,size.w/1200);                                              // размеры знаков привязаны к ширине рисунка
  for(const o of d.objects){
    const sh=lmShape(o,role);if(!sh)continue;
    ctx.beginPath();sh.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();
    const col=LM_FILL[o.status];
    if(col){ctx.globalAlpha=.32;ctx.fillStyle=col;ctx.fill();}
    ctx.globalAlpha=col?.9:.45;ctx.lineWidth=(col?3:2)*unit;ctx.strokeStyle=col||'#56646D';if(!col)ctx.setLineDash([8*unit,6*unit]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
  }
  ctx.textAlign='center';ctx.textBaseline='middle';
  for(const o of d.objects){
    const at=lmLabelAt(o,role);if(!at)continue;
    const txt=lmLabel(o),r=15*unit;ctx.font=`600 ${13*unit}px Jost, sans-serif`;
    const w=Math.max(r*2,ctx.measureText(txt).width+12*unit);
    lmRoundRect(ctx,at[0]-w/2,at[1]-r,w,r*2,r);ctx.fillStyle='#ffffff';ctx.fill();ctx.lineWidth=2*unit;ctx.strokeStyle=LM_FILL[o.status]||'#1B252C';ctx.stroke();
    ctx.fillStyle='#1B252C';ctx.fillText(txt,at[0],at[1]+unit);
  }
  for(const p of d.pins||[]){
    ctx.font=`${12*unit}px Jost, sans-serif`;
    const txt=(LM_PIN_GLYPH[p.kind]||'')+(p.text.length>28?p.text.slice(0,27)+'…':p.text),w=ctx.measureText(txt).width+14*unit,h=22*unit;
    lmRoundRect(ctx,p.x-6*unit,p.y-h/2,w,h,4*unit);ctx.fillStyle='#F7E3BC';ctx.fill();ctx.lineWidth=unit;ctx.strokeStyle='#D08A22';ctx.stroke();
    ctx.fillStyle='#1B252C';ctx.textAlign='left';ctx.fillText(txt,p.x+unit,p.y+unit);ctx.textAlign='center';
  }
  if(d.party&&(role==='player'||lmSameSize(d0))){
    ctx.font=`700 ${14*unit}px Jost, sans-serif`;
    const w=ctx.measureText('Мы здесь').width+18*unit,h=26*unit;
    lmRoundRect(ctx,d.party.x-w/2,d.party.y-h/2,w,h,h/2);ctx.fillStyle='#1B252C';ctx.fill();ctx.fillStyle='#ffffff';ctx.fillText('Мы здесь',d.party.x,d.party.y+unit);
  }
  const pr=lmProgress(d.objects,role);
  ctx.fillStyle='#1B252C';ctx.fillRect(0,size.h,cv.width,foot);ctx.fillStyle='#ffffff';ctx.textAlign='left';ctx.textBaseline='middle';
  ctx.font=`600 ${20*unit}px Jost, sans-serif`;ctx.fillText(`${lmCur().name||''}`,16*unit,size.h+foot/2-10*unit);
  ctx.font=`${14*unit}px Jost, sans-serif`;ctx.fillText(`${fFull(S.now.date)} 2075${pr.total>=2?`  ·  Расчищено ${pr.cleared} из ${pr.total}`:''}`,16*unit,size.h+foot/2+14*unit);
  cv.toBlob(blob=>{
    if(!blob){toast('Не удалось подготовить картинку');return;}
    const url=URL.createObjectURL(blob),name=`${(lmCur().name||'карта').replace(/[^\wА-Яа-яЁё -]+/g,'').trim()||'карта'}.png`;
    curKey=null;
    showPanel(`<p class="kind">Карта</p><h2>Картинка карты</h2><p class="note">${lmGM()&&role==='player'?'Как карту видят игроки: без скрытых меток и заметок мастера. ':''}Её можно отправить в Telegram-чат. Если кнопка не скачивает, нажмите на картинку и удерживайте.</p>
      <img class="lm-export" src="${url}" alt="Карта «${esc(lmCur().name||'')}» с отметками"><div class="dl-acts"><a class="btn primary" href="${url}" download="${esc(name)}">Скачать PNG</a><button type="button" class="btn" data-act="close">Закрыть</button></div>`);
  },'image/png');
}

/* --- действия этого модуля: возвращает true, если действие его --- */
async function lmPlayAct(a,b){
  const id=b.dataset.id,v=b.dataset.v;
  const armed=(path,done)=>{
    if(!b.dataset.armed){b.dataset.armed='1';b.dataset.label=b.textContent;b.textContent='Нажмите ещё раз';setTimeout(()=>{if(document.body.contains(b)&&b.dataset.armed){delete b.dataset.armed;b.textContent=b.dataset.label;}},4000);return null;}
    return lmPost(path,{}).then(j=>{if(j){closePanel();lmRefresh(j.msg);}return j;});
  };
  if(a==='lm-dl-new'){lmDeadlineForm(null);return true;}
  if(a==='lm-dl-edit'){lmDeadlineForm(id);return true;}
  if(a==='lm-dl-apply'||a==='lm-dl-skip'){
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/deadlines/${encodeURIComponent(id)}/apply`,{apply:a==='lm-dl-apply'});
    if(j)lmRefresh(j.msg);
    return true;
  }
  if(a==='lm-dl-del'){await armed(`/api/gm/locmaps/${LM.id}/deadlines/${encodeURIComponent(id)}/delete`);return true;}
  if(a==='lm-undo'){const j=await lmPost(`/api/gm/locmaps/${LM.id}/log/${encodeURIComponent(id)}/undo`,{});if(j)lmRefresh(j.msg);return true;}
  if(a==='lm-answer'){lmAnswerForm(+id);return true;}
  if(a==='lm-party-clear'){const j=await apiPost(`/api/locmaps/${encodeURIComponent(LM.id)}/party/clear`,{},null,true);if(j)lmRefresh(j.msg);return true;}
  if(a==='lm-bump'){const j=await lmPost(`/api/gm/locmaps/${LM.id}/counter`,{delta:+v});if(j)lmRefresh(j.msg);return true;}
  if(a==='lm-count'){
    const o=lmFind(id);if(!o)return true;
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,{id,count:(o.count===null||o.count===undefined?0:o.count)+(+b.dataset.d),announce:false});
    if(j){LM.ver=-1;await lmLoad();lmMarkers();lmObject(id);}                        // данные и подписи на карте обновляются, карточка остаётся открытой
    return true;
  }
  if(a==='lm-links'){lmLinksPanel(id);return true;}
  if(a==='lm-link'){
    const o=lmFind(id);if(!o)return true;
    const k=b.dataset.kind,ref=b.dataset.ref,has=(o.links||[]).some(l=>l.kind===k&&l.id===ref);
    const links=has?(o.links||[]).filter(l=>!(l.kind===k&&l.id===ref)):(o.links||[]).concat([{kind:k,id:ref}]);
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,{id,links,announce:false});
    if(j){LM.ver=-1;await lmLoad();lmLinksPanel(id);}
    return true;
  }
  if(a==='lm-export'){lmExport();return true;}
  return false;
}
/* Отправка форм этого модуля. */
async function lmPlaySubmit(f){
  const kind=f.dataset.lm,val=n=>(f.elements.namedItem(n)||{}).value||'';
  const err=m=>{const n=f.querySelector('.err')||document.getElementById('form-err');if(n)n.textContent=m;};
  if(kind==='deadline'){
    const body={title:val('title'),date:val('date'),obj:val('obj'),vis:lmChecked(f,'vis')[0]||'мастер',known:lmChecked(f,'known'),status:val('status'),delta:val('delta')===''?null:+val('delta'),
      reveal:f.elements.namedItem('reveal').checked,note:val('note')};
    if(f.dataset.id)body.id=f.dataset.id;
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/deadlines`,body,err);
    if(j){closePanel();LM.tab='deadlines';lmRefresh(j.msg);}
    return true;
  }
  if(kind==='answer'){
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/pins/${f.dataset.id}/answer`,{text:val('text'),notify:f.elements.namedItem('notify').checked},err);
    if(j){closePanel();LM.tab='pins';lmRefresh(j.msg);}
    return true;
  }
  return false;
}
