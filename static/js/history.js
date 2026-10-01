/* ===== Корзина и история изменений (только мастер) =====
   Списки приходят отдельными запросами (в общее состояние они не входят). Всё, что показывается, экранируется. */
const H_KIND={money:'запись о деньгах',factions:'фракцию',standing:'репутацию',contacts:'контакт',entry:'запись',dossier:'карточку досье',places:'место',windows:'этап',rhythm:'регулярное событие',clocks:'скрытый таймер',plan:'событие плана',past:'событие хроники',handouts:'раздатку',travel:'вид транспорта',dnote:'описание района',time:'время в игре'};
const H_KIND_NOM={money:'Запись о деньгах',factions:'Фракция',standing:'Репутация',contacts:'Контакт',entry:'Запись',dossier:'Карточка досье',places:'Место',windows:'Этап',rhythm:'Регулярное событие',clocks:'Скрытый таймер',plan:'Событие плана',past:'Событие хроники',handouts:'Раздатка',travel:'Вид транспорта',dnote:'Описание района',time:'Время'};
const H_VERB={create:'добавил(а)',edit:'изменил(а)',delete:'удалил(а)',restore:'восстановил(а)',revert:'вернул(а) прежнее:',upload:'загрузил(а) файл:',
  'file-delete':'убрал(а) картинку:',time:'изменил(а)',played:'перенёс(ла) в хронику',
  'act:ans':'ответил(а) на приглашение:','act:join':'попросился(лась) в запись:','act:kick':'убрал(а) участника из записи:',
  'act:approve':'подтвердил(а) развитие:','act:reject':'отклонил(а) развитие:','act:outcome':'отметил(а) итог записи:'};
const H_FIELD={char:'Персонаж',delta:'Сумма (+ доход, − расход)',faction:'Фракция',value:'Отношение',connection:'Связи',loyalty:'Лояльность',services:'Чем помогает',card:'Карточка досье',title:'Название',name:'Название',from:'Начало',to:'Окончание',tod:'Время суток',who:'Участники',open:'Можно попроситься',where:'Где',cond:'Условия',goal:'Цель',
  vis:'Видимость',place:'Место',note:'Описание',gm_note:'Заметка мастера',answers:'Ответы',status:'Статус',stars:'Звёзды',talk:'Обсуждение',type:'Тип',role:'Кто это',
  stance:'Отношение',org:'Организация',alias:'Позывной',known:'Кто знает',met:'Знакомы лично',facts:'Сведения',last_date:'Последняя встреча',last_place:'Где виделись',
  last_note:'О встрече',session:'Сессия',cover:'Что видят игроки',x:'Положение на карте (X)',y:'Положение на карте (Y)',text:'Описание для игроков',gm_text:'Заметка мастера',inter:'Промежуточная арка',
  gm:'Название для мастера',wd:'Дни недели',monthDay:'Число месяца',when:'Срок',date:'Дата',quiet:'Свободное время до',effect:'Действует с',kind:'Как едет',
  motorway:'Магистрали, км/ч',trunk:'Трассы, км/ч',primary:'Основные дороги, км/ч',off:'Вне дорог, км/ч',delay:'Сборы перед выездом, мин',wall:'Пропускной пункт, мин'};
const H_REVERTABLE=a=>['create','edit','delete','time'].includes(a);
function getJson(path){
  return fetch(path,{headers:authHeaders(),credentials:'same-origin'}).then(r=>{if(r.status===401){showLogin();return null;}return r.ok?r.json():null;}).catch(()=>null);
}
function hTitle(h){
  if(h.kind==='time')return '';
  if(h.kind==='dnote')return ' «'+esc(DNAMES[h.item_id]||h.item_id)+'»';
  return h.title?' «'+esc(h.title)+'»':'';
}
function hSentence(h){
  const verb=H_VERB[h.action]||esc(h.action),kind=H_KIND[h.kind]||esc(h.kind);
  const noKind=['revert','upload','file-delete','played','act:ans','act:join','act:kick','act:approve','act:reject','act:outcome'].includes(h.action);
  return `<b>${esc(h.actor)}</b> ${verb} ${noKind?'':kind}${hTitle(h)}`.replace(/\s+/g,' ');
}
/* Значение поля для показа: списки номеров персонажей превращаются в имена, пустой список в «пусто». */
function hVal(text){
  if(typeof text!=='string'||text[0]!=='[')return text;
  try{const a=JSON.parse(text);if(Array.isArray(a)&&a.every(x=>typeof x==='string'))return a.map(c=>CN[c]||c).join(', ');}catch(e){}
  return text;
}
function hChanges(h){
  if(!h.changes||!h.changes.length)return '';
  return `<details class="hist-ch"><summary>Что изменилось (${h.changes.length})</summary><table>${h.changes.map(c=>`<tr><th>${esc(H_FIELD[c.field]||c.field)}</th><td class="was">${esc(hVal(c.before))||'<i>пусто</i>'}</td><td class="now">${esc(hVal(c.after))||'<i>пусто</i>'}</td></tr>`).join('')}</table></details>`;
}
function histRow(h){
  const btn=H_REVERTABLE(h.action)?`<button type="button" class="btn small" data-act="hist-revert" data-id="${h.id}">${h.action==='delete'?'Вернуть из корзины':h.action==='create'?'Отменить добавление':'Вернуть как было'}</button>`:'';
  return `<div class="hist-row"><div class="hist-top"><span class="hist-time">${fTs(h.ts)}</span> ${hSentence(h)}${h.role==='player'?'<span class="tag">игрок</span>':''}</div>${hChanges(h)}${btn?`<div class="acts">${btn}</div>`:''}</div>`;
}
function trashRow(t){
  return `<div class="hist-row"><div class="hist-top"><b>${esc(H_KIND_NOM[t.kind]||t.kind)}</b> «${esc(t.title)}» <span class="muted small">удалил(а) ${esc(t.by)}, ${fTs(t.ts)}; хранится ещё ${t.days_left} ${plural(t.days_left,'день','дня','дней')}</span></div>
  <div class="acts"><button type="button" class="btn small primary" data-act="trash-restore" data-id="${t.id}">Восстановить</button><button type="button" class="btn small plain" data-act="trash-purge" data-id="${t.id}">Удалить навсегда</button></div></div>`;
}
function trashInner(){
  const list=UI.trashList;
  if(list==null)return '<p class="muted">Загружаю…</p>';
  return list.length?list.map(trashRow).join('')+`<div class="acts"><button type="button" class="btn small plain" data-act="trash-empty">Очистить корзину</button></div>`:'<p class="muted">Корзина пуста.</p>';
}
function historyInner(){
  const list=UI.hist;
  if(list==null)return '<p class="muted">Загружаю…</p>';
  return (list.length?list.map(histRow).join(''):'<p class="muted">Ничего не найдено.</p>')+(UI.histMore?`<div class="acts"><button type="button" class="btn small" data-act="hist-more">Показать ещё</button></div>`:'');
}
function gmExtrasHTML(){
  return `<section id="gm-trash"><div class="sec-head"><h2>Корзина${S.trash?` (${S.trash})`:''}</h2></div><p class="note">Удалённые записи, карточки, места, раздатки и другое хранятся ${UI.trashDays||30} дней, потом удаляются окончательно. Картинки и файлы удалённого закрыты: по прежним ссылкам они не открываются.</p><div id="trash-list">${trashInner()}</div></section>
  <section id="gm-history"><div class="sec-head"><h2>История изменений</h2></div><p class="note">Кто и что менял на портале, включая действия игроков. У правок можно посмотреть, что именно изменилось, и вернуть как было.</p>
  <label class="field"><span class="sr-only">Поиск по названию или имени</span><input id="hist-q" type="search" maxlength="60" placeholder="Поиск по названию или имени" value="${esc(UI.histQ||'')}"></label><div id="hist-list">${historyInner()}</div></section>`;
}
function histQuery(extra){
  const q=new URLSearchParams({limit:'40'});
  if(UI.histQ)q.set('q',UI.histQ);
  for(const [k,v] of Object.entries(extra||{}))q.set(k,v);
  return '/api/gm/history?'+q.toString();
}
function patchExtras(){
  const t=document.getElementById('trash-list'),h=document.getElementById('hist-list');
  if(t)t.innerHTML=trashInner();
  if(h)h.innerHTML=historyInner();
}
async function gmLoadExtras(force){
  if(V!=='gm'||UI.section!=='gm'||!S.me.gm)return;
  if(!force&&UI.extrasVer===S.version)return;
  UI.extrasVer=S.version;
  const [t,h]=await Promise.all([getJson('/api/gm/trash'),getJson(histQuery())]);
  if(t){UI.trashList=t.items;UI.trashDays=t.days;}
  if(h){UI.hist=h.items;UI.histMore=h.items.length>=40;}
  if(UI.section==='gm')patchExtras();
}
async function histMore(){
  const last=(UI.hist||[]).slice(-1)[0];if(!last)return;
  const h=await getJson(histQuery({before:last.id}));
  if(h){UI.hist=UI.hist.concat(h.items);UI.histMore=h.items.length>=40;patchExtras();}
}
let histTimer=null;
document.addEventListener('input',ev=>{
  if(ev.target.id!=='hist-q')return;
  clearTimeout(histTimer);
  histTimer=setTimeout(()=>{UI.histQ=ev.target.value.trim();gmLoadExtras(true);},350);
});
async function openItemHistory(kind,id){
  const lists={entry:S.entries,dossier:S.dossier,places:S.places,windows:S.windows,rhythm:S.rhythm,clocks:S.clocks,plan:S.plan,past:S.past,handouts:S.handouts,travel:S.travel,money:S.money,factions:S.factions,standing:S.standing,contacts:S.contacts};
  const it=(lists[kind]||[]).find(x=>x.id===id),title=it?(it.title||it.name):id;
  const h=await getJson(`/api/gm/history?kind=${encodeURIComponent(kind)}&item=${encodeURIComponent(id)}&limit=100`);
  if(!h){toast('Не удалось загрузить историю');return;}
  curKey=null;
  showPanel(`<p class="kind">История</p><h2>${esc(title||id)}</h2>${h.items.length?h.items.map(histRow).join(''):'<p class="muted">Об этом в журнале ничего нет.</p>'}<div class="acts"><button type="button" class="btn" data-act="close">Закрыть</button></div>`);
}
async function historyAct(a,b){
  const id=b.dataset.id;
  if(a==='hist-more'){histMore();return;}
  if(a==='item-history'){openItemHistory(b.dataset.kind,id);return;}
  const path={'hist-revert':`/api/gm/history/${id}/revert`,'trash-restore':`/api/gm/trash/${id}/restore`,'trash-purge':`/api/gm/trash/${id}/purge`,'trash-empty':'/api/gm/trash/empty'}[a];
  if(!path)return;
  const j=await apiPost(path,{});
  if(!j)return;
  if(!document.getElementById('overlay').hidden)closePanel();
  UI.extrasVer=-1;render(true);if(j.msg)toast(j.msg);gmLoadExtras(true);
}
