/* ===== Броски кубов в обсуждении (Shadowrun 5) =====
   Кубы бросает сервер, страница только рисует результат. Успех 5 и 6, глитч: единиц больше половины пула. */
const DICE_MAX=40;
Object.assign(UI,{rollOpen:false});
function diceFaces(list,extra){
  return list.map(d=>`<span class="die${d>=5?' hit':''}${d===1&&!extra?' one':''}${extra?' extra':''}" aria-hidden="true">${d}</span>`).join('');
}
function rollHTML(m){
  const r=m.r,all=r.dice.concat(r.extra||[]);
  const parts=[`<b>Успехов: ${r.hits}</b>`];
  if(r.limit!=null&&!r.edge&&r.counted!==r.hits)parts[0]+=`, с учётом предела ${r.limit}: <b>${r.counted}</b>`;
  if(r.limit!=null&&r.edge)parts.push('предел не действует');
  if(r.threshold!=null)parts.push(`порог ${r.threshold}: <b class="${r.success?'roll-ok':'roll-fail'}">${r.success?'успех':'провал'}</b>`);
  if(r.glitch)parts.push(`<b class="roll-fail">${r.glitch==='critical'?'критический глитч':'глитч'}</b>`);
  return `<div class="roll"><div class="roll-head">Бросок ${r.pool}d6${r.label?` «${esc(r.label)}»`:''}${r.edge?' · с риском':''}</div>
  <div class="dice" role="img" aria-label="Выпало: ${all.join(', ')}">${diceFaces(r.dice)}${r.extra&&r.extra.length?`<span class="dice-plus" aria-hidden="true">+</span>${diceFaces(r.extra,true)}`:''}</div>
  <div class="roll-res">${parts.join(' · ')}</div></div>`;
}
function rollFormHTML(e){
  return `<details class="roll-box" ${UI.rollOpen?'open':''}><summary>Бросить кубы</summary>
  <form id="roll-form" data-id="${esc(e.id)}" novalidate>
    <div class="roll-row"><label class="field">Кубов<input name="dice" type="number" min="1" max="${DICE_MAX}" step="1" value="6" inputmode="numeric"></label>
    <label class="field">Предел<input name="limit" type="number" min="1" max="99" step="1" placeholder="нет" inputmode="numeric"></label>
    <label class="field">Порог<input name="threshold" type="number" min="0" max="99" step="1" placeholder="нет" inputmode="numeric"></label></div>
    <label class="check"><input type="checkbox" name="edge"> Рискнуть: шестёрки взрываются, предел не действует</label>
    <label class="field">Что проверяем<input name="label" maxlength="60" placeholder="Например: скрытность" autocomplete="off"></label>
    <p class="err" id="roll-err" role="alert"></p>
    <div class="acts"><button type="submit" class="btn primary">Бросить</button></div>
  </form></details>`;
}
async function submitRoll(form){
  const F=n=>form.elements.namedItem(n),err=m=>{document.getElementById('roll-err').textContent=m;};
  const dice=Number(F('dice').value);
  if(!F('dice').value.trim()||!Number.isInteger(dice)||dice<1||dice>DICE_MAX)return err(`Число кубов: от 1 до ${DICE_MAX}.`);
  const opt=n=>F(n).value.trim()===''?null:Number(F(n).value);
  UI.rollOpen=true;
  const j=await apiPost(`/api/entries/${encodeURIComponent(form.dataset.id)}/roll`,{dice,limit:opt('limit'),threshold:opt('threshold'),edge:F('edge').checked,label:F('label').value.trim()},err);
  if(!j)return;
  render(true);openDetail('e:'+form.dataset.id,true);
  const last=document.querySelector('#panel .chat .msg:last-child');if(last)last.scrollIntoView({block:'nearest'});
}

/* Для автотестов в Node: в браузере переменной module нет. */
if(typeof module!=='undefined'&&module.exports){
  module.exports={DICE_MAX,diceFaces,rollHTML};
}
