/* ===== Даты кампании =====
   Даты хранятся как ГГГГ-ММ-ДД, дни недели идут по настоящему календарю. */
let CAL_START='2075-07-01', CAL_END='2075-12-31', MONTH_LIST=[];
const MONTHS_GEN=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const MONTHS_NOM=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const WD=['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'];
const WD_GEN=['понедельника','вторника','среды','четверга','пятницы','субботы','воскресенья'];
const WDS=['пн','вт','ср','чт','пт','сб','вс'];
const TOD=['утро','день','вечер','ночь'];
const TODX={'утро':.22,'день':.48,'вечер':.72,'ночь':.9};
const DAY=86400000;

const pad=n=>String(n).padStart(2,'0');
const toT=s=>{const [y,m,d]=s.split('-').map(Number);return Date.UTC(y,m-1,d);};
const fromT=t=>{const d=new Date(t);return d.getUTCFullYear()+'-'+pad(d.getUTCMonth()+1)+'-'+pad(d.getUTCDate());};
const addDays=(s,n)=>fromT(toT(s)+n*DAY);
const wdi=s=>(new Date(toT(s)).getUTCDay()+6)%7;
const yOf=s=>+s.slice(0,4), mOf=s=>+s.slice(5,7), dOf=s=>+s.slice(8,10);
const fDate=s=>dOf(s)+'\u00a0'+MONTHS_GEN[mOf(s)-1]+(yOf(s)!==2075?' '+yOf(s):'');
const fFull=s=>WDS[wdi(s)]+', '+fDate(s);
const range=(a,b)=>{const r=[];for(let c=a;c<=b;c=addDays(c,1))r.push(c);return r;};
const clampDate=s=>s<CAL_START?CAL_START:s>CAL_END?CAL_END:s;
const fSpan=(a,b)=>(!b||a===b)?fFull(a):fFull(a)+' – '+fFull(b);
const fRange=(a,b)=>a===b?fDate(a):mOf(a)===mOf(b)?dOf(a)+'–'+dOf(b)+'\u00a0'+MONTHS_GEN[mOf(a)-1]:fDate(a)+' – '+fDate(b);
const TS_FMT=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
const fTs=ts=>TS_FMT.format(ts);
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const joinNames=a=>a.length<2?a.join(''):a.slice(0,-1).join(', ')+' и '+a[a.length-1];
const plural=(n,one,few,many)=>{const m10=n%10,m100=n%100;return m10===1&&m100!==11?one:m10>=2&&m10<=4&&(m100<12||m100>14)?few:many;};
function buildMonths(){const r=[];let y=yOf(CAL_START),m=mOf(CAL_START);while(y<yOf(CAL_END)||(y===yOf(CAL_END)&&m<=mOf(CAL_END))){r.push(y+'-'+pad(m));m++;if(m>12){m=1;y++;}}return r;}

/* Что видят игроки вперёд: строки для панели мастера и подсказка игроку. h: поле horizon из состояния. */
function horizonCounts(hidden){
  const kinds=[['entries','запись','записи','записей'],['blocks','общее событие','общих события','общих событий'],['rhythm','регулярное событие','регулярных события','регулярных событий'],['handouts','раздатка','раздатки','раздаток']];
  return kinds.filter(([k])=>hidden&&hidden[k]).map(([k,one,few,many])=>`${hidden[k]} ${plural(hidden[k],one,few,many)}`).join(', ');
}
function horizonLine(h,fmt){
  if(!h)return '';
  const when=h.until?fmt(h.until)+(h.window?` («${h.window}»)`:''):'';
  if(h.mode==='window'){
    if(!h.until)return 'Сегодняшний день не входит ни в один этап, поэтому ограничение пока не действует. Добавьте этап на эту дату.';
    const c=horizonCounts(h.hidden);
    return `Игроки видят календарь до ${when}.${c?` Скрыто от них: ${c}.`:' Пока ничего не скрыто.'}`;
  }
  return h.until?`Игроки видят календарь до конца кампании. Если включить ограничение, они будут видеть до ${when}.`:'Игроки видят календарь до конца кампании.';
}

/* Для автотестов в Node. В браузере переменной module нет, и этот блок пропускается. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={pad,toT,fromT,addDays,wdi,yOf,mOf,dOf,fDate,fFull,range,clampDate,fSpan,fRange,cap,esc,joinNames,plural,buildMonths,horizonCounts,horizonLine,
    setCalendar:(start,end)=>{CAL_START=start;CAL_END=end;}};
}
