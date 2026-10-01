/* ===== Импорт мест на карту: набор точек из «Seattle 2072» и KML из Google My Maps ===== */
const IMP_ORDER=['Корпорации','Город и ориентиры','Полиция и тюрьмы','Медицина','Клубы, бары, казино','Магазины и рынки','Фон: еда','Фон: бары и клубы','Фон: ночлег','Фон: магазины','Фон: досуг','Внутри стены Догтауна'];
const IMP_COMMON_WORDS=['банда','штаб','сиэтле','тюрьма','больница','the'];
let IMP=null,POI=null,LLGRID=null;

/* --- чистые функции: проверяются отдельно (tests/js/import.test.js) --- */
function impWords(n){return new Set((String(n).toLowerCase().match(/[a-zа-яё0-9]{4,}/g)||[]).filter(w=>!IMP_COMMON_WORDS.includes(w)));}
// Есть ли уже такое место на карте (P: места карты). Возвращает пояснение или пустую строку.
function impDup(it,P){
  for(const keys of (it.same||[])){const p=P.find(p=>keys.every(k=>p.name.toLowerCase().includes(k.toLowerCase())));if(p)return `уже на карте: «${p.name}»`;}
  // дубль: то же название поблизости, похожее название рядом или точка практически в том же месте
  const iw=impWords(it.name);
  for(const p of P){
    const d=Math.hypot(p.x-it.x,p.y-it.y);if(d>600)continue;
    const same=p.name.toLowerCase()===it.name.toLowerCase(),shared=[...impWords(p.name)].some(w=>iw.has(w));
    if(same||(shared&&d<300)||d<25)return `${same?'уже на карте':'рядом уже есть'} «${p.name}», ${Math.round(d)} м`;
  }
  return '';
}
// Долгота и широта в координаты карты: билинейная интерполяция по сетке g (static/map/llgrid.json). Вне сетки или карты: null.
function llToXY(lon,lat,g,W,H){
  const fx=(lon-g.lon0)/g.step,fy=(lat-g.lat0)/g.step,i=Math.floor(fx),j=Math.floor(fy);
  if(!(i>=0&&j>=0&&i<g.nx-1&&j<g.ny-1))return null;
  const tx=fx-i,ty=fy-j,at=(a,ii,jj)=>a[jj*g.nx+ii];
  const f=a=>(1-tx)*(1-ty)*at(a,i,j)+tx*(1-ty)*at(a,i+1,j)+(1-tx)*ty*at(a,i,j+1)+tx*ty*at(a,i+1,j+1);
  const x=Math.round(f(g.x)),y=Math.round(f(g.y));
  return x<0||y<0||x>W||y>H?null:[x,y];
}
// Точки из текста KML: [{id,name,type,group,rec,note,gm_note,x,y,same}] и сколько точек за краем карты пропущено.
function kmlItems(text,g,W,H){
  const strip=s=>(s||'').replace(/<!\[CDATA\[|\]\]>/g,'').replace(/<br\s*\/?>/gi,' ').replace(/<[^>]+>/g,'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;|&apos;/g,"'").replace(/&amp;/g,'&').replace(/\s+/g,' ').trim();
  const items=[];let skipped=0,k=0;
  text.split(/<Folder\b[^>]*>/i).forEach((part,pi)=>{
    const folder=pi===0?'Без слоя':(strip((part.match(/<name>([\s\S]*?)<\/name>/i)||[])[1])||`Слой ${pi}`).slice(0,60);
    for(const m of part.matchAll(/<Placemark\b[^>]*>([\s\S]*?)<\/Placemark>/gi)){
      const p=m[1],pt=p.match(/<Point\b[\s\S]*?<coordinates>\s*([-\d.]+)\s*,\s*([-\d.]+)/i);
      if(!pt)continue;
      const xy=llToXY(+pt[1],+pt[2],g,W,H);if(!xy){skipped++;continue;}
      const desc=strip((p.match(/<description>([\s\S]*?)<\/description>/i)||[])[1]);
      items.push({id:'k'+(k++),name:strip((p.match(/<name>([\s\S]*?)<\/name>/i)||[])[1]).slice(0,80)||'Без названия',type:'other',group:folder,rec:true,note:'',gm_note:('Из KML'+(desc?': '+desc:'')).slice(0,2000),x:xy[0],y:xy[1],same:[]});
    }
  });
  return {items,skipped};
}
// KMZ это zip-архив (начинается с «PK»): его читать нельзя, нужен обычный KML.
const impIsKmz=head=>head[0]===0x50&&head[1]===0x4b;

/* --- панель импорта --- */
async function impLoad(u){const r=await fetch(u,{credentials:'same-origin'});if(!r.ok)throw new Error(String(r.status));return r.json();}
function impPrepare(items){
  for(const it of items)it.dup=impDup(it,S.places||[]);
  IMP.items=items;IMP.on=new Set(items.filter(i=>i.rec&&!i.dup).map(i=>i.id));IMP.open=new Set();
}
async function openImport(src){
  if(V!=='gm')return;
  src=src||'canon';curKey=null;
  showPanel(`<p class="kind">Карта</p><h2>Импорт мест</h2><div id="imp"><p class="muted">Загружается…</p></div>`);
  IMP={src,items:[],on:new Set(),open:new Set(),vis:'стол',kmlName:'',skipped:0};
  if(src==='canon'){
    try{POI=POI||await impLoad('/static/map/poi_seattle2072.json');}
    catch(e){document.getElementById('imp').innerHTML='<p class="err">Не удалось загрузить набор точек. Обновите страницу.</p>';return;}
    impPrepare(POI.items.map(x=>Object.assign({},x)));
  }
  renderImport();
}
function renderImport(){
  const box=document.getElementById('imp');if(!box||!IMP)return;
  const groups=[];
  for(const it of IMP.items){let g=groups.find(g=>g.k===it.group);if(!g)groups.push(g={k:it.group,items:[]});g.items.push(it);}
  const ord=k=>{const i=IMP_ORDER.indexOf(k);return i<0?100:i;};
  groups.sort((a,b)=>ord(a.k)-ord(b.k)||a.k.localeCompare(b.k,'ru'));
  const n=IMP.on.size,types=Object.entries(PLACE_TYPES);
  box.innerHTML=`<div class="seg imp-seg" role="group"><button type="button" data-act="imp-src" data-v="canon" aria-pressed="${IMP.src==='canon'}">Канон Seattle 2072</button><button type="button" data-act="imp-src" data-v="kml" aria-pressed="${IMP.src==='kml'}">Свой файл KML</button></div>
  ${IMP.src==='canon'?`<p class="note imp-intro">Точки из книги «Seattle 2072» (открытый набор skiant/seattle-2072-map). У отобранных есть русские пояснения для игроков, канонический адрес ложится в заметку мастера. Рекомендуемое отмечено заранее; то, что уже есть на вашей карте, не отмечено. Существующие места импорт не меняет.</p>`
  :`<label class="field">Файл KML<input type="file" id="imp-file" accept=".kml,application/vnd.google-earth.kml+xml"><span class="sub">В Google My Maps: меню карты (три точки) → «Экспорт в KML/KMZ» → галочка «Экспортировать в файл .KML» → «Скачать».${IMP.kmlName?` Загружен файл «${esc(IMP.kmlName)}»: точек ${IMP.items.length}${IMP.skipped?`, за краем карты пропущено ${IMP.skipped}`:''}.`:''}</span></label>`}
  <fieldset class="vis"><legend>Кто увидит новые места</legend><label><input type="radio" name="imp-vis" value="стол" ${IMP.vis==='стол'?'checked':''}> Все игроки</label><label><input type="radio" name="imp-vis" value="мастер" ${IMP.vis==='мастер'?'checked':''}> Только мастер</label></fieldset>
  ${groups.map(g=>{const on=g.items.filter(i=>IMP.on.has(i.id)).length,open=IMP.open.has(g.k);
    return `<div class="imp-g"><div class="imp-gh"><input type="checkbox" data-imp-group="${esc(g.k)}" aria-label="Вся группа «${esc(g.k)}»" ${on===g.items.length?'checked':''} ${on&&on<g.items.length?'data-mixed="1"':''}><button type="button" class="imp-tog" data-act="imp-tog" data-v="${esc(g.k)}" aria-expanded="${open}">${esc(g.k)} <span class="muted">${on} из ${g.items.length}</span></button>${IMP.src==='kml'?`<select data-imp-type="${esc(g.k)}" aria-label="Тип мест группы «${esc(g.k)}»">${types.map(([k,t])=>`<option value="${k}" ${g.items[0].type===k?'selected':''}>${t}</option>`).join('')}</select>`:''}</div>
    <div class="imp-items" ${open?'':'hidden'}>${open?g.items.map(i=>`<label class="imp-row"><input type="checkbox" data-imp="${esc(i.id)}" ${IMP.on.has(i.id)?'checked':''}><span><b>${esc(i.name)}</b><span class="imp-meta">${PLACE_TYPES[i.type]||''}${i.bg?' · фон':''} · ${DNAMES[districtAt(i.x,i.y)]||'—'} · квадрат ${square(i.x,i.y)}</span>${i.note?`<span class="imp-note">${esc(i.note)}</span>`:''}${i.dup?`<span class="imp-dup">${esc(i.dup)}</span>`:''}</span></label>`).join(''):''}</div></div>`;}).join('')}
  ${IMP.src==='kml'&&!IMP.items.length?'<p class="muted">Выберите файл, чтобы увидеть его точки.</p>':''}
  <p class="err" id="imp-err" role="alert"></p>
  <div class="acts"><button type="button" class="btn primary" data-act="imp-go" ${n?'':'disabled'}>Добавить выбранные: ${n}</button><button type="button" class="btn" data-act="close">Отмена</button></div>`;
  box.querySelectorAll('input[data-mixed]').forEach(x=>{x.indeterminate=true;});
}
async function parseKml(text){
  if(!LLGRID)LLGRID=await impLoad('/static/map/llgrid.json');
  return kmlItems(text,LLGRID,MAPDATA.W,MAPDATA.H);
}
async function submitImport(btn){
  if(!IMP)return;
  const sel=IMP.items.filter(i=>IMP.on.has(i.id));if(!sel.length)return;
  const err=m=>{const e=document.getElementById('imp-err');if(e)e.textContent=m;};
  btn.disabled=true;btn.textContent='Добавляется…';
  const j=await apiPost('/api/gm/places/import',{items:sel.map(i=>({name:i.name,type:i.type,x:i.x,y:i.y,vis:IMP.vis,known:[],note:i.note||'',gm_note:i.gm_note||'',bg:!!i.bg}))},err);
  if(j){IMP=null;closePanel();refreshPlaces();toast(j.msg);}else{btn.disabled=false;btn.textContent='Повторить';}
}
if(typeof document!=='undefined'){
  document.addEventListener('change',async ev=>{
    const t=ev.target;if(!IMP||!t.closest||!t.closest('#imp'))return;
    if(t.dataset.imp){t.checked?IMP.on.add(t.dataset.imp):IMP.on.delete(t.dataset.imp);renderImport();}
    else if(t.dataset.impGroup!=null){for(const i of IMP.items)if(i.group===t.dataset.impGroup){t.checked?IMP.on.add(i.id):IMP.on.delete(i.id);}renderImport();}
    else if(t.dataset.impType!=null){for(const i of IMP.items)if(i.group===t.dataset.impType)i.type=t.value;for(const i of IMP.items)i.dup=impDup(i,S.places||[]);renderImport();}
    else if(t.name==='imp-vis')IMP.vis=t.value;
    else if(t.id==='imp-file'&&t.files[0]){
      const f=t.files[0];
      if(f.size>20*1048576){document.getElementById('imp-err').textContent='Файл слишком большой.';return;}
      if(impIsKmz(new Uint8Array(await f.slice(0,4).arrayBuffer()))){document.getElementById('imp-err').textContent='Это KMZ (архив). Выгрузите карту ещё раз с галочкой «Экспортировать в файл .KML».';return;}
      try{const r=await parseKml(await f.text());IMP.kmlName=f.name;IMP.skipped=r.skipped;impPrepare(r.items);for(const g of new Set(r.items.map(i=>i.group)))IMP.open.add(g);renderImport();}
      catch(e){document.getElementById('imp-err').textContent='Не удалось прочитать файл KML.';}
    }
  });
}
if(typeof module!=='undefined'&&module.exports){
  module.exports={IMP_ORDER,impWords,impDup,llToXY,kmlItems,impIsKmz};
}
