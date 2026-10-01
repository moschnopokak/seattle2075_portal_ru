/* ===== «Мой дневник»: скачать всё, что знает персонаж, в Markdown или PDF =====
   Файл собирает сервер из того же состояния, которое он отдаёт этому игроку, поэтому в нём нет ничего, чего игрок не видит. */
const DIARY_PARTS={chron:'Хроника',entries:'Мои записи',chat:'Обсуждения записей',dossier:'Досье',handouts:'Раздатки',sheet:'Лист персонажа (нуйены, репутация, контакты)'};
const DIARY_DEFAULT=['chron','entries','dossier','handouts','sheet'];
const diaryName=h=>{
  const star=/filename\*=UTF-8''([^;]+)/i.exec(h||'');
  if(star){try{return decodeURIComponent(star[1]);}catch(e){}}
  const plain=/filename="([^"]+)"/i.exec(h||'');
  return plain?plain[1]:'diary';
};
function openDiary(){
  const c=viewChars()||[];if(V==='gm'||!c.length)return;
  curKey=null;
  showPanel(`<p class="kind">Мой дневник</p><h2>${esc(CN[V]||'')}</h2>
  <p class="note">Всё, что знает ваш персонаж, одним файлом. В нём только то, что вы видите на портале.</p>
  <form id="diary-form" novalidate>
    <fieldset class="who"><legend>Что включить</legend>${Object.entries(DIARY_PARTS).map(([k,t])=>`<label><input type="checkbox" name="part" value="${k}" ${DIARY_DEFAULT.includes(k)?'checked':''}> ${t}</label>`).join('')}</fieldset>
    <fieldset class="vis"><legend>Формат</legend><label><input type="radio" name="fmt" value="md" checked> Markdown (для Obsidian и других заметок)</label><label><input type="radio" name="fmt" value="pdf"> PDF (для чтения и печати)</label></fieldset>
    <p class="err" id="form-err" role="alert"></p>
    <div class="dl-acts"><button type="submit" class="btn primary">Скачать</button><button type="button" class="btn" data-act="close">Закрыть</button></div>
  </form>`);
}
async function downloadDiary(form){
  const err=m=>{document.getElementById('form-err').textContent=m;};
  const parts=[...form.querySelectorAll('input[name="part"]:checked')].map(x=>x.value),fmt=form.querySelector('input[name="fmt"]:checked').value;
  if(!parts.length)return err('Отметьте, что включить в дневник.');
  const btn=form.querySelector('button[type="submit"]');btn.disabled=true;btn.textContent='Готовлю…';
  try{
    const r=await fetch(`/api/me/diary?format=${fmt}&parts=${parts.join(',')}&char=${encodeURIComponent(V)}`,{credentials:'same-origin',headers:authHeaders()});
    if(r.status===401){showLogin();return;}
    if(!r.ok){let j=null;try{j=await r.json();}catch(e){}err(errText(j));return;}
    const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=diaryName(r.headers.get('content-disposition'));document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    closePanel();toast('Дневник сохранён');
  }catch(e){err('Нет связи с сервером. Попробуйте ещё раз.');}
  finally{btn.disabled=false;btn.textContent='Скачать';}
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={DIARY_PARTS,DIARY_DEFAULT,diaryName};
}
