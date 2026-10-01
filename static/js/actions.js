/* ===== Действия ===== */
const ENTRY_ACTS=['ans','join','kick','star','talk','approve','reject','outcome','del'];
document.addEventListener('click',async ev=>{
  if(ev.target.id==='overlay'){closePanel();return;}
  const nav=ev.target.closest('[data-nav]');
  if(nav){UI.section=nav.dataset.nav;render();window.scrollTo(0,0);return;}
  const op=ev.target.closest('[data-open]');
  if(op){openDetail(op.dataset.open);return;}
  const b=ev.target.closest('[data-act]');if(!b||b.disabled)return;
  const a=b.dataset.act,v=b.dataset.v,id=b.dataset.id;
  if((a==='del'||a==='del-item'||a==='fact-del'||a==='portrait-del'||a==='trash-purge'||a==='trash-empty')&&!b.dataset.armed){
    b.dataset.armed='1';b.dataset.label=b.textContent;b.textContent='Нажмите ещё раз, чтобы удалить'+(a==='del-item'&&b.dataset.kind==='places'?placeLinks(id):'');
    setTimeout(()=>{if(document.body.contains(b)&&b.dataset.armed){delete b.dataset.armed;b.textContent=b.dataset.label;}},4000);
    return;
  }
  if(a==='map-measure'||a.startsWith('measure-')){measureAct(a,b);return;}
  if(a.startsWith('hist-')||a.startsWith('trash-')||a==='item-history'){historyAct(a,b);return;}
  if(a==='free-pick'){const f=document.getElementById('entry-form');if(f)freePick(f,b.dataset.d);return;}
  if(a.startsWith('sr-')){srAct(a,b);return;}
  if(a==='open-diary'){openDiary();return;}
  if(a==='open-prefs'){openPrefs();return;}
  if(a==='prefs-test'){prefsTest();return;}
  if(ENTRY_ACTS.includes(a)){
    const j=await apiPost(`/api/entries/${encodeURIComponent(id)}/act`,{act:a,v});
    if(j){if(a==='del')finish(j.msg);else refresh(j.msg);}
    return;
  }
  switch(a){
    case 'close':closePanel();break;
    case 'add':openForm(b.dataset.date);break;
    case 'edit-entry':{const e=S.entries.find(x=>x.id===id);if(e)openForm(e.from,e);break;}
    case 'new-item':openItemForm(b.dataset.kind);break;
    case 'edit-item':openItemForm(b.dataset.kind,id);break;
    case 'map-add':stopMoving();ADDING=!ADDING;updateMapTools();if(ADDING)toast('Щёлкните по карте в нужной точке');break;
    case 'map-move':{const m=PMARK[id];if(m&&m.dragging){closePanel();stopMoving();ADDING=false;updateMapTools();MOVING=id;m.dragging.enable();toast('Перетащите метку и отпустите. Отмена: щелчок по метке или Esc');}break;}
    case 'open-place':openPlace(id);break;
    case 'show-place':closePanel();UI.focusPlace=id;UI.section='map';render();if(MAP&&MAP.getContainer()===document.getElementById('leaflet')){const p=placeById(id);if(p){focusPlace(p);openPlace(id);}UI.focusPlace=null;}break;
    case 'add-at':{const p=placeById(id);openForm(S.now.date);const f=document.getElementById('entry-form');if(f&&p){f.elements.namedItem('place').value=p.id;f.elements.namedItem('where').value=placeWhere(p);}break;}
    case 'edit-district':openDistrictForm(id);break;
    case 'portrait-pick':pickPortrait(id);break;
    case 'portrait-del':{const j=await apiPost(`/api/gm/dossier/${encodeURIComponent(id)}/portrait/delete`,{});if(j){render(true);openDossier(id,true);toast(j.msg);}break;}
    case 'zoom-img':openLightbox(b.dataset.src,b.dataset.alt);break;
    case 'h-new':openHandoutForm();break;
    case 'dfilter':UI[b.dataset.k]=v;render(true);break;
    case 'dback':openDossier(id);break;
    case 'fact-add':openFactForm(b.dataset.card);break;
    case 'fact-edit':openFactForm(b.dataset.card,id);break;
    case 'fact-vis':{const c=(S.dossier||[]).find(x=>x.id===b.dataset.card);if(!c)break;const facts=c.facts.map(f=>f.id===id?Object.assign({},f,{vis:f.vis==='мастер'?'стол':'мастер',known:[]}):f);const opened=facts.find(f=>f.id===id).vis!=='мастер';await postCard(c,{facts},opened&&c.vis==='мастер'?'Сведение открыто, но карточка пока скрыта от игроков':(opened?'Сведение открыто игрокам':'Сведение скрыто'));break;}
    case 'fact-del':{const c=(S.dossier||[]).find(x=>x.id===b.dataset.card);if(c)await postCard(c,{facts:c.facts.filter(f=>f.id!==id)},'Сведение удалено');break;}
    case 'dcard-vis':{const c=(S.dossier||[]).find(x=>x.id===id);if(c){const hid=(c.facts||[]).filter(f=>f.vis==='мастер').length;await postCard(c,{vis:c.vis==='стол'?'мастер':'стол',known:[]},c.vis==='стол'?'Карточка скрыта от игроков':('Карточка открыта всем игрокам'+(hid?`. Скрытых сведений: ${hid}, открываются по одному`:'')));}break;}
    case 'del-item':{const j=await apiPost(`/api/gm/items/${b.dataset.kind}/${encodeURIComponent(id)}/delete`,{});if(j)finish(j.msg);break;}
    case 'logout':logout();break;
    case 'cal-view':UI.cal=v;render();break;
    case 'span':UI.span=v;UI.stage=null;render();break;
    case 'week':UI.anchor=clampDate(addDays(UI.anchor||addDays(S.now.date,-1),7*+v));render();break;
    case 'stage':UI.stage=Math.max(0,Math.min(S.windows.length-1,stageIdx()+ +v));render();break;
    case 'today':UI.anchor=null;UI.stage=null;UI.month=null;render();break;
    case 'month':{const i=MONTH_LIST.indexOf(curMonth())+ +v;if(i>=0&&i<MONTH_LIST.length)UI.month=MONTH_LIST[i];render();break;}
    case 'day':UI.cal='lanes';UI.span='week';UI.anchor=clampDate(addDays(b.dataset.date,-1));render();break;
    case 'played':{const j=await apiPost(`/api/gm/plan/${encodeURIComponent(id)}/played`,{});if(j)finish(j.msg);break;}
    case 'shift':{const j=await apiPost('/api/gm/time',{shift:+v});if(j)render(true);break;}
    case 'tod':{const j=await apiPost('/api/gm/time',{tod:v});if(j)render(true);break;}
    case 'jump':{const j=await apiPost('/api/gm/time',{date:document.getElementById('jump').value});if(j){render(true);toast('Дата изменена');}break;}
    case 'export':{const t=document.getElementById('exp');t.value=exportMd();t.hidden=false;t.focus();t.select();break;}
  }
});
document.addEventListener('submit',async ev=>{
  if(ev.target.id==='district-form'){
    ev.preventDefault();const f=ev.target,err=m=>{document.getElementById('form-err').textContent=m;};
    const j=await apiPost('/api/gm/district/'+f.dataset.slug,{text:f.elements.namedItem('text').value,gm_text:f.elements.namedItem('gm_text').value},err);
    if(j){openDistrict(f.dataset.slug);toast(j.msg);}
    return;
  }
  if(ev.target.id==='handout-form'){ev.preventDefault();await submitHandout(ev.target);return;}
  if(ev.target.id==='prefs-form'){ev.preventDefault();await submitPrefs(ev.target);return;}
  if(ev.target.id==='diary-form'){ev.preventDefault();await downloadDiary(ev.target);return;}
  if(ev.target.id==='sr-form'){ev.preventDefault();await submitSrForm(ev.target);return;}
  if(ev.target.id==='roll-form'){ev.preventDefault();await submitRoll(ev.target);return;}
  if(ev.target.id==='fact-form'){
    ev.preventDefault();
    const f=ev.target,F=n=>f.elements.namedItem(n),err=m=>{document.getElementById('form-err').textContent=m;};
    const c=(S.dossier||[]).find(x=>x.id===f.dataset.card);if(!c)return;
    const vis=f.querySelector('input[name="fvis"]:checked').value;
    const nf={id:f.dataset.fact||undefined,text:F('text').value.trim(),date:F('date').value,vis,known:[...f.querySelectorAll('input[name="fknown"]:checked')].map(x=>x.value),truth:F('truth').value.trim()};
    const facts=f.dataset.fact?c.facts.map(x=>x.id===f.dataset.fact?nf:x):c.facts.concat([nf]);
    const j=await apiPost('/api/gm/items/dossier',Object.assign({},c,{facts}),err);
    if(j){render(true);openDossier(c.id);toast(f.dataset.fact?'Сведение сохранено':'Сведение добавлено');}
    return;
  }
  if(ev.target.id==='item-form'){
    ev.preventDefault();
    const form=ev.target,b=collectItem(form),err=m=>{document.getElementById('form-err').textContent=m;};
    if(b.cover&&!b.cover.title)return err('Укажите, что видят игроки, или выключите маску.');
    const before=new Set((S.dossier||[]).map(x=>x.id));
    const j=await apiPost('/api/gm/items/'+form.dataset.kind,b,err);
    if(j&&form.dataset.kind==='dossier'){
      const id=form.dataset.id||((S.dossier||[]).find(x=>!before.has(x.id))||{}).id;
      render(true);if(id)openDossier(id);else closePanel();toast(j.msg);return;
    }
    if(j)finish(j.msg);
    return;
  }
  if(ev.target.id!=='chat-form')return;
  ev.preventDefault();
  const form=ev.target,ta=form.elements.namedItem('msg'),t=ta.value.trim();
  if(!t)return;
  const j=await apiPost(`/api/entries/${encodeURIComponent(form.dataset.id)}/messages`,{text:t});
  if(!j)return;
  ta.value='';
  render(true);openDetail('e:'+form.dataset.id,true);
  const last=document.querySelector('#panel .chat .msg:last-child');last&&last.scrollIntoView({block:'nearest'});
  const ta2=document.querySelector('#chat-form textarea');ta2&&ta2.focus();
});
document.addEventListener('change',async ev=>{
  if(ev.target.dataset&&ev.target.dataset.layer){const k=ev.target.dataset.layer;MAPLAYERS[k]=ev.target.checked;if(MAP&&MAPL[k]){ev.target.checked?MAP.addLayer(MAPL[k]):MAP.removeLayer(MAPL[k]);}return;}
  if(ev.target.id==='who-select'){V=ev.target.value;UI.stage=null;if(!S.me.gm){try{localStorage.setItem(STORE_CHAR,V);}catch(e){}}render();if(curKey&&overlayOpen())openDetail(curKey,true);}
  if(ev.target.id==='quiet'){const j=await apiPost('/api/gm/time',{quiet:ev.target.value||''});if(j)render(true);}
});
document.addEventListener('keydown',ev=>{
  if(ev.key==='Escape'&&overlayOpen()){closePanel();return;}
  if(ev.key==='Escape'&&UI.section==='map'&&MEASURE.on&&!ADDING&&!MOVING){measureStop(false);return;}
  if(ev.key==='Escape'&&UI.section==='map'&&(ADDING||MOVING)){if(ADDING){ADDING=false;updateMapTools();toast('Добавление места отменено');}stopMoving('Перемещение отменено');return;}
  if(ev.key==='Enter'&&(ev.ctrlKey||ev.metaKey)&&ev.target.closest&&ev.target.closest('#chat-form')){ev.preventDefault();ev.target.closest('#chat-form').requestSubmit();}
});
