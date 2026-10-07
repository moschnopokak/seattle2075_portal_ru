/* ===== Досье ===== */
const STANCE={unknown:'Неясно',contact:'Контакт',ally:'Союзник',neutral:'Нейтрален',hostile:'Враг'};
const STANCE_CLR={unknown:'var(--sodium-ink)',contact:'var(--meet)',ally:'var(--grow)',neutral:'var(--muted)',hostile:'var(--vow)'};
const DTYPE={person:'Человек',org:'Организация'};
const dMetLbl=c=>c.type==='org'?'Имели дело':'Знакомы лично';
const dSeenLbl=c=>c.type==='org'?'Последний контакт':'Видели в последний раз';
const dSeenShort=c=>c.type==='org'?'Последний контакт':'Видели';
const DVIS={'стол':'Все игроки','знают':'Только знающие персонажи','мастер':'Скрыта от игроков'};
const FVIS={'стол':'Все, кто видит карточку','знают':'Только отмеченные персонажи','мастер':'Пока скрыто от игроков'};
Object.assign(UI,{dq:'',dtype:'all',dstance:'all',dvis:'all'});
function dossierVisible(){
  const D=S.dossier||[];
  if(!S.me.gm||V==='gm')return D;
  const vc=viewChars()||[];
  const has=(vis,known)=>vis==='стол'||(vis==='знают'&&(known||[]).some(c=>vc.includes(c)));
  const pv=placesVisible();
  return D.filter(c=>has(c.vis,c.known)).map(c=>Object.assign({},c,{facts:(c.facts||[]).filter(f=>has(f.vis,f.known)&&!(hzPreview()&&f.date&&f.date>hzPreview())).map(f=>Object.assign({},f,{truth:''})),gm_note:'',last_place:pv.some(p=>p.id===c.last_place)?c.last_place:''}));
}
function dossierCards(){
  const q=(UI.dq||'').trim().toLowerCase();
  return dossierVisible().filter(c=>(UI.dtype==='all'||c.type===UI.dtype)&&(UI.dstance==='all'||c.stance===UI.dstance)
    &&(V!=='gm'||UI.dvis==='all'||(UI.dvis==='open'?c.vis!=='мастер':c.vis==='мастер'))
    &&(!q||dSearchText(c).includes(q))).sort((a,b)=>a.name.localeCompare(b.name,'ru'));
}
const dSearchText=c=>[c.name,c.alias,c.role,c.org,c.last_note].concat((c.facts||[]).map(f=>f.text+' '+(V==='gm'?f.truth||'':''))).concat(V==='gm'?[c.gm_note]:[]).join(' ').toLowerCase();
const dAlias=c=>c.alias?(c.type==='org'?esc(c.alias):'«'+esc(c.alias)+'»'):'';
function dCard(c){
  const gm=V==='gm',hidden=gm&&c.vis==='мастер',partial=gm&&c.vis==='знают';
  const met=(c.met||[]).map(x=>CN[x]||x),pl=c.last_place?placeById(c.last_place):null;
  const last=[c.last_date?fDate(c.last_date):'',pl?pl.name:''].filter(Boolean).join(', ');
  const nf=(c.facts||[]).length;
  return `<button type="button" class="dc ${c.type} ${hidden?'dc-hidden':''}" data-open="n:${c.id}" style="--sc:${STANCE_CLR[c.stance]||'var(--muted)'}">
    <span class="dc-av ${c.img?'dc-img':''}" aria-hidden="true">${c.img?`<img src="${pimg(c,'t')}" alt="" width="48" height="48" loading="lazy" decoding="async">`:esc((c.name.trim()[0]||'?').toUpperCase())}</span>
    <span class="dc-main"><span class="dc-name">${esc(c.name)}${c.alias?` <i>${dAlias(c)}</i>`:''}</span>
    ${c.role?`<span class="dc-role">${esc(c.role)}</span>`:''}
    <span class="dc-chips"><span class="dc-st">${STANCE[c.stance]||''}</span>${c.org?`<span>${esc(c.org)}</span>`:''}${hidden?'<span class="dc-gm">скрыта</span>':''}${partial?'<span class="dc-gm">часть игроков</span>':''}${gm?`<span>${nf} ${plural(nf,'сведение','сведения','сведений')}</span>`:''}</span>
    ${met.length?`<span class="dc-line">${dMetLbl(c)}: ${esc(joinNames(met))}</span>`:''}${last?`<span class="dc-line">${dSeenShort(c)}: ${esc(last)}</span>`:''}</span></button>`;
}
function dList(){
  const L=dossierCards(),all=dossierVisible();
  if(!L.length)return `<p class="muted">${all.length?'Ничего не найдено. Измените поиск или фильтры.':(V==='gm'?'Карточек пока нет.':'В досье пока пусто. Карточки появляются по мере того, как пачка узнаёт людей.')}</p>`;
  return `<div class="dgrid">${L.map(dCard).join('')}</div>`;
}
function rDossier(){
  const all=dossierVisible();
  const seg=(k,opts,cur)=>`<div class="seg" role="group">${opts.map(([v,t])=>`<button type="button" data-act="dfilter" data-k="${k}" data-v="${v}" aria-pressed="${cur===v}">${t}</button>`).join('')}</div>`;
  const opened=all.filter(c=>c.vis!=='мастер').length;
  return `<section class="dossier"><div class="d-top"><h1>Досье</h1>${V==='gm'?'<button type="button" class="btn primary" data-act="new-item" data-kind="dossier">Добавить карточку</button>':''}</div>
  <p class="note">${V==='gm'?`Карточек: ${all.length}, открыто игрокам: ${opened}.${S.portraits?` Картинки: ${fmtMB(S.portraits.used)} из ${fmtMB(S.portraits.quota)}.`:''} Карточка открывается кнопкой в её окне.`:'Люди и организации, с которыми пачка сталкивалась, и всё, что о них известно.'}</p>
  <div class="d-tools"><input id="dq" type="search" placeholder="Поиск по досье" value="${esc(UI.dq)}" aria-label="Поиск по имени, организации и сведениям" autocomplete="off">
  ${seg('dtype',[['all','Все'],['person','Люди'],['org','Организации']],UI.dtype)}
  ${seg('dstance',[['all','Любые'],['contact','Контакты'],['ally','Союзники'],['neutral','Нейтральные'],['hostile','Враги'],['unknown','Неясно']],UI.dstance)}
  ${V==='gm'?seg('dvis',[['all','Все карточки'],['open','Открытые'],['hidden','Скрытые']],UI.dvis):''}</div>
  <div id="dlist">${dList()}</div></section>`;
}
const factWho=f=>joinNames((f.known||[]).map(x=>CN[x]||x));
function openDossier(id,keep){
  const c=dossierVisible().find(x=>x.id===id);if(!c){closePanel();return;}
  curKey='n:'+id;
  const gm=V==='gm',pl=c.last_place?placeById(c.last_place):null,met=(c.met||[]).map(x=>CN[x]||x),facts=c.facts||[];
  const fh=facts.map(f=>`<li class="fact ${gm&&f.vis==='мастер'?'fact-hidden':''}"><div class="ft">${rich(f.text)}</div>
    <div class="fm">${f.date?esc(fFull(f.date)):''}${gm?`${f.date?' · ':''}${f.vis==='знают'?'только: '+esc(factWho(f)):({'стол':'видят все, кто видит карточку','мастер':'скрыто от игроков'}[f.vis])}`:''}</div>
    ${gm&&f.truth?`<div class="ftruth"><b>На самом деле:</b> ${esc(f.truth)}</div>`:''}
    ${gm?`<div class="acts mini-acts"><button type="button" class="btn small" data-act="fact-vis" data-card="${c.id}" data-id="${esc(f.id)}">${f.vis==='мастер'?'Открыть игрокам':'Скрыть'}</button><button type="button" class="btn small" data-act="fact-edit" data-card="${c.id}" data-id="${esc(f.id)}">Изменить</button><button type="button" class="btn small plain" data-act="fact-del" data-card="${c.id}" data-id="${esc(f.id)}">Удалить</button></div>`:''}</li>`).join('');
  const seen=(c.last_date||pl||c.last_note)?`<dt>${dSeenLbl(c)}</dt><dd>${[c.last_date?esc(fFull(c.last_date)):'',pl?`${esc(pl.name)} <button type="button" class="btn plain mini" data-act="show-place" data-id="${pl.id}">на карте</button>`:'',c.last_note?rich(c.last_note):''].filter(Boolean).join(', ')}</dd>`:'';
  showPanel(`<div class="dp">${portraitBlock(c)}<div class="dp-txt"><p class="kind">${DTYPE[c.type]||''}<span class="dc-st" style="--sc:${STANCE_CLR[c.stance]||'var(--muted)'};color:var(--sc)">${STANCE[c.stance]||''}</span>${gm?`<span class="tag">${DVIS[c.vis]||''}</span>`:''}</p>
  <h2>${esc(c.name)}${c.alias?` <i class="muted">${dAlias(c)}</i>`:''}</h2>${c.role?`<p class="prose" style="margin-top:0">${rich(c.role)}</p>`:''}</div></div>
  ${gm?`<div class="acts pimg-acts"><button type="button" class="btn small" data-act="portrait-pick" data-id="${c.id}">${c.img?'Заменить картинку':'Добавить картинку'}</button>${c.img?`<button type="button" class="btn small plain" data-act="portrait-del" data-id="${c.id}">Убрать картинку</button>`:''}</div>`:''}
  <dl class="dd">${c.org?`<dt>Организация</dt><dd>${esc(c.org)}</dd>`:''}${met.length?`<dt>${dMetLbl(c)}</dt><dd>${esc(joinNames(met))}</dd>`:''}${gm&&c.vis==='знают'?`<dt>Карточка открыта</dt><dd>${esc(joinNames((c.known||[]).map(x=>CN[x]||x)))}</dd>`:''}${seen}</dl>
  <h3>Что известно</h3>${facts.length?`<ul class="facts">${fh}</ul>`:'<p class="muted" style="margin:0">Пока ничего конкретного.</p>'}
  ${mentionsHTML(c)}
  ${gm?`<div class="acts" style="margin-top:12px"><button type="button" class="btn" data-act="fact-add" data-card="${c.id}">Добавить сведение</button></div>
  ${c.gm_note?`<h3>Заметка мастера</h3><p class="prose" style="margin-top:0;white-space:pre-wrap">${rich(c.gm_note)}</p>`:''}
  <div class="acts"><button type="button" class="btn primary" data-act="dcard-vis" data-id="${c.id}">${c.vis==='стол'?'Скрыть от игроков':'Открыть всем игрокам'}</button><button type="button" class="btn" data-act="edit-item" data-kind="dossier" data-id="${c.id}">Изменить карточку</button><button type="button" class="btn plain" data-act="item-history" data-kind="dossier" data-id="${c.id}">История</button><button type="button" class="btn plain" data-act="del-item" data-kind="dossier" data-id="${c.id}">Удалить</button></div>`:''}`,keep);
}
function openFactForm(cardId,factId){
  const c=(S.dossier||[]).find(x=>x.id===cardId);if(!c)return;
  const it=factId?(c.facts||[]).find(f=>f.id===factId):null;
  const vis=it?it.vis:(c.vis==='мастер'?'мастер':'стол');
  curKey=null;
  showPanel(`<p class="kind">${esc(c.name)}</p><h2>${it?'Изменить сведение':'Новое сведение'}</h2><form id="fact-form" data-card="${c.id}" data-fact="${it?esc(it.id):''}" novalidate>
  <label class="field">Что известно<textarea name="text" rows="4" maxlength="1500">${esc(it&&it.text)}</textarea><span class="sub">Сослаться на другую карточку можно так: [[Имя]].</span></label>
  <label class="field">Когда стало известно<select name="date">${dateOpts(it?it.date:S.now.date,'не указано')}</select></label>
  <fieldset class="vis"><legend>Кто видит</legend>${Object.entries(FVIS).map(([k,t])=>`<label><input type="radio" name="fvis" value="${k}" ${vis===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
  <fieldset class="who" id="fknown-box" ${vis==='знают'?'':'hidden'}><legend>Кто из персонажей знает</legend><span class="sub muted small" style="flex-basis:100%">Сведение видит только тот, кому открыта и карточка, и само сведение.</span>${CHARS.map(x=>`<label><input type="checkbox" name="fknown" value="${x.id}" ${it&&(it.known||[]).includes(x.id)?'checked':''}> ${esc(x.name)}</label>`).join('')}</fieldset>
  <label class="field">На самом деле<textarea name="truth" rows="3" maxlength="1500">${esc(it&&it.truth)}</textarea><span class="sub">Заполните, если пачка узнала неточное или ложное. Игроки эту поправку не видят.</span></label>
  <p class="err" id="form-err" role="alert"></p><div class="acts"><button type="submit" class="btn primary">${it?'Сохранить':'Добавить'}</button><button type="button" class="btn" data-act="dback" data-id="${c.id}">Отмена</button></div></form>`);
  const form=document.getElementById('fact-form');
  form.addEventListener('input',()=>{document.getElementById('form-err').textContent='';});
  form.addEventListener('change',ev=>{if(ev.target.name==='fvis')document.getElementById('fknown-box').hidden=ev.target.value!=='знают';});
}
async function postCard(c,patch,msg){
  const j=await apiPost('/api/gm/items/dossier',Object.assign({},c,patch));
  if(j){render(true);openDossier(c.id,true);if(msg)toast(msg);}
  return j;
}

/* ===== Картинки досье ===== */
const pimg=(c,n)=>c.img?`/portrait/${c.img}/${n}.webp`:'';
const fmtMB=n=>{if(n<1048576)return Math.round(n/1024)+' КБ';const v=n/1048576;return (v<10?v.toFixed(2):v.toFixed(1)).replace('.',',').replace(/,0$/,'')+' МБ';};
function portraitBlock(c){
  if(!c.img)return '';
  return `<button type="button" class="dp-img ${c.type}" data-act="zoom-img" data-src="${pimg(c,'f')}" data-alt="${esc(c.name)}" aria-label="Увеличить картинку"><img src="${pimg(c,'f')}" alt="" width="112" height="112"></button>`;
}
function openLightbox(src,alt){
  const d=document.createElement('div');d.className='lb';d.setAttribute('role','dialog');d.setAttribute('aria-label',alt||'Картинка');
  d.setAttribute('aria-modal','true');d.tabIndex=-1;
  d.innerHTML=`<img src="${esc(src)}" alt="${esc(alt||'')}"><button type="button" class="btn plain lb-x">Закрыть</button>`;
  const back=document.activeElement;
  const onKey=e=>{if(e.key==='Escape'||e.key==='Tab'){e.preventDefault();e.stopPropagation();if(e.key==='Escape')close();}};
  const close=()=>{d.remove();document.removeEventListener('keydown',onKey,true);if(back&&document.body.contains(back))back.focus();};
  d.addEventListener('click',close);document.addEventListener('keydown',onKey,true);document.body.appendChild(d);d.focus();
}
function pickPortrait(cardId){
  if(RO()){toast('Предпросмотр: действия отключены');return;}
  let inp=document.getElementById('pfile');
  if(!inp){
    inp=document.createElement('input');inp.type='file';inp.id='pfile';inp.accept='image/*';inp.hidden=true;document.body.appendChild(inp);
    inp.addEventListener('change',()=>{const f=inp.files&&inp.files[0],id=inp.dataset.card;inp.value='';if(f&&id)openCropper(id,f);});
  }
  inp.dataset.card=cardId;inp.click();
}
function openCropper(cardId,file){
  const c=(S.dossier||[]).find(x=>x.id===cardId);if(!c)return;
  if(file.size>40*1048576){toast('Файл слишком большой. Возьмите картинку поменьше.');return;}
  const url=URL.createObjectURL(file),im=new Image();
  im.onload=()=>{
    URL.revokeObjectURL(url);
    if(Math.min(im.naturalWidth,im.naturalHeight)<96){toast('Картинка слишком маленькая: нужно хотя бы 96 точек по короткой стороне.');return;}
    startCrop(c,im);
  };
  im.onerror=()=>{URL.revokeObjectURL(url);toast('Не удалось открыть картинку. Подойдут JPEG, PNG и WebP.');};
  im.src=url;
}
function startCrop(c,im){
  curKey=null;
  showPanel(`<p class="kind">${esc(c.name)}</p><h2>Картинка</h2>
  <p class="note" style="margin:0 0 12px">Перетащите картинку и подберите масштаб. Сохранится квадрат, картинка сожмётся до небольшого размера.</p>
  <div class="crop ${c.type}" id="crop"><canvas id="crop-cv"></canvas></div>
  <label class="field" style="margin-top:12px">Масштаб<input type="range" id="crop-zoom" min="1" max="4" step="0.01" value="1"></label>
  <p class="err" id="form-err" role="alert"></p>
  <div class="acts"><button type="button" class="btn primary" id="crop-save">Сохранить</button><button type="button" class="btn" id="crop-cancel">Отмена</button></div>`);
  const box=document.getElementById('crop'),cv=document.getElementById('crop-cv'),zoom=document.getElementById('crop-zoom'),err=document.getElementById('form-err');
  const iw=im.naturalWidth,ih=im.naturalHeight,side=box.clientWidth,dpr=Math.min(window.devicePixelRatio||1,2);
  cv.width=cv.height=Math.round(side*dpr);
  const ctx=cv.getContext('2d');ctx.imageSmoothingQuality='high';
  const minS=side/Math.min(iw,ih);let z=1,cx=iw/2,cy=ih>iw?side/(2*minS)+(ih-side/minS)*0.2:ih/2;
  const clamp=()=>{const half=side/(2*minS*z);cx=Math.min(Math.max(cx,half),iw-half);cy=Math.min(Math.max(cy,half),ih-half);};
  const rect=()=>{clamp();const w=side/(minS*z);return [cx-w/2,cy-w/2,w];};
  const draw=()=>{const [sx,sy,w]=rect();ctx.clearRect(0,0,cv.width,cv.height);ctx.drawImage(im,sx,sy,w,w,0,0,cv.width,cv.height);};
  draw();
  let drag=null;
  box.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];box.setPointerCapture(e.pointerId);box.classList.add('grab');});
  box.addEventListener('pointermove',e=>{if(!drag)return;const s=minS*z;cx-=(e.clientX-drag[0])/s;cy-=(e.clientY-drag[1])/s;drag=[e.clientX,e.clientY];draw();});
  const end=()=>{drag=null;box.classList.remove('grab');};
  box.addEventListener('pointerup',end);box.addEventListener('pointercancel',end);
  box.addEventListener('wheel',e=>{e.preventDefault();z=Math.min(4,Math.max(1,z*Math.exp(-e.deltaY*0.0015)));zoom.value=z;draw();},{passive:false});
  zoom.addEventListener('input',()=>{z=+zoom.value;draw();});
  document.getElementById('crop-cancel').onclick=()=>openDossier(c.id);
  document.getElementById('crop-save').onclick=async ev=>{
    const btn=ev.currentTarget;btn.disabled=true;btn.textContent='Загружается…';err.textContent='';
    const [sx,sy,w]=rect();
    const out=document.createElement('canvas');out.width=out.height=512;
    const o=out.getContext('2d');o.imageSmoothingQuality='high';o.drawImage(im,sx,sy,w,w,0,0,512,512);
    let blob=await new Promise(r=>out.toBlob(r,'image/webp',0.9));
    if(!blob||blob.type!=='image/webp')blob=await new Promise(r=>out.toBlob(r,'image/jpeg',0.9));
    const reset=()=>{btn.disabled=false;btn.textContent='Сохранить';};
    if(!blob){err.textContent='Не удалось подготовить картинку.';reset();return;}
    const j=await uploadPortrait(c.id,blob,m=>{err.textContent=m;});
    reset();
    if(j){render(true);openDossier(c.id);toast(j.msg);}
  };
}
async function uploadPortrait(cardId,blob,onError){
  if(RO()){toast('Предпросмотр: действия отключены');return null;}
  if(busy)return null;busy=true;
  try{
    const r=await fetch(`/api/gm/dossier/${encodeURIComponent(cardId)}/portrait`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':blob.type||'application/octet-stream',...authHeaders()},body:blob});
    let j=null;try{j=await r.json();}catch(e){}
    if(r.status===401){showLogin();return null;}
    if(!r.ok){onError(r.status===413&&!j?'Файл слишком большой для портала. Уменьшите картинку.':errText(j));return null;}
    if(j&&j.state)applyState(j.state);
    return j;
  }catch(e){onError('Нет связи с порталом. Проверьте интернет и попробуйте ещё раз.');return null;}
  finally{busy=false;}
}
