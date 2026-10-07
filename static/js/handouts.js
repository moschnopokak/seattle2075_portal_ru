/* ===== Раздатки ===== */
const HVIS={'стол':'Вся пачка','знают':'Только отмеченные персонажи','мастер':'Черновик: игроки не видят'};
const HO_KIND={html:'страница',image:'картинка',pdf:'PDF',audio:'аудио'};
const hoKind=h=>HO_KIND[h.kind]?h.kind:'html';
const HO_ICON={
  html:'<svg viewBox="0 0 20 20"><path d="M5 2.5h7l3.5 3.5V17.5H5z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M12 2.5V6h3.5M7.5 10h5M7.5 13h5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
  image:'<svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="12" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="7.5" cy="8.4" r="1.3" fill="currentColor"/><path d="M3.5 14l4-3.5 3 2.5 2.5-2 3.5 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  pdf:'<svg viewBox="0 0 20 20"><path d="M5 2.5h7l3.5 3.5V17.5H5z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M12 2.5V6h3.5" fill="none" stroke="currentColor" stroke-width="1.4"/><text x="10.2" y="14.6" font-size="5.2" font-weight="700" text-anchor="middle" fill="currentColor">PDF</text></svg>',
  audio:'<svg viewBox="0 0 20 20"><path d="M3.5 8v4h3l4 3.2V4.8L6.5 8z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M13.2 7.4a3.6 3.6 0 010 5.2M15.4 5.2a6.6 6.6 0 010 9.6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'};
const HOUT_SANDBOX='allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals allow-forms allow-downloads';
Object.assign(UI,{hq:''});
const seenKey=()=>'seattle2075-seen-handouts:'+(S&&S.me?S.me.name:'');
function seenSet(){try{return new Set(JSON.parse(localStorage.getItem(seenKey())||'[]'));}catch(e){return new Set();}}
function markSeen(id){try{const s=seenSet();if(s.has(id))return;s.add(id);localStorage.setItem(seenKey(),JSON.stringify([...s]));}catch(e){}}
function handoutsVisible(){
  const H=S.handouts||[];
  if(!S.me.gm||V==='gm')return H;
  const vc=viewChars()||[];
  return H.filter(h=>h.file&&!(hzPreview()&&h.date>hzPreview())&&(h.vis==='стол'||(h.vis==='знают'&&(h.known||[]).some(c=>vc.includes(c)))))
    .map(h=>Object.assign({},h,{gm_note:'',fname:'',known:h.vis==='знают'?(h.known||[]).filter(c=>vc.includes(c)):[]}));
}
const hNew=h=>V!=='gm'&&!S.me.gm&&!seenSet().has(h.id);
const hWho=h=>h.vis==='стол'?'вся пачка':h.vis==='знают'?joinNames((h.known||[]).map(c=>CN[c]||c)):'черновик';
const hSize=n=>n>=1048576?(n/1048576).toFixed(1).replace('.',',')+' МБ':Math.max(1,Math.round(n/1024))+' КБ';
function unseenHandouts(){if(!S||S.me.gm)return 0;const s=seenSet();return handoutsVisible().filter(h=>!s.has(h.id)).length;}
function hCard(h){
  const gm=V==='gm',pl=h.place?placeById(h.place):null;
  return `<button type="button" class="hc ${gm&&h.vis==='мастер'?'hc-draft':''}" data-open="h:${h.id}">
    <span class="hc-ico" aria-hidden="true">${HO_ICON[hoKind(h)]}</span>
    <span class="hc-main"><span class="hc-title">${esc(h.title)}${hNew(h)?' <b class="hc-new">новое</b>':''}</span>
    <span class="hc-meta">${esc(fFull(h.date))} · ${esc(hWho(h))}${hoKind(h)!=='html'?' · '+HO_KIND[hoKind(h)]:''}${pl?' · '+esc(pl.name):''}</span>
    ${h.note?`<span class="hc-note">${esc(h.note)}</span>`:''}
    ${gm?`<span class="hc-gm">${h.file?hSize(h.size||0):'<b>файл не загружен</b>'}</span>`:''}</span></button>`;
}
function rHandouts(){
  const all=handoutsVisible(),q=(UI.hq||'').trim().toLowerCase();
  const L=all.filter(h=>!q||[h.title,h.note,V==='gm'?h.gm_note:''].join(' ').toLowerCase().includes(q)).sort((a,b)=>a.date<b.date?1:a.date>b.date?-1:(b.uploaded||0)-(a.uploaded||0));
  const u=S.handout_usage;
  let h=`<section class="handouts"><div class="d-top"><h1>Раздатки</h1>${V==='gm'?'<button type="button" class="btn primary" data-act="h-new">Добавить раздатку</button>':''}</div>
  <p class="note">${V==='gm'?`Раздаток: ${all.length}, выдано: ${all.filter(x=>x.file&&x.vis!=='мастер').length}.${u?` Занято ${fmtMB(u.used)} из ${fmtMB(u.quota)}.`:''} Раздатку видят только те, кому она выдана.`:'Всё, что пачка получила на руки. Раздатка открывается на весь экран.'}</p>
  <div class="d-tools"><input id="hq" type="search" placeholder="Поиск по раздаткам" aria-label="Поиск по названию и комментарию" value="${esc(UI.hq)}" autocomplete="off"></div>`;
  if(!L.length)return h+`<p class="muted">${all.length?'Ничего не найдено.':(V==='gm'?'Раздаток пока нет.':'Раздаток пока нет. Они появятся, когда мастер их выдаст.')}</p></section>`;
  const groups=[];
  for(const x of L){const w=S.windows.find(w=>x.date>=w.from&&x.date<=w.to&&winVisible(w));const k=w?winName(w):'Вне этапов';let g=groups.find(g=>g.k===k);if(!g)groups.push(g={k,items:[]});g.items.push(x);}
  for(const g of groups)h+=`<h2 class="h-group">${esc(g.k)}</h2><div class="hgrid">${g.items.map(hCard).join('')}</div>`;
  return h+'</section>';
}
/* Содержимое окна просмотра: HTML и PDF в рамке (HTML в песочнице), картинка, звук. */
function hBody(h,src,kind){
  const t=esc(h.title);
  if(kind==='image')return `<div class="hv-media"><img class="hv-img" src="${src}" alt="${t}" data-hv="imgzoom" title="Нажмите, чтобы увеличить"></div>`;
  if(kind==='audio')return `<div class="hv-media"><audio class="hv-audio" controls preload="metadata" src="${src}" aria-label="${t}"></audio></div>`;
  if(kind==='pdf')return `<iframe class="hv-frame" src="${src}" referrerpolicy="no-referrer" title="${t}"></iframe>`;
  return `<iframe class="hv-frame" src="${src}" sandbox="${HOUT_SANDBOX}" referrerpolicy="no-referrer" title="${t}"></iframe>`;
}
let HV=null;
function closeHandout(){if(!HV)return;const {el,back,onKey,onMsg}=HV;HV=null;el.remove();document.removeEventListener('keydown',onKey,true);window.removeEventListener('message',onMsg);document.body.classList.remove('hv-open');if(back&&document.body.contains(back))back.focus();if(UI.section==='handouts')render(true);}
function openHandout(id){
  const h=handoutsVisible().find(x=>x.id===id);if(!h)return;
  closePanel();if(HV)closeHandout();
  const gm=V==='gm',pl=h.place?placeById(h.place):null,src=h.file?`/handout/${h.file}/view`:'',kind=hoKind(h);
  if(h.file&&!S.me.gm)markSeen(h.id);
  const el=document.createElement('div');el.className='hv';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');el.setAttribute('aria-label',h.title);el.tabIndex=-1;
  el.innerHTML=`<header class="hv-top"><div class="hv-row">
    <div class="hv-t"><h2>${esc(h.title)}</h2><p class="hv-meta">Получено ${esc(fFull(h.date))} <button type="button" class="btn plain mini" data-hv="day">день в календаре</button> · ${esc(hWho(h))}${pl?` · ${esc(pl.name)} <button type="button" class="btn plain mini" data-hv="place">на карте</button>`:''}</p></div>
    <div class="hv-acts"><div class="hv-zoom" role="group" aria-label="Масштаб" hidden><button type="button" class="btn" data-hv="zout" aria-label="Уменьшить">−</button><button type="button" class="btn hv-pct" data-hv="zfit" title="Вписать в ширину экрана">100%</button><button type="button" class="btn" data-hv="zin" aria-label="Увеличить">+</button></div>${src?`<a class="btn" href="${src}" target="_blank" rel="noopener">Открыть отдельно</a>`:''}${src&&kind!=='html'?`<a class="btn" href="${src}" download="${esc(h.fname||h.title)}">Скачать</a>`:''}${gm?'<button type="button" class="btn" data-hv="edit">Изменить</button>':''}</div><button type="button" class="btn hv-x" data-hv="close">Закрыть</button></div>
    </header>
    ${h.note||(gm&&h.gm_note)?`<div class="hv-notes">${h.note?`<p class="hv-note">${esc(h.note)}</p>`:''}${gm&&h.gm_note?`<p class="hv-gmnote"><b>Заметка мастера:</b> ${esc(h.gm_note)}</p>`:''}</div>`:''}
    ${src?hBody(h,src,kind):`<div class="hv-empty"><p>Файл раздатки ещё не загружен.</p>${gm?'<button type="button" class="btn primary" data-hv="edit">Загрузить файл</button>':''}</div>`}`;
  const back=document.activeElement;
  const frame=()=>el.querySelector('.hv-frame');
  const zoomCmd=cmd=>{const f=frame();if(f&&f.contentWindow)f.contentWindow.postMessage({kind:'seattle2075-handout',cmd},'*');};
  const onMsg=e=>{
    const f=frame();if(!f||e.source!==f.contentWindow)return;
    const d=e.data;if(!d||d.kind!=='seattle2075-handout'||typeof d.pct!=='number')return;
    const g=el.querySelector('.hv-zoom');g.hidden=false;
    g.querySelector('.hv-pct').textContent=Math.max(1,Math.min(999,Math.round(d.pct)))+'%';
    g.querySelector('[data-hv="zout"]').disabled=!!d.min;g.querySelector('[data-hv="zin"]').disabled=!!d.max;
    g.querySelector('.hv-pct').setAttribute('aria-pressed',d.fit?'true':'false');
  };
  window.addEventListener('message',onMsg);
  const onKey=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeHandout();return;}
    if(el.querySelector('.hv-zoom').hidden||e.ctrlKey||e.metaKey||e.altKey)return;
    if(e.key==='+'||e.key==='='){e.preventDefault();zoomCmd('in');}else if(e.key==='-'){e.preventDefault();zoomCmd('out');}else if(e.key==='0'){e.preventDefault();zoomCmd('fit');}};
  el.addEventListener('click',e=>{const b=e.target.closest('[data-hv]');if(!b)return;const a=b.dataset.hv;
    if(a==='close')closeHandout();
    else if(a==='imgzoom')b.classList.toggle('full');
    else if(a==='edit'){closeHandout();openHandoutForm(h.id);}
    else if(a==='zin'||a==='zout'||a==='zfit')zoomCmd(a.slice(1));
    else if(a==='day'){closeHandout();UI.section='cal';UI.cal='lanes';UI.span='week';UI.stage=null;UI.anchor=clampDate(addDays(h.date,-1));render();window.scrollTo(0,0);}
    else if(a==='place'&&pl){closeHandout();UI.focusPlace=pl.id;UI.section='map';render();}
  });
  document.addEventListener('keydown',onKey,true);document.body.appendChild(el);document.body.classList.add('hv-open');el.focus();
  const fr=frame();if(fr&&kind==='html')fr.addEventListener('load',()=>zoomCmd('hello'));
  HV={el,back,onKey,onMsg,id};
}
function openHandoutForm(id){
  if(V!=='gm')return;
  const it=id?(S.handouts||[]).find(x=>x.id===id):null;
  const vis=it?it.vis:'мастер',lim=(S.handout_usage||{}).limit||15*1048576;
  const plc=(S.places||[]).slice().sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  curKey=null;
  showPanel(`<p class="kind">Раздатка</p><h2>${it?'Изменить':'Новая раздатка'}</h2><form id="handout-form" data-id="${it?it.id:''}" novalidate>
  <label class="field">Файл<input type="file" name="file" accept=".html,.htm,.pdf,.png,.jpg,.jpeg,.gif,.webp,.mp3,.m4a,.ogg,.opus,.wav,.flac,text/html,application/pdf,image/png,image/jpeg,image/gif,image/webp,audio/*"><span class="sub">${it&&it.file?`Сейчас: ${esc(it.fname||HO_KIND[hoKind(it)])}, ${HO_KIND[hoKind(it)]}, ${hSize(it.size||0)}. Выберите файл, только если хотите заменить.`:`Подходят HTML-страницы, картинки (PNG, JPEG, GIF, WebP), PDF и аудио (MP3, M4A, OGG, WAV, FLAC). До ${fmtMB(lim)}.`}</span></label>
  <label class="field">Название<input name="title" maxlength="120" value="${esc(it?it.title:'')}" placeholder="Возьмётся из файла, если оставить пустым"></label>
  <label class="field">Когда получена<select name="date">${dateOpts(it?it.date:S.now.date)}</select></label>
  <fieldset class="vis"><legend>Кому выдана</legend>${Object.entries(HVIS).map(([k,t])=>`<label><input type="radio" name="vis" value="${k}" ${vis===k?'checked':''}> ${t}</label>`).join('')}</fieldset>
  <fieldset class="who" id="hknown-box" ${vis==='знают'?'':'hidden'}><legend>Кто получил</legend>${CHARS.map(c=>`<label><input type="checkbox" name="known" value="${c.id}" ${it&&(it.known||[]).includes(c.id)?'checked':''}> ${esc(c.name)}</label>`).join('')}</fieldset>
  <label class="field">Комментарий для игроков<textarea name="note" rows="3" maxlength="3000" placeholder="Например: нашли в сейфе Танаки, бумага пахнет табаком">${esc(it?it.note:'')}</textarea><span class="sub">Показывается над раздаткой.</span></label>
  <label class="field">Где получена<select name="place"><option value="">не указано</option>${plc.map(p=>`<option value="${p.id}" ${it&&it.place===p.id?'selected':''}>${esc(p.name)}${placeTag(p)}</option>`).join('')}</select></label>
  <label class="field">Заметка мастера<textarea name="gm_note" rows="3" maxlength="3000">${esc(it?it.gm_note:'')}</textarea><span class="sub">Игроки её не видят.</span></label>
  <p class="note">Игроки получают уведомление в Telegram, когда раздатка им выдана. Черновик никому не виден.</p>
  <p class="err" id="form-err" role="alert"></p>
  <div class="acts"><button type="submit" class="btn primary">${it?'Сохранить':'Добавить'}</button><button type="button" class="btn" data-act="close">Отмена</button>${it?`<button type="button" class="btn plain" data-act="del-item" data-kind="handouts" data-id="${it.id}">Удалить</button>`:''}</div></form>`);
  const form=document.getElementById('handout-form'),F=n=>form.elements.namedItem(n),err=m=>{document.getElementById('form-err').textContent=m;};
  form.addEventListener('input',()=>err(''));
  form.addEventListener('change',async ev=>{
    if(ev.target.name==='vis')document.getElementById('hknown-box').hidden=ev.target.value!=='знают';
    if(ev.target.name==='file'){
      const f=ev.target.files[0];if(!f)return;
      if(f.size>lim){err(`Файл больше ${fmtMB(lim)}. Уменьшите его, например сожмите картинки внутри.`);ev.target.value='';return;}
      if(!F('title').value.trim()&&/\.html?$/i.test(f.name)){try{const t=new DOMParser().parseFromString(await f.slice(0,200000).text(),'text/html').title.trim();if(t)F('title').value=t.slice(0,120);}catch(e){}}
      if(!F('title').value.trim())F('title').value=f.name.replace(/\.[a-z0-9]{2,5}$/i,'').slice(0,120);
    }
  });
}
async function submitHandout(form){
  const F=n=>form.elements.namedItem(n),err=m=>{document.getElementById('form-err').textContent=m;};
  const file=F('file').files[0],id=form.dataset.id;
  const old=id?(S.handouts||[]).find(x=>x.id===id):null;
  if(!id&&!file)return err('Выберите файл раздатки: HTML-страницу, картинку, PDF или аудио.');
  const vis=form.querySelector('input[name="vis"]:checked').value;
  const b={id:id||undefined,title:F('title').value.trim(),date:F('date').value,vis,known:[...form.querySelectorAll('input[name="known"]:checked')].map(x=>x.value),
    note:F('note').value.trim(),gm_note:F('gm_note').value.trim(),place:F('place').value};
  if(!b.title)return err('Укажите название раздатки.');
  const btn=form.querySelector('button[type="submit"]');btn.disabled=true;
  try{
    // новая раздатка сначала сохраняется черновиком: так игроки не получат уведомление раньше, чем загрузится файл
    const meta=file&&!(old&&old.file)?Object.assign({},b,{vis:'мастер',known:[]}):b;
    const before=new Set((S.handouts||[]).map(x=>x.id));
    const j=await apiPost('/api/gm/items/handouts',meta,err);if(!j)return;
    const hid=id||((S.handouts||[]).find(x=>!before.has(x.id))||{}).id;
    if(!hid)return err('Не удалось сохранить раздатку.');
    form.dataset.id=hid;
    if(file){
      btn.textContent='Загружается…';
      const up=await uploadHandout(hid,file,err);if(!up)return;
      if(meta!==b){const cur=(S.handouts||[]).find(x=>x.id===hid);const k=await apiPost('/api/gm/items/handouts',Object.assign({},cur,{vis:b.vis,known:b.known}),err);if(!k)return;}
    }
    closePanel();render(true);toast(b.vis==='мастер'?'Раздатка сохранена черновиком':(old&&old.file&&old.vis!=='мастер'?'Раздатка сохранена':'Раздатка выдана'));
  }finally{btn.disabled=false;btn.textContent=id?'Сохранить':'Добавить';}
}
async function uploadHandout(hid,file,onError){
  if(RO()){toast('Предпросмотр: действия отключены');return null;}
  if(busy)return null;busy=true;
  try{
    const r=await fetch(`/api/gm/handouts/${encodeURIComponent(hid)}/file`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type||'application/octet-stream','X-File-Name':encodeURIComponent(file.name),...authHeaders()},body:file});
    let j=null;try{j=await r.json();}catch(e){}
    if(r.status===401){showLogin();return null;}
    if(!r.ok){onError(r.status===413&&!j?'Файл слишком большой для портала. Уменьшите его.':errText(j));return null;}
    if(j&&j.state)applyState(j.state);
    return j;
  }catch(e){onError('Нет связи с порталом. Проверьте интернет и попробуйте ещё раз.');return null;}
  finally{busy=false;}
}
