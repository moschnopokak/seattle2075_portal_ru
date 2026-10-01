/* ===== Настройки личных уведомлений ===== */
const TZ_LIST=['Europe/Kaliningrad','Europe/Moscow','Europe/Samara','Asia/Yekaterinburg','Asia/Omsk','Asia/Novosibirsk','Asia/Krasnoyarsk','Asia/Irkutsk','Asia/Yakutsk','Asia/Vladivostok','Asia/Magadan','Asia/Kamchatka','Europe/Kyiv','Europe/Minsk','Europe/Riga','Europe/Vilnius','Europe/Tallinn','Europe/Warsaw','Europe/Berlin','Europe/Paris','Europe/London','Europe/Lisbon','Europe/Istanbul','Asia/Tbilisi','Asia/Yerevan','Asia/Baku','Asia/Almaty','Asia/Tashkent','Asia/Dubai','Asia/Jerusalem','Asia/Bangkok','Asia/Shanghai','Asia/Tokyo','Australia/Sydney','America/New_York','America/Chicago','America/Denver','America/Los_Angeles','UTC'];
function browserTz(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone||'';}catch(e){return '';}}
const hourOpts=sel=>Array.from({length:24},(_,h)=>`<option value="${h}" ${h===sel?'selected':''}>${pad(h)}:00</option>`).join('');
async function openPrefs(){
  const j=await getJson('/api/me/prefs');
  if(!j){toast('Не удалось загрузить настройки');return;}
  const p=j.prefs,bt=browserTz(),zones=[...new Set([bt,...TZ_LIST].filter(Boolean))];
  curKey=null;
  showPanel(`<p class="kind">Настройки</p><h2>Личные уведомления</h2>
  ${j.dm?'<p class="note">Сообщения приходят от бота в Telegram. Если ничего не приходит, откройте бота и нажмите «Запустить», затем проверьте связь кнопкой ниже.</p>':'<p class="err">На этом портале личные уведомления выключены: не задан токен бота или NOTIFY_DM=0.</p>'}
  <form id="prefs-form" novalidate>
    <label class="check"><input type="checkbox" name="chat_notify" ${p.chat_notify?'checked':''}> Сообщения в обсуждениях записей (одним уведомлением, примерно через ${j.chat_minutes} мин. после первого)</label>
    <fieldset class="vis"><legend>Как получать уведомления</legend>
      <label><input type="radio" name="mode" value="now" ${p.digest_on?'':'checked'}> Сразу, как только что-то случилось</label>
      <label><input type="radio" name="mode" value="digest" ${p.digest_on?'checked':''}> Одной сводкой раз в день, в <select name="digest_hour" aria-label="Час сводки">${hourOpts(p.digest_hour)}</select></label>
    </fieldset>
    <label class="check"><input type="checkbox" name="quiet_on" ${p.quiet_on?'checked':''}> Тихие часы: не беспокоить с <select name="quiet_from" aria-label="Тихие часы с">${hourOpts(p.quiet_from)}</select> до <select name="quiet_to" aria-label="Тихие часы до">${hourOpts(p.quiet_to)}</select></label>
    <p class="muted small" style="margin:2px 0 10px">Всё, что случилось в тихие часы, придёт одним сообщением после их окончания. В режиме сводки тихие часы не нужны.</p>
    <label class="field">Часовой пояс<input name="tz" list="tz-list" maxlength="64" value="${esc(p.tz)}" autocomplete="off"><datalist id="tz-list">${zones.map(z=>`<option value="${esc(z)}">`).join('')}</datalist>
      <span class="sub">${bt&&bt!==p.tz?`Браузер сообщает: ${esc(bt)}. `:''}Нужен, чтобы тихие часы и сводка шли по вашему времени.</span></label>
    <p class="err" id="form-err" role="alert"></p>
    <div class="acts"><button type="submit" class="btn primary">Сохранить</button><button type="button" class="btn" data-act="prefs-test">Отправить пробное сообщение</button><button type="button" class="btn" data-act="close">Закрыть</button></div>
  </form>`);
}
async function submitPrefs(form){
  const F=n=>form.elements.namedItem(n),err=m=>{document.getElementById('form-err').textContent=m;};
  const body={chat_notify:F('chat_notify').checked,digest_on:form.querySelector('input[name="mode"]:checked').value==='digest',digest_hour:+F('digest_hour').value,
    quiet_on:F('quiet_on').checked,quiet_from:+F('quiet_from').value,quiet_to:+F('quiet_to').value,tz:F('tz').value.trim()};
  const j=await apiPost('/api/me/prefs',body,err);
  if(j){closePanel();toast('Настройки сохранены');}
}
async function prefsTest(){
  const r=await fetch('/api/me/prefs/test',{method:'POST',credentials:'same-origin',headers:authHeaders()});
  let j=null;try{j=await r.json();}catch(e){}
  if(r.ok)toast('Пробное сообщение отправлено. Проверьте Telegram');
  else{const m=errText(j);const el=document.getElementById('form-err');if(el)el.textContent=m;else toast(m);}
}
