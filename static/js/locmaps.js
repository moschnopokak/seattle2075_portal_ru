/* ===== Карты локаций =====
   План места (Роща, здание, база): рисунок для игроков и отдельный рисунок мастера, на них метки, лента «Что изменилось» и пометки группы.
   Рисунки приходят с портала как картинки (SVG показывается как <img>, поэтому код внутри не выполняется); метки и пометки рисуются поверх.
   Всё, что пришло с портала (названия, заметки), выводится через esc(). Чистые функции проверяют автотесты в Node. */
const LM_KINDS={area:'Сектор',thing:'Находка',danger:'Угроза',creature:'Существо',place:'Место',note:'Пометка'};
const LM_STATUS={'':'без отметки',scouted:'разведано',cleared:'расчищено',danger:'опасно',found:'найдено',lost:'потеряно'};
const LM_VIS={'мастер':'скрыта от игроков','стол':'видна всем игрокам','знают':'видна выбранным игрокам'};
let LM={id:null,data:null,role:'player',map:null,group:null,mode:'',moveId:null,tab:'marks',ver:-1,as:'',view:null,seq:0};

/* --- чистые функции --- */
const lmLabel=o=>String(o.key||o.name||'?').slice(0,5);
const lmStatusText=s=>LM_STATUS[s]||LM_STATUS[''];
/* Метка на подписи: «О1», состояние и видимость в классах для цвета. */
const lmPinClass=(o,gm)=>`lm-pin lm-k-${LM_KINDS[o.kind]?o.kind:'place'}${o.status?' lm-s-'+o.status:''}${gm&&o.vis==='мастер'?' lm-hid':''}`;
/* Положение: на рисунке роли или нет. at: {player:[x,y], gm:[x,y]} */
const lmAt=(o,role)=>o.at&&Array.isArray(o.at[role])?o.at[role]:null;
/* Карты, которые видит тот, чьими глазами смотрит мастер (в предпросмотре). Игроку портал уже отдал только его карты. */
function lmMapsFor(maps,preview,chars){
  if(!preview)return maps||[];
  return (maps||[]).filter(m=>m.vis==='стол'||(m.vis==='знают'&&(m.known||[]).some(c=>(chars||[]).includes(c))));
}
/* Метки и лента глазами игрока (предпросмотр мастера): без скрытого, без заметок мастера, без положения на рисунке мастера. */
function lmPlayerView(data,chars,horizon){
  const sees=x=>x.vis==='стол'||(x.vis==='знают'&&(x.known||[]).some(c=>(chars||[]).includes(c)));
  return Object.assign({},data,{
    objects:(data.objects||[]).filter(sees).map(o=>({id:o.id,key:o.key,name:o.name,kind:o.kind,status:o.status,note:o.note,at:o.at&&o.at.player?{player:o.at.player}:{}})),
    feed:(data.feed||[]).filter(f=>(!f.vis||sees(f))&&!(horizon&&f.date>horizon)).map(f=>({id:f.id,ts:f.ts,date:f.date,obj:f.obj,text:f.text})),
    dw:data.dw&&data.dw.player?{player:data.dw.player}:{},gm_note:undefined,vis:undefined,known:undefined});
}
/* Высота окна карты: по форме рисунка, но не выше доли экрана и не ниже минимума. */
function lmHeight(width,size,vw,vh){
  const top=Math.min(vh*(vw<=760?.62:.68),660);
  return Math.round(Math.max(260,Math.min(top,width*size.h/size.w+16)));
}
/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={LM_KINDS,LM_STATUS,lmLabel,lmStatusText,lmPinClass,lmAt,lmMapsFor,lmPlayerView,lmHeight};
}

/* --- состояние раздела --- */
const lmPreview=()=>!!(S&&S.me.gm&&V!=='gm');
const lmGM=()=>V==='gm'&&!!S.me.gm;
const lmList=()=>lmMapsFor(S.locmaps,lmPreview(),viewChars());
const lmCur=()=>(S.locmaps||[]).find(m=>m.id===LM.id)||{};
/* Рисунок мастера открывается, только если он загружен; иначе показывается рисунок игроков, и выбор не застревает. */
const lmRole=()=>lmGM()&&LM.role==='gm'&&!!(lmCur().dw&&lmCur().dw.gm)?'gm':'player';
const lmLL=(x,y)=>L.latLng(-y,x);
function lmDispose(){if(LM.map){try{LM.map.remove();}catch(e){}LM.map=null;LM.group=null;}}

/* --- страница раздела --- */
function lmBarHTML(list){
  const gm=lmGM(),cur=list.find(m=>m.id===LM.id)||{},hasGm=!!(cur.dw&&cur.dw.gm);
  return `<div class="lm-bar">
    ${list.length>1?`<label class="lm-pick"><span class="sr-only">Карта</span><select id="lm-select">${list.map(m=>`<option value="${esc(m.id)}" ${m.id===LM.id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label>`:`<h2 class="lm-title">${esc(cur.name||'')}</h2>`}
    ${gm&&hasGm?`<div class="seg" role="group" aria-label="Какой рисунок"><button type="button" data-act="lm-role" data-v="player" aria-pressed="${lmRole()==='player'}">Рисунок игроков</button><button type="button" data-act="lm-role" data-v="gm" aria-pressed="${lmRole()==='gm'}">Карта мастера</button></div>`:''}
    ${gm?`<div class="lm-gmbtn"><button type="button" class="btn small" data-act="lm-map-edit" data-id="${esc(cur.id||'')}">Править карту</button><button type="button" class="btn small" data-act="lm-files">Рисунки</button><button type="button" class="btn small" data-act="lm-import">Метки из JSON</button><button type="button" class="btn small" data-act="lm-map-new">Добавить карту</button></div>`:''}
  </div>`;
}
function rMaps(){
  const list=lmList();
  if(!list.length){
    return `<div class="lm"><p class="muted">Карт локаций пока нет.</p>${lmGM()?'<div class="acts"><button type="button" class="btn primary" data-act="lm-map-new">Добавить карту</button></div>':''}</div>`;
  }
  if(!LM.id||!list.some(m=>m.id===LM.id))LM.id=list[0].id;
  const cur=list.find(m=>m.id===LM.id);
  const tools=lmGM()
    ?`<button type="button" class="btn" data-act="lm-mode" data-v="mark" aria-pressed="${LM.mode==='mark'}">Поставить метку</button>`
    :(!lmPreview()?`<button type="button" class="btn" data-act="lm-mode" data-v="pin" aria-pressed="${LM.mode==='pin'}">Добавить пометку</button>`:'');
  return `<div class="lm">${lmBarHTML(list)}
    ${list.length>1?`<h2 class="lm-title">${esc(cur.name)}</h2>`:''}${cur.note?`<p class="note lm-note-text">${esc(cur.note)}</p>`:''}
    <div id="lm-map" class="lm-map${LM.mode?' lm-adding':''}" role="application" aria-label="Карта: ${esc(cur.name)}"></div>
    <div class="lm-tools">${tools}${LM.mode?`<span class="muted small">${LM.mode==='move'?'Щёлкните по карте: сюда встанет метка.':'Щёлкните по карте в нужной точке.'}</span><button type="button" class="btn small plain" data-act="lm-mode" data-v="">Отмена</button>`:''}</div>
    <div class="seg lm-tabs" role="group" aria-label="Что показать">
      <button type="button" data-act="lm-tab" data-v="marks" aria-pressed="${LM.tab==='marks'}">Метки</button>
      <button type="button" data-act="lm-tab" data-v="feed" aria-pressed="${LM.tab==='feed'}">Что изменилось</button>
      <button type="button" data-act="lm-tab" data-v="pins" aria-pressed="${LM.tab==='pins'}">Пометки группы</button></div>
    <div id="lm-tab">${lmTabHTML()}</div></div>`;
}
function lmTabHTML(){
  const d=LM.data;
  if(!d||d.id!==LM.id||LM.as!==V)return '<p class="muted">Загружаю…</p>';
  return LM.tab==='feed'?lmFeedHTML(d):LM.tab==='pins'?lmPinsHTML(d):lmMarksHTML(d);
}
function lmMarksHTML(d){
  const gm=lmGM();
  if(!d.objects.length)return `<p class="muted">${gm?'Меток пока нет. Нажмите «Поставить метку» и щёлкните по карте или загрузите метки из JSON.':'Открытых меток пока нет.'}</p>`;
  return d.objects.map(o=>`<button type="button" class="lm-row" data-act="lm-obj" data-id="${esc(o.id)}"><span class="${lmPinClass(o,gm)} lm-chip"><span>${esc(lmLabel(o))}</span></span>
    <span class="lm-rname"><b>${esc(o.name)}</b> <span class="muted small">${esc(LM_KINDS[o.kind]||'')}${o.status?', '+esc(lmStatusText(o.status)):''}${gm?', '+esc(LM_VIS[o.vis]||''):''}${gm&&!lmAt(o,lmRole())?', не на этом рисунке':''}</span></span></button>`).join('');
}
function lmFeedHTML(d){
  const gm=lmGM();
  const form=gm?`<form class="lm-form lm-feedform" data-lm="feed" novalidate><label class="field"><span class="sr-only">Объявление</span><input name="text" maxlength="300" placeholder="Что изменилось на карте"></label>
    <div class="lm-line"><select name="vis" aria-label="Кому видно"><option value="стол">Всем игрокам</option><option value="знают">Выбранным</option></select>
    <label><input type="checkbox" name="notify"> написать игрокам в Telegram</label><button type="submit" class="btn small primary">Добавить</button></div>
    <div class="lm-chars" hidden>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${esc(c.id)}"> ${esc(c.name)}</label>`).join('')}</div><p class="err" role="alert"></p></form>`:'';
  const rows=d.feed.length?d.feed.map(f=>`<div class="lm-feed"><span class="muted small">${f.date?esc(fFull(f.date)):''}</span> ${esc(f.text)}${gm?` <span class="muted small">(${f.vis==='знают'?'выбранным':'всем'})</span> <button type="button" class="btn small plain" data-act="lm-feed-del" data-id="${f.id}">Убрать</button>`:''}</div>`).join('')
    :'<p class="muted">Пока ничего не менялось.</p>';
  return form+rows;
}
function lmPinsHTML(d){
  const me=!lmGM()&&!lmPreview();
  if(!d.pins.length)return `<p class="muted">Пометок пока нет.${me?' Нажмите «Добавить пометку» над картой и щёлкните по рисунку.':''}</p>`;
  return d.pins.map(p=>`<div class="lm-feed"><b>${esc(CN[p.char]||'')}</b>: ${esc(p.text)} ${(lmGM()||(me&&S.me.chars.includes(p.char)))?`<button type="button" class="btn small plain" data-act="lm-pin-del" data-id="${p.id}">Убрать</button>`:''}</div>`).join('');
}

/* --- карта --- */
async function lmMount(){
  const el=document.getElementById('lm-map');
  if(LM.map){try{LM.view={c:LM.map.getCenter(),z:LM.map.getZoom(),id:LM.id,role:lmRole()};}catch(e){}lmDispose();}
  if(!el)return;
  const seq=++LM.seq;
  try{await ensureLeaflet();}catch(e){el.innerHTML='<p class="err" style="padding:16px">Не удалось загрузить карту. Обновите страницу.</p>';return;}
  if(seq!==LM.seq||!document.body.contains(el))return;
  if(!LM.data||LM.data.id!==LM.id||LM.ver!==S.version||LM.as!==V)await lmLoad(seq);
  if(seq!==LM.seq||!document.body.contains(document.getElementById('lm-map')))return;
  lmDraw();
}
async function lmLoad(seq){
  const id=LM.id,j=await getJson('/api/locmaps/'+encodeURIComponent(id));
  if(seq!==undefined&&seq!==LM.seq)return;
  if(!j){LM.data=null;const t=document.getElementById('lm-tab');if(t)t.innerHTML='<p class="err">Не удалось загрузить карту.</p>';return;}
  LM.data=lmPreview()?lmPlayerView(j,viewChars(),hzPreview()):j;
  LM.ver=S.version;LM.as=V;                                                   // данные собраны для этого взгляда: при смене «Вида» загружаются заново
  const t=document.getElementById('lm-tab');if(t)t.innerHTML=lmTabHTML();
}
function lmDraw(){
  const el=document.getElementById('lm-map'),d=LM.data;
  if(!el||!d||d.id!==LM.id||!window.L)return;
  lmDispose();
  const role=lmRole(),size=d.dw&&d.dw[role];
  if(!size){el.innerHTML=`<p class="muted lm-empty">${role==='gm'?'Рисунок мастера не загружен.':lmGM()?'Рисунок игроков не загружен: нажмите «Рисунки».':'У этой карты пока нет рисунка.'}</p>`;return;}
  el.innerHTML='';
  el.style.height=lmHeight(el.clientWidth,size,window.innerWidth,window.innerHeight)+'px';   // высота по форме рисунка: на телефоне не остаётся пустого поля
  const map=L.map(el,{crs:L.CRS.Simple,minZoom:-4,maxZoom:3,zoomSnap:.25,zoomDelta:.5,wheelPxPerZoomLevel:90,attributionControl:false,maxBoundsViscosity:.8});
  const b=L.latLngBounds(lmLL(0,size.h),lmLL(size.w,0));
  L.imageOverlay(`/locmap/${encodeURIComponent(d.id)}/${role}.svg?v=${size.v}`,b,{interactive:false}).addTo(map);
  map.setMaxBounds(b.pad(.25));
  map.fitBounds(b);
  map.setMinZoom(Math.min(map.getZoom()-1,-.5));
  const v=LM.view;
  if(v&&v.id===LM.id&&v.role===role)map.setView(v.c,v.z,{animate:false});
  LM.map=map;LM.group=L.layerGroup().addTo(map);
  lmMarkers();
  map.on('click',lmMapClick);
}
function lmMarkers(){
  if(!LM.group||!LM.data)return;
  LM.group.clearLayers();
  const role=lmRole(),gm=lmGM();
  for(const o of LM.data.objects){
    const at=lmAt(o,role);if(!at)continue;
    const m=L.marker(lmLL(at[0],at[1]),{title:o.name,keyboard:true,riseOnHover:true,icon:L.divIcon({className:lmPinClass(o,gm),html:`<span>${esc(lmLabel(o))}</span>`,iconSize:[0,0]})});
    m.on('click',e=>{L.DomEvent.stopPropagation(e);lmObject(o.id);});
    LM.group.addLayer(m);
  }
  if(role==='player')for(const p of LM.data.pins){
    const m=L.marker(lmLL(p.x,p.y),{title:p.text,icon:L.divIcon({className:'lm-note',html:`<span>${esc(p.text)}</span>`,iconSize:[0,0]})});
    m.on('click',e=>{L.DomEvent.stopPropagation(e);lmPinCard(p.id);});
    LM.group.addLayer(m);
  }
}
async function lmMapClick(e){
  if(!LM.mode||!LM.data)return;
  const d=LM.data,role=lmRole(),size=d.dw[role];
  const x=Math.round(e.latlng.lng),y=Math.round(-e.latlng.lat);
  if(!size||x<0||y<0||x>size.w||y>size.h)return;
  const mode=LM.mode,o=mode==='move'?lmFind(LM.moveId):null;
  LM.mode='';LM.moveId=null;render(true);
  if(mode==='mark')lmObjectForm(null,{role,x,y});
  else if(mode==='pin')lmPinForm(x,y);
  else if(mode==='move'&&o){
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,{id:o.id,at:Object.assign({},o.at,{[role]:[x,y]}),announce:false});   // положение на другом рисунке остаётся
    if(j)lmRefresh(j.msg);
  }
}

/* --- карточка метки --- */
function lmFind(id){return LM.data&&LM.data.objects.find(o=>o.id===id);}
function lmObject(id){
  const o=lmFind(id);if(!o)return;
  curKey=null;
  const gm=lmGM();
  let h=`<p class="kind">${esc(LM_KINDS[o.kind]||'Метка')}${o.key?' · '+esc(o.key):''}</p><h2>${esc(o.name)}</h2>
    <p class="lm-state">${esc(lmStatusText(o.status))}${gm?` · ${esc(LM_VIS[o.vis]||'')}${o.vis==='знают'?': '+esc(joinNames((o.known||[]).map(c=>CN[c]||c))):''}`:''}</p>
    ${o.note?`<p class="lm-notebody">${esc(o.note)}</p>`:'<p class="muted">Описания пока нет.</p>'}`;
  if(gm){
    h+=o.gm_note?`<h3 class="lm-h">Заметка мастера</h3><p class="lm-notebody">${esc(o.gm_note)}</p>`:'';
    h+=`<div class="seg lm-quick" role="group" aria-label="Состояние">${Object.entries(LM_STATUS).filter(([k])=>k).map(([k,t])=>`<button type="button" data-act="lm-status" data-id="${esc(o.id)}" data-v="${k}" aria-pressed="${o.status===k}">${t}</button>`).join('')}<button type="button" data-act="lm-status" data-id="${esc(o.id)}" data-v="" aria-pressed="${!o.status}">без отметки</button></div>
      <div class="dl-acts"><button type="button" class="btn primary" data-act="lm-obj-edit" data-id="${esc(o.id)}">Править</button>
      <button type="button" class="btn" data-act="lm-move" data-id="${esc(o.id)}">${lmAt(o,lmRole())?'Переставить':'Поставить на этом рисунке'}</button>
      <button type="button" class="btn" data-act="lm-obj-show" data-id="${esc(o.id)}">${o.vis==='мастер'?'Показать игрокам':'Скрыть от игроков'}</button>
      <button type="button" class="btn plain" data-act="lm-obj-del" data-id="${esc(o.id)}">Удалить</button></div>`;
  }else h+='<div class="dl-acts"><button type="button" class="btn" data-act="close">Закрыть</button></div>';
  showPanel(h);
}
function lmObjectForm(id,pos){
  if(!lmGM())return;
  const o=id?lmFind(id):null;
  const v=x=>esc(x||''),kind=o?o.kind:'place',vis=o?o.vis:'мастер';
  const at=(role)=>pos&&pos.role===role?[pos.x,pos.y]:(o&&lmAt(o,role))||null;
  const roleName={player:'рисунке игроков',gm:'карте мастера'};
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>${o?'Метка':'Новая метка'}</h2>
  <form class="lm-form" data-lm="obj" data-id="${v(o&&o.id)}" novalidate>
    <label class="field">Название<input name="name" maxlength="80" value="${v(o&&o.name)}"></label>
    <div class="lm-line"><label class="field">Подпись на карте<input name="key" maxlength="20" value="${v(o&&o.key)}" placeholder="О1"></label>
    <label class="field">Что это<select name="kind">${Object.entries(LM_KINDS).map(([k,t])=>`<option value="${k}" ${k===kind?'selected':''}>${t}</option>`).join('')}</select></label>
    <label class="field">Состояние<select name="status">${Object.entries(LM_STATUS).map(([k,t])=>`<option value="${k}" ${o&&o.status===k?'selected':''}>${t}</option>`).join('')}</select></label></div>
    <fieldset class="vis"><legend>Кто видит метку</legend>${Object.entries(LM_VIS).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${k===vis?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <div class="lm-chars" ${vis==='знают'?'':'hidden'}>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${esc(c.id)}" ${o&&(o.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</div>
    <label class="field">Что видят игроки<textarea name="note" rows="3" maxlength="1000">${v(o&&o.note)}</textarea></label>
    <label class="field">Заметка мастера<textarea name="gm_note" rows="3" maxlength="2000">${v(o&&o.gm_note)}</textarea><span class="sub">Игроки её не видят.</span></label>
    <p class="muted small">Положение: ${['player','gm'].map(r=>at(r)?`на ${roleName[r]} (${at(r)[0]}, ${at(r)[1]})`:`не стоит на ${roleName[r]}`).join('; ')}. Переставить метку можно в её карточке кнопкой «Переставить».</p>
    <input type="hidden" name="at_player" value="${at('player')?at('player').join(','):''}"><input type="hidden" name="at_gm" value="${at('gm')?at('gm').join(','):''}">
    <label class="lm-ck"><input type="checkbox" name="announce" checked> записать в ленту, если метка открыта игрокам или изменила состояние</label>
    <label class="lm-ck"><input type="checkbox" name="notify"> написать об этом игрокам в Telegram</label>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Сохранить</button><button type="button" class="btn" data-act="close">Отмена</button></div>
  </form>`);
}
function lmMapForm(id){
  if(!lmGM())return;
  const m=id?(S.locmaps||[]).find(x=>x.id===id):null,v=x=>esc(x||'');
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>${m?'Править карту':'Новая карта'}</h2>
  <form class="lm-form" data-lm="map" data-id="${v(m&&m.id)}" novalidate>
    <label class="field">Название<input name="name" maxlength="80" value="${v(m&&m.name)}"></label>
    <label class="field">Описание для игроков<textarea name="note" rows="3" maxlength="2000">${v(m&&m.note)}</textarea></label>
    <label class="field">Заметка мастера<textarea name="gm_note" rows="3" maxlength="4000">${v(m&&m.gm_note)}</textarea></label>
    <fieldset class="vis"><legend>Кто видит карту</legend>${Object.entries({'мастер':'только мастер','стол':'все игроки','знают':'выбранные игроки'}).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${(m?m.vis:'мастер')===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <div class="lm-chars" ${m&&m.vis==='знают'?'':'hidden'}>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${esc(c.id)}" ${m&&(m.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</div>
    <label class="field">Место на городской карте<select name="place"><option value="">не привязана</option>${(S.places||[]).map(p=>`<option value="${esc(p.id)}" ${m&&m.place===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><span class="sub">У места появится кнопка «Открыть карту места».</span></label>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Сохранить</button>${m?`<button type="button" class="btn plain" data-act="lm-map-del" data-id="${esc(m.id)}">Удалить карту</button>`:''}<button type="button" class="btn" data-act="close">Отмена</button></div>
  </form>`);
}
function lmFilesPanel(){
  if(!lmGM())return;
  const cur=(S.locmaps||[]).find(m=>m.id===LM.id);if(!cur)return;
  const row=(role,name)=>{const s=cur.dw&&cur.dw[role];return `<div class="lm-file"><b>${name}</b> <span class="muted small">${s?`загружен, ${s.w}×${s.h}`:'не загружен'}</span>
    <label class="btn small">Выбрать файл SVG<input type="file" accept=".svg,image/svg+xml" data-lm-file="${role}" hidden></label>${s?`<button type="button" class="btn small plain" data-act="lm-file-del" data-v="${role}">Убрать</button>`:''}</div>`;};
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>Рисунки</h2><p class="note">Рисунок игроков видят те, кому открыта карта. Рисунок мастера видите только вы. Файл очищается при загрузке: скрипты, внешние ссылки и встроенные картинки убираются.</p>
    ${row('player','Рисунок игроков')}${row('gm','Карта мастера')}<div class="dl-acts"><button type="button" class="btn" data-act="close">Готово</button></div>`);
}
function lmImportPanel(){
  if(!lmGM())return;
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>Метки из JSON</h2><p class="note">Вставьте список меток: <code>{"objects":[{"key":"О1","name":"Ворота","kind":"area","note":"…","gm_note":"…","at":{"player":[470,95],"gm":[420,205]}}]}</code>. Метка с такой же подписью обновляется (видимость и состояние не меняются), новые метки скрыты от игроков.</p>
    <form class="lm-form" data-lm="import" novalidate><label class="field"><span class="sr-only">JSON</span><textarea name="json" rows="10" maxlength="400000" placeholder='{"objects":[...]}'></textarea></label><p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Загрузить</button><button type="button" class="btn" data-act="close">Закрыть</button></div></form>`);
}
function lmPinForm(x,y){
  curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>Пометка группы</h2><p class="note">Короткая заметка на карте. Её увидят все игроки и мастер.</p>
    <form class="lm-form" data-lm="pin" data-x="${x}" data-y="${y}" novalidate><label class="field"><span class="sr-only">Пометка</span><input name="text" maxlength="120" placeholder="Например: тропы врут"></label><p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Добавить</button><button type="button" class="btn" data-act="close">Отмена</button></div></form>`);
}
function lmPinCard(id){
  const p=LM.data&&LM.data.pins.find(x=>x.id===id);if(!p)return;
  const mine=lmGM()||(!lmPreview()&&S.me.chars.includes(p.char));
  curKey=null;
  showPanel(`<p class="kind">Пометка группы</p><h2>${esc(CN[p.char]||'')}</h2><p class="lm-notebody">${esc(p.text)}</p><div class="dl-acts">${mine?`<button type="button" class="btn plain" data-act="lm-pin-del" data-id="${p.id}">Убрать пометку</button>`:''}<button type="button" class="btn" data-act="close">Закрыть</button></div>`);
}

/* --- действия --- */
function lmRefresh(msg){
  LM.ver=-1;render(true);if(msg)toast(msg);
}
async function lmPost(path,body,err){
  const j=await apiPost(path,body,err||null,true);
  return j;
}
async function lmAct(a,b){
  const id=b.dataset.id,v=b.dataset.v;
  if(a==='lm-open'){closePanel();LM.id=id;LM.data=null;LM.view=null;LM.mode='';UI.section='maps';render();window.scrollTo(0,0);return;}
  if(a==='lm-tab'){LM.tab=v;const t=document.getElementById('lm-tab');if(t)t.innerHTML=lmTabHTML();document.querySelectorAll('.lm-tabs [data-act]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.v===LM.tab)));return;}
  if(a==='lm-role'){LM.role=v;LM.view=null;render(true);return;}
  if(a==='lm-mode'){LM.mode=LM.mode===v?'':v;LM.moveId=null;render(true);return;}
  if(a==='lm-move'){closePanel();LM.mode='move';LM.moveId=id;render(true);return;}
  if(a==='lm-obj'){lmObject(id);return;}
  if(a==='lm-obj-edit'){lmObjectForm(id);return;}
  if(a==='lm-map-new'){lmMapForm(null);return;}
  if(a==='lm-map-edit'){lmMapForm(id);return;}
  if(a==='lm-files'){lmFilesPanel();return;}
  if(a==='lm-import'){lmImportPanel();return;}
  if(a==='lm-status'){const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,{id,status:v});if(j){closePanel();lmRefresh(j.msg);}return;}
  if(a==='lm-obj-show'){const o=lmFind(id);if(!o)return;const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,{id,vis:o.vis==='мастер'?'стол':'мастер',known:[]});if(j){closePanel();lmRefresh(j.msg);}return;}
  if(a==='lm-obj-del'||a==='lm-map-del'||a==='lm-file-del'||a==='lm-feed-del'||a==='lm-pin-del'){
    if(!b.dataset.armed){b.dataset.armed='1';b.dataset.label=b.textContent;b.textContent='Нажмите ещё раз, чтобы удалить';setTimeout(()=>{if(document.body.contains(b)&&b.dataset.armed){delete b.dataset.armed;b.textContent=b.dataset.label;}},4000);return;}
    const path={'lm-obj-del':`/api/gm/locmaps/${LM.id}/objects/${id}/delete`,'lm-map-del':`/api/gm/items/locmaps/${id}/delete`,'lm-file-del':`/api/gm/locmaps/${LM.id}/drawing/${v}/delete`,
      'lm-feed-del':`/api/gm/locmaps/${LM.id}/feed/${id}/delete`,'lm-pin-del':`/api/locmaps/${LM.id}/pins/${id}/delete`}[a];
    const j=await lmPost(path,{});
    if(j){if(a==='lm-map-del')LM.id=null;if(a==='lm-file-del'){lmRefresh(j.msg);lmFilesPanel();return;}closePanel();lmRefresh(j.msg);}
  }
}
const lmChecked=(f,name)=>[...f.querySelectorAll(`input[name="${name}"]:checked`)].map(x=>x.value);
const lmPoint=s=>{const p=String(s||'').split(',').map(Number);return p.length===2&&p.every(Number.isFinite)?p:null;};
async function lmSubmit(f){
  const err=m=>{const n=f.querySelector('.err')||document.getElementById('form-err');if(n)n.textContent=m;};
  const kind=f.dataset.lm,val=n=>(f.elements.namedItem(n)||{}).value||'';
  if(kind==='obj'){
    const body={name:val('name'),key:val('key'),kind:val('kind'),status:val('status'),vis:lmChecked(f,'vis')[0]||'мастер',known:lmChecked(f,'known'),note:val('note'),gm_note:val('gm_note'),
      at:{},announce:f.elements.namedItem('announce').checked,notify:f.elements.namedItem('notify').checked};
    if(lmPoint(val('at_player')))body.at.player=lmPoint(val('at_player'));
    if(lmPoint(val('at_gm')))body.at.gm=lmPoint(val('at_gm'));
    if(f.dataset.id)body.id=f.dataset.id;
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/objects`,body,err);
    if(j){closePanel();lmRefresh(j.msg);}
  }else if(kind==='map'){
    const body={name:val('name'),note:val('note'),gm_note:val('gm_note'),vis:lmChecked(f,'vis')[0]||'мастер',known:lmChecked(f,'known'),place:val('place')};
    if(f.dataset.id)body.id=f.dataset.id;
    const before=new Set((S.locmaps||[]).map(m=>m.id));
    const j=await lmPost('/api/gm/items/locmaps',body,err);
    if(j){const fresh=(S.locmaps||[]).find(m=>!before.has(m.id));if(fresh)LM.id=fresh.id;closePanel();lmRefresh(j.msg);}
  }else if(kind==='feed'){
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/feed`,{text:val('text'),vis:val('vis'),known:lmChecked(f,'known'),notify:f.elements.namedItem('notify').checked},err);
    if(j)lmRefresh(j.msg);
  }else if(kind==='pin'){
    const j=await apiPost(`/api/locmaps/${LM.id}/pins`,{text:val('text'),x:+f.dataset.x,y:+f.dataset.y},err);
    if(j){closePanel();LM.tab='pins';lmRefresh(j.msg);}
  }else if(kind==='import'){
    let data;try{data=JSON.parse(val('json'));}catch(e){err('Это не JSON: проверьте скобки и кавычки.');return;}
    const items=Array.isArray(data)?data:data&&data.objects;
    const j=await lmPost(`/api/gm/locmaps/${LM.id}/import`,{objects:items},err);
    if(j){
      const r=j.report,bad=r.items.filter(i=>i.status==='error');
      lmRefresh();
      showPanel(`<p class="kind">Карта</p><h2>Метки загружены</h2><p><b>Добавлено: ${r.add}. Обновлено: ${r.update}. Без изменений: ${r.skip}.${r.error?' Не прошло проверку: '+r.error+'.':''}</b></p>
        ${bad.map(i=>`<div class="lm-feed"><b>${esc(i.title)}</b>: ${esc(i.msg)}</div>`).join('')}<div class="dl-acts"><button type="button" class="btn primary" data-act="close">Готово</button></div>`);
    }
  }
}
/* Загрузка рисунка: тело запроса это сам файл. */
async function lmUpload(role,file){
  if(!file)return;
  try{
    const r=await fetch(`/api/gm/locmaps/${encodeURIComponent(LM.id)}/drawing/${role}`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'image/svg+xml',...authHeaders()},body:await file.arrayBuffer()});
    let j=null;try{j=await r.json();}catch(e){}
    if(r.status===401){showLogin();return;}
    if(!r.ok){toast(errText(j));return;}
    applyState(j.state);LM.view=null;lmRefresh(j.msg);lmFilesPanel();
  }catch(e){toast('Нет связи с порталом. Проверьте интернет и попробуйте ещё раз.');}
}
if(typeof document!=='undefined'){
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&LM.mode&&UI.section==='maps'&&!overlayOpen()){LM.mode='';LM.moveId=null;render(true);}});
  document.addEventListener('change',ev=>{
    const t=ev.target;
    if(t.id==='lm-select'){LM.id=t.value;LM.data=null;LM.view=null;LM.mode='';render(true);return;}
    if(t.dataset&&t.dataset.lmFile){lmUpload(t.dataset.lmFile,t.files&&t.files[0]);return;}
    const form=t.closest&&t.closest('.lm-form');
    if(form&&t.name==='vis'){const box=form.querySelector('.lm-chars');if(box)box.hidden=t.value!=='знают';}
    if(form&&form.dataset.lm==='feed'&&t.name==='vis'){const box=form.querySelector('.lm-chars');if(box)box.hidden=t.value!=='знают';}
  });
}
