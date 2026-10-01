/* ===== Геометрия карты и маршруты =====
   Чистые функции без обращения к странице: их проверяют тесты на Node (tests/js/geo.test.js).
   Координаты в метрах, как в static/map/map.json. Дороги: три класса (магистрали, трассы, основные).
   Из линий строится граф: близкие вершины склеиваются, висячие концы соединяются «мостами» с ближайшей
   соседней сетью. Маршрут ищется по времени (алгоритм Дейкстры) отдельно для каждого вида транспорта. */
const GEO_SNAP=30;          // вершины ближе этого (м) считаются одним узлом
const GEO_BRIDGE=300;       // висячий конец дороги соединяется с чужой сетью, если она ближе этого (м)
const GEO_CELL=1000;        // размер ячейки пространственного индекса (м)
const GEO_MAX_ACCESS=12000; // дальше этого от дорог маршрут по дорогам не строится (м)
const GEO_CLASSES=['motorway','trunk','primary'];

const geoDist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);

/* Точка внутри полигона или мультиполигона GeoJSON (с учётом дыр). */
function pip(x,y,g){
  const polys=g.type==='Polygon'?[g.coordinates]:g.coordinates;
  for(const poly of polys){let inside=false;for(const ring of poly){for(let i=0,j=ring.length-1;i<ring.length;j=i++){const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1];if(((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi)+xi))inside=!inside;}}if(inside)return true;}
  return false;
}

/* Ближайшая точка отрезка a-b к точке (x,y): {t, px, py, d}, t от 0 до 1. */
function geoProject(x,y,ax,ay,bx,by){
  const dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy;
  let t=l2?((x-ax)*dx+(y-ay)*dy)/l2:0;t=Math.max(0,Math.min(1,t));
  const px=ax+t*dx,py=ay+t*dy;
  return {t,px,py,d:Math.hypot(x-px,y-py)};
}

/* Граф дорог. roads: {motorway:{coordinates:[[[x,y],...],...]}, trunk:..., primary:...}. */
function buildRoadGraph(roads){
  const xs=[],ys=[],key=new Map(),ea=[],eb=[],elen=[],ecls=[];
  const node=(x,y)=>{const k=Math.round(x/GEO_SNAP)+','+Math.round(y/GEO_SNAP);let i=key.get(k);if(i===undefined){i=xs.length;key.set(k,i);xs.push(x);ys.push(y);}return i;};
  GEO_CLASSES.forEach((cls,c)=>{
    const lines=(roads[cls]&&roads[cls].coordinates)||[];
    for(const line of lines)for(let i=0;i+1<line.length;i++){
      const a=node(line[i][0],line[i][1]),b=node(line[i+1][0],line[i+1][1]);
      if(a!==b){ea.push(a);eb.push(b);elen.push(Math.hypot(xs[a]-xs[b],ys[a]-ys[b]));ecls.push(c);}
    }
  });
  const n=xs.length,adj=Array.from({length:n},()=>[]);
  for(let e=0;e<ea.length;e++){adj[ea[e]].push(e);adj[eb[e]].push(e);}
  // компоненты связности (объединение множеств)
  const parent=Array.from({length:n},(_,i)=>i);
  const find=a=>{while(parent[a]!==a){parent[a]=parent[parent[a]];a=parent[a];}return a;};
  for(let e=0;e<ea.length;e++)parent[find(ea[e])]=find(eb[e]);
  // пространственный индекс узлов
  const cells=new Map(),cellOf=(x,y)=>Math.floor(x/GEO_CELL)+','+Math.floor(y/GEO_CELL);
  for(let i=0;i<n;i++){const k=cellOf(xs[i],ys[i]);(cells.get(k)||cells.set(k,[]).get(k)).push(i);}
  // «мосты»: висячие концы (степень 1) к ближайшему узлу другой компоненты
  const r=Math.ceil(GEO_BRIDGE/GEO_CELL);
  for(let i=0;i<n;i++){
    if(adj[i].length!==1)continue;
    const cx=Math.floor(xs[i]/GEO_CELL),cy=Math.floor(ys[i]/GEO_CELL);let best=-1,bd=GEO_BRIDGE;
    for(let dx=-r;dx<=r;dx++)for(let dy=-r;dy<=r;dy++)for(const j of cells.get((cx+dx)+','+(cy+dy))||[]){
      if(find(j)===find(i))continue;
      const d=Math.hypot(xs[i]-xs[j],ys[i]-ys[j]);if(d<bd){bd=d;best=j;}
    }
    if(best>=0){const e=ea.length;ea.push(i);eb.push(best);elen.push(bd);ecls.push(ecls[adj[i][0]]);adj[i].push(e);adj[best].push(e);parent[find(i)]=find(best);}
  }
  // индекс рёбер по ячейкам для поиска ближайшей дороги к произвольной точке
  const ecell=new Map();
  for(let e=0;e<ea.length;e++){
    const x0=Math.min(xs[ea[e]],xs[eb[e]]),x1=Math.max(xs[ea[e]],xs[eb[e]]),y0=Math.min(ys[ea[e]],ys[eb[e]]),y1=Math.max(ys[ea[e]],ys[eb[e]]);
    for(let cx=Math.floor(x0/GEO_CELL);cx<=Math.floor(x1/GEO_CELL);cx++)for(let cy=Math.floor(y0/GEO_CELL);cy<=Math.floor(y1/GEO_CELL);cy++){
      const k=cx+','+cy;(ecell.get(k)||ecell.set(k,[]).get(k)).push(e);
    }
  }
  return {xs,ys,ea,eb,elen,ecls,adj,ecell,n};
}

/* Ближайшая к (x,y) точка дорожной сети: {e, t, px, py, d} или null, если дороги дальше maxD. */
function nearestRoad(g,x,y,maxD=GEO_MAX_ACCESS){
  const cx=Math.floor(x/GEO_CELL),cy=Math.floor(y/GEO_CELL),maxR=Math.ceil(maxD/GEO_CELL);
  let best=null;
  for(let ring=0;ring<=maxR;ring++){
    for(let dx=-ring;dx<=ring;dx++)for(let dy=-ring;dy<=ring;dy++){
      if(Math.max(Math.abs(dx),Math.abs(dy))!==ring)continue;
      for(const e of g.ecell.get((cx+dx)+','+(cy+dy))||[]){
        const p=geoProject(x,y,g.xs[g.ea[e]],g.ys[g.ea[e]],g.xs[g.eb[e]],g.ys[g.eb[e]]);
        if(!best||p.d<best.d)best={e,t:p.t,px:p.px,py:p.py,d:p.d};
      }
    }
    // дальше кольца не найдут ничего ближе уже найденного
    if(best&&best.d<=ring*GEO_CELL)break;
  }
  return best&&best.d<=maxD?best:null;
}

/* Двоичная куча для алгоритма Дейкстры. */
class GeoHeap{
  constructor(){this.k=[];this.v=[];}
  get size(){return this.k.length;}
  push(key,val){const k=this.k,v=this.v;let i=k.length;k.push(key);v.push(val);while(i>0){const p=(i-1)>>1;if(k[p]<=key)break;k[i]=k[p];v[i]=v[p];i=p;}k[i]=key;v[i]=val;}
  pop(){const k=this.k,v=this.v,top=[k[0],v[0]],lk=k.pop(),lv=v.pop(),n=k.length;if(n){let i=0;for(;;){let c=2*i+1;if(c>=n)break;if(c+1<n&&k[c+1]<k[c])c++;if(k[c]>=lk)break;k[i]=k[c];v[i]=v[c];i=c;}k[i]=lk;v[i]=lv;}return top;}
}

const mpm=kmh=>kmh*1000/60; // километры в час в метры в минуту

/* Маршрут по дорогам между точками A и B для одного вида транспорта.
   Возвращает {ok, minutes, meters, roadMeters:[м по магистралям, трассам, основным], offMeters, path:[[x,y],...], fallback}.
   Если дороги недоступны (далеко или нет связи), участок считается по прямой на скорости вне дорог (fallback:true). */
function routeOnRoads(g,A,B,profile){
  const off=mpm(profile.off),speed=GEO_CLASSES.map(c=>mpm(profile[c]||0));
  const straight=()=>{const d=geoDist(A,B);return {ok:true,fallback:true,minutes:d/off,meters:d,roadMeters:[0,0,0],offMeters:d,path:[A,B]};};
  if(!g||!g.n)return straight();
  const pa=nearestRoad(g,A[0],A[1]),pb=nearestRoad(g,B[0],B[1]);
  if(!pa||!pb)return straight();
  const N=g.n,VA=N,VB=N+1;
  // виртуальные узлы на ближайших рёбрах
  const extra=new Map();
  const link=(u,v,len,cls)=>{(extra.get(u)||extra.set(u,[]).get(u)).push([v,len,cls]);(extra.get(v)||extra.set(v,[]).get(v)).push([u,len,cls]);};
  const attach=(vn,p)=>{const e=p.e,l=g.elen[e],c=g.ecls[e];link(vn,g.ea[e],p.t*l,c);link(vn,g.eb[e],(1-p.t)*l,c);};
  attach(VA,pa);attach(VB,pb);
  if(pa.e===pb.e)link(VA,VB,Math.abs(pa.t-pb.t)*g.elen[pa.e],g.ecls[pa.e]);
  const time=new Float64Array(N+2).fill(Infinity),prev=new Int32Array(N+2).fill(-1),pLen=new Float64Array(N+2),pCls=new Int8Array(N+2);
  const heap=new GeoHeap();time[VA]=0;heap.push(0,VA);
  const relax=(u,v,len,cls,t0)=>{const s=speed[cls];if(!(s>0))return;const t=t0+len/s;if(t<time[v]){time[v]=t;prev[v]=u;pLen[v]=len;pCls[v]=cls;heap.push(t,v);}};
  while(heap.size){
    const [t0,u]=heap.pop();if(t0>time[u])continue;if(u===VB)break;
    if(u<N)for(const e of g.adj[u]){const v=g.ea[e]===u?g.eb[e]:g.ea[e];relax(u,v,g.elen[e],g.ecls[e],t0);}
    for(const [v,len,cls] of extra.get(u)||[])relax(u,v,len,cls,t0);
  }
  if(!(time[VB]<Infinity))return straight();
  // восстановление пути
  const nodes=[];let cur=VB;const roadMeters=[0,0,0];
  while(cur!==-1){nodes.push(cur);if(prev[cur]!==-1)roadMeters[pCls[cur]]+=pLen[cur];cur=prev[cur];}
  nodes.reverse();
  const pos=i=>i===VA?[pa.px,pa.py]:i===VB?[pb.px,pb.py]:[g.xs[i],g.ys[i]];
  const accessA=pa.d,accessB=pb.d,road=roadMeters[0]+roadMeters[1]+roadMeters[2];
  return {ok:true,fallback:false,minutes:time[VB]+(accessA+accessB)/off,meters:road+accessA+accessB,roadMeters,offMeters:accessA+accessB,
    path:[A,...nodes.map(pos),B]};
}

/* Маршрут по прямой. */
function routeStraight(A,B,profile){const d=geoDist(A,B);return {ok:true,fallback:false,minutes:d/mpm(profile.off),meters:d,roadMeters:[0,0,0],offMeters:d,path:[A,B]};}

/* Поездка через все точки pts=[[x,y],...] для вида транспорта profile.
   opts: {graph, straight:true для линейки без дорог, dogtown: геометрия района для штрафа за стену}.
   Возвращает суммарные минуты (с задержкой профиля и стеной), метры, разбивку и ломаную для рисования. */
function planTrip(pts,profile,opts={}){
  const out={minutes:0,meters:0,roadMeters:[0,0,0],offMeters:0,path:[],legs:[],fallback:false,walls:0};
  if(pts.length<2)return out;
  const useRoads=!opts.straight&&profile.kind!=='straight';
  for(let i=0;i+1<pts.length;i++){
    const A=pts[i],B=pts[i+1];
    const leg=useRoads?routeOnRoads(opts.graph,A,B,profile):routeStraight(A,B,profile);
    let minutes=leg.minutes;
    if(useRoads&&profile.wall>0&&opts.dogtown&&pip(A[0],A[1],opts.dogtown)!==pip(B[0],B[1],opts.dogtown)){minutes+=profile.wall;out.walls++;}
    out.legs.push({meters:leg.meters,minutes,fallback:leg.fallback});
    out.minutes+=minutes;out.meters+=leg.meters;out.offMeters+=leg.offMeters;
    for(let c=0;c<3;c++)out.roadMeters[c]+=leg.roadMeters[c];
    if(leg.fallback)out.fallback=true;
    out.path.push(...(out.path.length?leg.path.slice(1):leg.path));
  }
  if(out.meters>0)out.minutes+=profile.delay||0;
  return out;
}

/* ===== Форматирование ===== */
function formatKm(m){
  if(m<950)return Math.round(m/10)*10+' м';
  const km=m/1000;return (km<10?km.toFixed(1):Math.round(km).toString()).replace('.',',')+' км';
}
function formatMinutes(min){
  if(!isFinite(min))return '—';
  if(min<1)return 'меньше минуты';
  let m=Math.round(min);
  if(m>=30)m=Math.round(m/5)*5;           // для долгих поездок точность до пяти минут: это оценка
  const d=Math.floor(m/1440),h=Math.floor((m%1440)/60),mm=m%60;
  return [d?d+' д':'',h?h+' ч':'',mm?mm+' мин':''].filter(Boolean).join(' ')||'0 мин';
}

if(typeof module!=='undefined'&&module.exports){
  module.exports={GEO_SNAP,GEO_BRIDGE,GEO_MAX_ACCESS,geoDist,pip,geoProject,buildRoadGraph,nearestRoad,routeOnRoads,routeStraight,planTrip,formatKm,formatMinutes};
}
