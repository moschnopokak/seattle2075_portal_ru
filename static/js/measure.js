/* ===== Линейка и время в пути =====
   Точки ставятся щелчком по карте или по метке места. Считается расстояние и время для каждого вида транспорта.
   Расчёты в geo.js, здесь только состояние, панель и рисование поверх карты. Виды транспорта задаёт мастер (S.travel). */
const MEASURE={on:false,pts:[],mode:'roads',sel:null,graph:null,layer:null,res:{},direct:0};
const MEASURE_MAX=12;
const travelProfiles=()=>(S.travel||[]).filter(t=>V==='gm'||t.vis!=='мастер');
function measureGraph(){if(!MEASURE.graph&&MAPDATA)MEASURE.graph=buildRoadGraph(MAPDATA.roads);return MEASURE.graph;}
function measureLabel(p){
  if(p.name)return p.name;
  const d=districtAt(p.x,p.y);
  return 'Точка, квадрат '+square(p.x,p.y)+(d&&d!=='outside'?', '+DNAMES[d]:'');
}
function measureStart(){
  MEASURE.on=true;
  const el=document.getElementById('leaflet');if(el)el.classList.add('measuring');
  updateMapTools();measureRender();
}
function measureStop(clear){
  MEASURE.on=false;if(clear)MEASURE.pts=[];
  const el=document.getElementById('leaflet');if(el)el.classList.remove('measuring');
  updateMapTools();measureRender();
}
function measureAdd(x,y,place){
  if(MEASURE.pts.length>=MEASURE_MAX){toast('Точек не больше '+MEASURE_MAX);return;}
  MEASURE.pts.push({x:Math.round(x),y:Math.round(y),name:place?place.name:'',place:place?place.id:''});
  measureRender();
}
function measureStartFrom(id){
  const p=placeById(id);if(!p)return;
  closePanel();
  MEASURE.pts=[{x:p.x,y:p.y,name:p.name,place:p.id}];MEASURE.on=true;
  if(UI.section==='map'&&MAP&&MAP.getContainer()===document.getElementById('leaflet')){measureStart();focusPlace(p);}
  else{UI.section='map';UI.measureFocus=id;render();}
}
function measureCompute(){
  const profs=travelProfiles(),pts=MEASURE.pts.map(p=>[p.x,p.y]);
  MEASURE.res={};MEASURE.direct=0;
  for(let i=0;i+1<pts.length;i++)MEASURE.direct+=geoDist(pts[i],pts[i+1]);
  if(pts.length<2)return;
  const roads=MEASURE.mode==='roads'&&profs.some(t=>t.kind!=='straight');
  const opts={graph:roads?measureGraph():null,straight:MEASURE.mode==='straight',dogtown:MAPDATA&&MAPDATA.districts.dogtown};
  for(const t of profs)MEASURE.res[t.id]=planTrip(pts,t,opts);
  if(!profs.some(t=>t.id===MEASURE.sel)){
    const byRoad=profs.filter(t=>t.kind!=='straight');
    MEASURE.sel=(byRoad.length?byRoad[byRoad.length-1]:profs[0]||{}).id||null;
  }
}
function measureDraw(){
  if(!MAP)return;
  if(MEASURE.layer){try{MAP.removeLayer(MEASURE.layer);}catch(e){}MEASURE.layer=null;}
  if(!MEASURE.on||!MEASURE.pts.length)return;
  const grp=L.layerGroup().addTo(MAP);MEASURE.layer=grp;
  const sel=MEASURE.res[MEASURE.sel];
  const path=sel&&sel.path.length>1?sel.path:MEASURE.pts.map(p=>[p.x,p.y]);
  const prof=travelProfiles().find(t=>t.id===MEASURE.sel);
  const straightStyle=MEASURE.mode==='straight'||(prof&&prof.kind==='straight')||(sel&&sel.fallback);   // пунктир: без дорог
  if(path.length>1)L.polyline(path.map(p=>LL(p[0],p[1])),{className:'m-route'+(straightStyle?' m-route-straight':''),weight:4,interactive:false}).addTo(grp);
  MEASURE.pts.forEach((p,i)=>{
    const m=L.marker(LL(p.x,p.y),{draggable:true,keyboard:false,title:measureLabel(p),zIndexOffset:1000,icon:L.divIcon({className:'mm',html:`<span>${i+1}</span>`,iconSize:[24,24]})});
    m.on('dragend',()=>{const q=m.getLatLng();MEASURE.pts[i]={x:Math.round(q.lng),y:Math.round(-q.lat),name:'',place:''};measureRender();});
    grp.addLayer(m);
  });
}
function measureRender(){
  measureCompute();measureDraw();
  const box=document.getElementById('map-measure');if(!box)return;
  box.hidden=!MEASURE.on;if(!MEASURE.on){box.innerHTML='';return;}
  const profs=travelProfiles(),n=MEASURE.pts.length,sel=MEASURE.res[MEASURE.sel];
  let h=`<div class="mm-head"><b>Линейка</b><button type="button" class="btn plain" data-act="measure-close">Закрыть</button></div>
  <div class="seg" role="group" aria-label="Способ расчёта"><button type="button" data-act="measure-mode" data-v="roads" aria-pressed="${MEASURE.mode==='roads'}">По дорогам</button><button type="button" data-act="measure-mode" data-v="straight" aria-pressed="${MEASURE.mode==='straight'}">По прямой</button></div>`;
  if(!n)h+=`<p class="mm-hint">Щёлкните по карте или по метке места, чтобы поставить первую точку. Точки можно перетаскивать.</p>`;
  else{
    h+=`<ol class="mm-pts">${MEASURE.pts.map((p,i)=>`<li><span class="mm-n">${i+1}</span><span class="mm-name">${esc(measureLabel(p))}</span><button type="button" class="btn plain mm-x" data-act="measure-del" data-i="${i}" aria-label="Убрать точку ${i+1}">×</button></li>`).join('')}</ol>`;
    if(n===1)h+=`<p class="mm-hint">Поставьте вторую точку.</p>`;
  }
  if(n>=2){
    const rows=profs.map(t=>{
      const r=MEASURE.res[t.id];if(!r)return '';
      const flags=[r.walls?`пропускной пункт Догтауна +${formatMinutes(t.wall*r.walls)}`:'',r.fallback?'дорога далеко, часть пути по прямой':''].filter(Boolean);
      return `<button type="button" class="mm-row" data-act="measure-sel" data-id="${esc(t.id)}" aria-pressed="${t.id===MEASURE.sel}"><span class="mm-t">${esc(t.name)}</span><span class="mm-d">${formatKm(r.meters)}</span><b class="mm-m">${formatMinutes(r.minutes)}</b>${flags.length?`<small>${esc(flags.join('; '))}</small>`:''}</button>`;
    }).join('');
    let sum=`<p class="mm-sum"><b>${formatKm(MEASURE.direct)}</b> по прямой`;
    if(MEASURE.mode==='roads'&&sel&&!sel.fallback&&sel.roadMeters.some(x=>x>0)){
      const [m,t,p]=sel.roadMeters,parts=[m?`магистрали ${formatKm(m)}`:'',t?`трассы ${formatKm(t)}`:'',p?`основные ${formatKm(p)}`:'',sel.offMeters>=50?`вне дорог ${formatKm(sel.offMeters)}`:''].filter(Boolean);
      sum+=`, по дорогам для выбранного вида: <b>${formatKm(sel.meters)}</b> (${parts.join(', ')})`;
    }
    sum+='.</p>';
    h+=sum+(rows?`<div class="mm-times" role="group" aria-label="Время в пути по видам транспорта">${rows}</div>`:`<p class="mm-hint">Мастер ещё не задал виды транспорта.</p>`);
    if(n>2&&sel)h+=`<details class="mm-legs"><summary>По участкам</summary>${sel.legs.map((l,i)=>`<div>${i+1} → ${i+2}: ${formatKm(l.meters)}, ${formatMinutes(l.minutes)}</div>`).join('')}</details>`;
    h+=`<p class="mm-note">Оценка по картам дорог кампании: без пробок, погоды и происшествий. Нажмите на вид транспорта, чтобы увидеть его маршрут на карте.</p>`;
  }
  h+=`<div class="acts mm-acts"><button type="button" class="btn small" data-act="measure-undo" ${n?'':'disabled'}>Убрать последнюю</button><button type="button" class="btn small" data-act="measure-reverse" ${n>1?'':'disabled'}>Поменять местами</button><button type="button" class="btn small" data-act="measure-clear" ${n?'':'disabled'}>Очистить</button></div>`;
  box.innerHTML=h;
}
function measureAct(a,b){
  const v=b.dataset.v,id=b.dataset.id;
  if(a==='map-measure'){MEASURE.on?measureStop(false):measureStart();return;}
  if(a==='measure-from'){measureStartFrom(id);return;}
  if(a==='measure-close')measureStop(true);
  else if(a==='measure-mode'){MEASURE.mode=v==='straight'?'straight':'roads';measureRender();}
  else if(a==='measure-sel'){MEASURE.sel=id;measureRender();}
  else if(a==='measure-del'){MEASURE.pts.splice(+b.dataset.i,1);measureRender();}
  else if(a==='measure-undo'){MEASURE.pts.pop();measureRender();}
  else if(a==='measure-reverse'){MEASURE.pts.reverse();measureRender();}
  else if(a==='measure-clear'){MEASURE.pts=[];measureRender();}
}
/* После перерисовки карты (смена раздела, обновление данных) возвращает линейку на место. */
function measureResume(){
  const el=document.getElementById('leaflet');
  if(el&&MEASURE.on)el.classList.add('measuring');
  measureRender();
}
