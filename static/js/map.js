/* ===== Карта ===== */
const PLACE_TYPES={home:'Жильё и убежища',contact:'Контакты',business:'Бары, клубы, бизнес',corp:'Корпорации и ориентиры',medical:'Медицина',security:'Полиция и тюрьмы',shop:'Магазины',leisure:'Еда и отдых',danger:'Опасные места',checkpoint:'Пропускные пункты',other:'Другое'};
const PLACE_GLYPH={home:'<path d="M3.5 10.5 10 4.5l6.5 6V16h-13z"/>',contact:'<circle cx="10" cy="7.3" r="3"/><path d="M4.5 16.5c.5-3.3 2.7-5 5.5-5s5 1.7 5.5 5z"/>',business:'<rect x="4.5" y="5" width="11" height="10.5" rx="1.5"/>',corp:'<path d="M10 3.5 16.5 10 10 16.5 3.5 10z"/>',danger:'<path d="M10 3.5 17 16H3z"/>',checkpoint:'<rect x="3.5" y="7.5" width="13" height="5" rx="1"/>',medical:'<path d="M8 4h4v4h4v4h-4v4H8v-4H4V8h4z"/>',security:'<path d="M10 3l6 2.5V10c0 3.6-2.6 6.3-6 7.5C6.6 16.3 4 13.6 4 10V5.5z"/>',shop:'<path d="M4.5 7.5h11l-1 9h-9z"/><path d="M7.5 7.5V6a2.5 2.5 0 015 0v1.5h-1.4V6a1.1 1.1 0 00-2.2 0v1.5z"/>',leisure:'<path d="M5 5.5h8V11a4 4 0 01-8 0z"/><path d="M13 6.5h1.4a2.1 2.1 0 010 4.2H13V9.4h1.4a.8.8 0 000-1.6H13z"/><rect x="4" y="15.5" width="10" height="1.6" rx=".8"/>',other:'<circle cx="10" cy="10" r="5"/>'};
const DNAMES={downtown:'Даунтаун',bellevue:'Беллвью',tacoma:'Такома',auburn:'Оберн',renton:'Рентон',everett:'Эверетт',snohomish:'Сноухомиш',redmond:'Редмонд',puyallup:'Пуйаллап',council:'Совет-Айленд',dogtown:'Догтаун',fortlewis:'Форт-Льюис',outremer:'Аутремер',outside:'за пределами метроплекса'};
const TONE={downtown:1,bellevue:3,tacoma:2,auburn:1,renton:4,everett:2,snohomish:3,redmond:2,puyallup:3,fortlewis:4,council:5,outremer:6,dogtown:7};
const GRID_COLS='АБВГДЕЖЗИКЛМНОПРСТУФ';
const PVIS={'стол':'все игроки','знают':'только знающие персонажи','мастер':'скрыто от игроков'};
let MAPDATA=null,MAP=null,MAPL={},PMARK={},ADDING=false,MOVING=null,PENDING_PLACES=false;
function stopMoving(msg){if(!MOVING)return;const m=PMARK[MOVING];if(m&&m.dragging)m.dragging.disable();MOVING=null;if(PENDING_PLACES){PENDING_PLACES=false;refreshPlaces();}if(msg)toast(msg);}
const MAPLAYERS={places:true,bg:true,roads:true,grid:true};
try{Object.assign(MAPLAYERS,JSON.parse(localStorage.getItem('seattle2075-map-layers')||'{}'));}catch(e){}
const saveLayers=()=>{try{localStorage.setItem('seattle2075-map-layers',JSON.stringify(MAPLAYERS));}catch(e){}};
let resizeT=null;
window.addEventListener('resize',()=>{clearTimeout(resizeT);resizeT=setTimeout(()=>{
  if(UI.section!=='map')return;
  const tb=document.getElementById('app-top');document.documentElement.style.setProperty('--top-h',(tb?tb.offsetHeight:60)+'px');
  if(MAP&&MAP.getContainer()===document.getElementById('leaflet'))MAP.invalidateSize();
},120);});
function loadAsset(tag,attrs){return new Promise((res,rej)=>{const e=document.createElement(tag);Object.assign(e,attrs);e.onload=res;e.onerror=rej;document.head.appendChild(e);});}
async function ensureLeaflet(){if(window.L)return;await loadAsset('link',{rel:'stylesheet',href:'/static/vendor/leaflet.css'});await loadAsset('script',{src:'/static/vendor/leaflet.js'});}
const LL=(x,y)=>L.latLng(-y,x);
const square=(x,y)=>(GRID_COLS[Math.floor(x/5000)]||'?')+'-'+(Math.floor(y/5000)+1);
function districtAt(x,y){if(!MAPDATA)return '';for(const [slug,g] of Object.entries(MAPDATA.districts)){if(slug!=='outside'&&pip(x,y,g))return slug;}return 'outside';}
function placesVisible(){
  const P=S.places||[];
  if(!S.me.gm||V==='gm')return P;
  const vc=viewChars()||[];
  return P.filter(p=>p.vis!=='мастер'&&(p.vis!=='знают'||(p.known||[]).some(c=>vc.includes(c))));
}
const placeById=id=>(S.places||[]).find(p=>p.id===id);
const placeTag=p=>V!=='gm'||p.vis==='стол'?'':(p.vis==='мастер'?' (скрыто от игроков)':' (знают: '+joinNames((p.known||[]).map(c=>CN[c]||c))+')');
const placeWhere=p=>p&&(V!=='gm'||p.vis==='стол')?p.name:'';
function rMap(){return `<div class="map-shell"><div id="leaflet" aria-label="Карта Сиэтла 2075"></div><div class="map-tools" id="map-tools"></div><div class="map-hud" id="map-hud"></div><div class="map-measure" id="map-measure" role="region" aria-label="Линейка и время в пути" hidden></div></div>`;}
function updateMapTools(){
  const t=document.getElementById('map-tools');if(!t)return;
  t.innerHTML=`<button type="button" class="btn small ${MEASURE.on?'primary':''}" data-act="map-measure" aria-pressed="${MEASURE.on}">Линейка</button>${V==='gm'?`<button type="button" class="btn small ${ADDING?'primary':''}" data-act="map-add">${ADDING?'Щёлкните по карте, чтобы поставить место. Отмена':'Добавить место'}</button><button type="button" class="btn small" data-act="map-import">Импорт мест</button>`:''}
  ${['places','bg','roads','grid'].map(k=>`<label class="check" ${k==='bg'?'title="Фоновые места: магазины, еда, ночлег, досуг"':''}><input type="checkbox" data-layer="${k}" ${MAPLAYERS[k]?'checked':''}> ${{places:'Места',bg:'Фон',roads:'Дороги',grid:'Сетка'}[k]}</label>`).join('')}`;
  const el=document.getElementById('leaflet');if(el)el.classList.toggle('adding',ADDING);
}
function declutter(){
  const el=document.getElementById('leaflet');if(!el)return;
  const vw=el.getBoundingClientRect(),taken=[];
  const free=r=>!taken.some(t=>r.left<t.right+4&&r.right>t.left-4&&r.top<t.bottom+3&&r.bottom>t.top-3);
  const inView=r=>r.width>0&&r.right>vw.left&&r.left<vw.right&&r.bottom>vw.top&&r.top<vw.bottom;
  el.querySelectorAll('.ml-d span,.ml-w span').forEach(sp=>{const r=sp.getBoundingClientRect();if(inView(r))taken.push(r);});
  // подписи мест: сначала места пачки, потом остальные; значки не трогаем
  const PRI={home:0,contact:1,checkpoint:2,business:3,danger:4,medical:5,security:6,corp:7,other:8,shop:9,leisure:9};
  const names=[...el.querySelectorAll('.pl')].map(m=>({m,sp:m.querySelector('.pl-name'),k:(PRI[(m.className.match(/pl-(home|contact|checkpoint|business|danger|medical|security|corp|other|shop|leisure)\b/)||[])[1]]??9)+(m.classList.contains('pl-bg')?10:0)})).filter(o=>o.sp);
  names.sort((a,b)=>a.k-b.k);
  for(const o of names){o.sp.style.visibility='';const r=o.sp.getBoundingClientRect();if(!inView(r))continue;if(free(r))taken.push(r);else o.sp.style.visibility='hidden';}
  el.querySelectorAll('.ml-r').forEach(m=>{
    const r=m.firstElementChild.getBoundingClientRect();
    if(!inView(r)){m.style.visibility='';return;}
    if(free(r)){taken.push(r);m.style.visibility='';}else m.style.visibility='hidden';
  });
}
function setZoomClass(){
  const el=document.getElementById('leaflet');if(!el||!MAP)return;const z=MAP.getZoom();
  el.classList.toggle('z-far',z<-6.5);el.classList.toggle('z-mid',z>=-6.5&&z<-5);el.classList.toggle('z-near',z>=-5);
}
async function initMap(){
  const el=document.getElementById('leaflet');
  try{await ensureLeaflet();if(!MAPDATA)MAPDATA=await (await fetch('/static/map/map.json')).json();}
  catch(e){el.innerHTML='<p class="err" style="padding:20px">Не удалось загрузить карту. Обновите страницу.</p>';return;}
  if(!document.body.contains(el))return;
  if(MAP){try{MAP.remove();}catch(e){}MAP=null;}
  const {W,H}=MAPDATA;
  MAP=L.map(el,{crs:L.CRS.Simple,minZoom:-8,maxZoom:-0.5,zoomSnap:0.25,zoomDelta:0.5,wheelPxPerZoomLevel:90,attributionControl:false,maxBoundsViscosity:0.7});
  MAP.setMaxBounds(L.latLngBounds(LL(-10000,-10000),LL(W+10000,H+10000)));
  [['dist',210],['water',220],['grid',225],['roads',230],['borders',240],['labels',450]].forEach(([n,z])=>{MAP.createPane(n).style.zIndex=z;});
  MAP.getPane('labels').style.pointerEvents='none';
  const gj=(geom,opts)=>L.geoJSON({type:'Feature',geometry:geom},Object.assign({coordsToLatLng:c=>LL(c[0],c[1])},opts));
  MAPL={};
  MAPL.dist=L.layerGroup().addTo(MAP);
  for(const [slug,g] of Object.entries(MAPDATA.districts)){
    const lyr=gj(g,{pane:'dist',interactive:slug!=='outside',style:{className:`m-d ${slug==='outside'?'m-outside':'tone'+(TONE[slug]||1)}`,stroke:false,fillOpacity:1}});
    if(slug!=='outside')lyr.on('click',()=>{if(!ADDING&&!MEASURE.on)openDistrict(slug);});
    MAPL.dist.addLayer(lyr);
  }
  gj(MAPDATA.water,{pane:'water',interactive:true,bubblingMouseEvents:true,style:{className:'m-water m-coast',weight:.8,fillOpacity:1}}).addTo(MAP);
  const grid=[];for(let x=5000;x<W;x+=5000)grid.push([LL(x,0),LL(x,H)]);for(let y=5000;y<H;y+=5000)grid.push([LL(0,y),LL(W,y)]);
  MAPL.grid=L.layerGroup([L.polyline(grid,{pane:'grid',className:'m-grid',weight:1,interactive:false})]);
  const lbl=(x,y,cls,html)=>L.marker(LL(x,y),{pane:'labels',interactive:false,keyboard:false,icon:L.divIcon({className:'ml '+cls,html:`<span>${html}</span>`,iconSize:[0,0]})});
  for(let i=0;i*5000<W;i++)MAPL.grid.addLayer(lbl(i*5000+2500,700,'ml-g',GRID_COLS[i]));
  for(let j=0;j*5000<H;j++)MAPL.grid.addLayer(lbl(700,j*5000+2500,'ml-g',j+1));
  MAPL.roads=L.layerGroup([['primary','m-rp',.9],['trunk','m-rt',1.5],['motorway','m-rm',2.3]].map(([k,c,w])=>gj(MAPDATA.roads[k],{pane:'roads',interactive:false,style:{className:c,weight:w,fill:false}})));
  (MAPDATA.shields||[]).forEach(r=>MAPL.roads.addLayer(lbl(r.x,r.y,'ml-r ml-r-'+r.kind,esc(r.ref))));
  L.control.attribution({prefix:false,position:'bottomright'}).addAttribution('Дороги: © участники <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>').addTo(MAP);
  gj(MAPDATA.borders.inner,{pane:'borders',interactive:false,style:{className:'m-border',weight:1.3,fill:false}}).addTo(MAP);
  gj(MAPDATA.borders.metro,{pane:'borders',interactive:false,style:{className:'m-metro',weight:2,dashArray:'7 4',fill:false}}).addTo(MAP);
  gj(MAPDATA.borders.wall,{pane:'borders',interactive:false,style:{className:'m-wall',weight:2.6,fill:false}}).addTo(MAP);
  const labels=L.layerGroup().addTo(MAP);
  MAPDATA.labels.forEach(l=>labels.addLayer(lbl(l.xy[0],l.xy[1],'ml-d'+(l.big?' big':'')+(l.slug==='dogtown'?' ml-dog':''),esc(l.name))));
  MAPDATA.water_labels.forEach(l=>labels.addLayer(lbl(l.xy[0],l.xy[1],'ml-w s'+l.size,esc(l.name))));
  MAPDATA.zone_labels.forEach(l=>labels.addLayer(lbl(l.xy[0],l.xy[1],'ml-o',esc(l.name))));
  MAPL.places=L.layerGroup();
  for(const k of ['places','roads','grid'])if(MAPLAYERS[k])MAP.addLayer(MAPL[k]);
  const svg=MAP.getPane('dist').querySelector('svg');
  if(svg&&!svg.querySelector('#dogwall'))svg.insertAdjacentHTML('afterbegin','<defs><pattern id="dogwall" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="9" height="9" class="dog-bg"/><rect width="3" height="9" class="dog-hatch"/></pattern></defs>');
  MAP.on('zoomend',setZoomClass);
  MAP.on('zoomend moveend',()=>requestAnimationFrame(declutter));
  MAP.on('click',e=>{if(ADDING)mapAddAt(e.latlng);else if(MEASURE.on)measureAdd(e.latlng.lng,-e.latlng.lat);});
  const hud=document.getElementById('map-hud');
  const hudAt=ll=>{if(!hud)return;const x=ll.lng,y=-ll.lat;hud.textContent=(x<0||y<0||x>MAPDATA.W||y>MAPDATA.H)?'За краем карты':'Квадрат '+square(x,y);};
  MAP.on('mousemove',e=>hudAt(e.latlng));MAP.on('moveend',()=>hudAt(MAP.getCenter()));
  const home=L.latLngBounds(LL(24000,6000),LL(62000,132000));
  if(UI.mapView)MAP.setView(UI.mapView.c,UI.mapView.z);else MAP.fitBounds(home);
  MAP.on('moveend',()=>{UI.mapView={c:MAP.getCenter(),z:MAP.getZoom()};});
  setZoomClass();updateMapTools();refreshPlaces();hudAt(MAP.getCenter());requestAnimationFrame(declutter);
  measureResume();
  if(UI.measureFocus){const p=placeById(UI.measureFocus);UI.measureFocus=null;if(p)focusPlace(p);}
  if(UI.focusPlace){const p=placeById(UI.focusPlace);UI.focusPlace=null;if(p){focusPlace(p);openPlace(p.id);}}
}
function refreshPlaces(){
  if(!MAP||!MAPL.places)return;
  if(MOVING){PENDING_PLACES=true;return;}
  MAPL.places.clearLayers();PMARK={};
  for(const p of placesVisible()){
    if(p.bg&&!MAPLAYERS.bg)continue;
    const n=S.entries.filter(e=>e.place===p.id&&canSee(e)&&isActive(e)).length;
    const cls='pl pl-'+p.type+(p.vis==='мастер'?' pl-hidden':'')+(p.vis==='знают'?' pl-known':'')+(p.bg?' pl-bg':'');
    const m=L.marker(LL(p.x,p.y),{title:p.name,riseOnHover:true,icon:L.divIcon({className:cls,iconSize:[0,0],
      html:`<span class="pl-ico"><svg viewBox="0 0 20 20" aria-hidden="true">${PLACE_GLYPH[p.type]||PLACE_GLYPH.other}</svg>${n?`<b class="pl-n">${n}</b>`:''}</span><span class="pl-name">${esc(p.name)}</span>`})});
    m.on('click',()=>{if(MEASURE.on&&!ADDING&&!MOVING){measureAdd(p.x,p.y,p);return;}if(MOVING===p.id){stopMoving('Перемещение отменено');return;}if(!ADDING&&!MOVING)openPlace(p.id);});
    m.on('dragend',async()=>{const q=m.getLatLng();const it=placeById(p.id);MOVING=null;PENDING_PLACES=false;
      const j=await apiPost('/api/gm/items/places',Object.assign({},it,{x:Math.round(q.lng),y:Math.round(-q.lat)}));
      refreshPlaces();if(j)toast('Место перемещено');});
    MAPL.places.addLayer(m);PMARK[p.id]=m;
  }
  requestAnimationFrame(declutter);
}
function focusPlace(p){MAP.setView(LL(p.x,p.y),Math.max(MAP.getZoom(),-4),{animate:false});if(innerWidth<=760)MAP.panBy([0,Math.round(innerHeight*0.22)],{animate:false});}
function placeLinks(id){const e=S.entries.filter(x=>x.place===id).length,d=(S.dossier||[]).filter(x=>x.last_place===id).length;const t=[e?`записей: ${e}`:'',d?`карточек досье: ${d}`:''].filter(Boolean).join(', ');return t?`. Привязано ${t}, привязка пропадёт`:'';}
function mapAddAt(latlng){ADDING=false;updateMapTools();openItemForm('places',null,{x:Math.round(latlng.lng),y:Math.round(-latlng.lat)});}
function openPlace(id,keep){
  const p=placesVisible().find(x=>x.id===id);if(!p){closePanel();return;}
  curKey='m:'+id;
  const d=districtAt(p.x,p.y);
  const es=S.entries.filter(e=>e.place===p.id&&canSee(e)).sort((a,b)=>a.from<b.from?1:-1);
  let acts=`<button type="button" class="btn" data-act="add-at" data-id="${p.id}">Добавить запись здесь</button><button type="button" class="btn" data-act="measure-from" data-id="${p.id}">Расстояние отсюда</button>`;
  if(V==='gm')acts=`<button type="button" class="btn" data-act="edit-item" data-kind="places" data-id="${p.id}">Изменить</button><button type="button" class="btn" data-act="map-move" data-id="${p.id}">Переместить</button>`+acts+`<button type="button" class="btn plain" data-act="del-item" data-kind="places" data-id="${p.id}">Удалить</button>`;
  showPanel(`<p class="kind"><span class="pl-dot pl-${p.type}"></span>${PLACE_TYPES[p.type]||'Место'}${p.bg?'<span class="tag">фон</span>':''}${V==='gm'?`<span class="tag">${PVIS[p.vis]||''}</span>`:''}</p><h2>${esc(p.name)}</h2>
  <dl><dt>Район</dt><dd>${DNAMES[d]||'—'}</dd><dt>Квадрат</dt><dd>${square(p.x,p.y)}</dd>${V==='gm'&&p.vis==='знают'?`<dt>Знают</dt><dd>${esc(joinNames((p.known||[]).map(c=>CN[c]||c)))}</dd>`:''}</dl>
  ${p.note?`<p class="prose">${rich(p.note)}</p>`:''}${V==='gm'&&p.gm_note?`<h3>Заметка мастера</h3><p class="prose" style="margin-top:0">${rich(p.gm_note)}</p>`:''}
  ${(()=>{const seen=dossierVisible().filter(c=>c.last_place===p.id);return seen.length?`<h3>Видели здесь</h3>`+seen.map(c=>`<button type="button" class="row" data-open="n:${c.id}"><span class="rt">${esc(c.name)}</span><span class="rs">${c.last_date?fDate(c.last_date):''}</span></button>`).join(''):'';})()}
  <h3>Записи календаря</h3>${es.length?es.map(e=>entryRow(e,fFull(e.from))).join(''):'<p class="muted" style="margin:0">Записей с этим местом пока нет.</p>'}
  <div class="acts">${acts}</div>`,keep);
}
function openDistrict(slug,keep){
  curKey='d:'+slug;
  const dn=(S.dnotes||[]).find(d=>d.id===slug)||{};
  const pl=placesVisible().filter(p=>districtAt(p.x,p.y)===slug).sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  showPanel(`<p class="kind">Район</p><h2>${DNAMES[slug]}</h2>${dn.text?`<p class="prose" style="margin-top:0">${rich(dn.text)}</p>`:'<p class="muted">Описания пока нет.</p>'}
  ${V==='gm'&&dn.gm_text?`<h3>Заметка мастера</h3><p class="prose" style="margin-top:0">${rich(dn.gm_text)}</p>`:''}
  <h3>Места</h3>${pl.length?pl.map(p=>`<button type="button" class="row" data-act="open-place" data-id="${p.id}"><span class="pl-dot pl-${p.type}"></span><span class="rt">${esc(p.name)}</span><span class="rs">${PLACE_TYPES[p.type]||''}</span></button>`).join(''):'<p class="muted" style="margin:0">Отмеченных мест нет.</p>'}
  ${V==='gm'?`<div class="acts"><button type="button" class="btn" data-act="edit-district" data-id="${slug}">Изменить описание</button></div>`:''}`,keep);
}
function openDistrictForm(slug){
  const dn=(S.dnotes||[]).find(d=>d.id===slug)||{};curKey=null;
  showPanel(`<p class="kind">Район</p><h2>${DNAMES[slug]}</h2><form id="district-form" data-slug="${slug}" novalidate>
  <label class="field">Описание для игроков<textarea name="text" rows="5" maxlength="3000">${esc(dn.text||'')}</textarea></label>
  <label class="field">Заметка мастера<textarea name="gm_text" rows="4" maxlength="3000">${esc(dn.gm_text||'')}</textarea><span class="sub">Игроки её не видят.</span></label>
  <p class="err" id="form-err" role="alert"></p><div class="acts"><button type="submit" class="btn primary">Сохранить</button><button type="button" class="btn" data-act="close">Отмена</button></div></form>`);
}
