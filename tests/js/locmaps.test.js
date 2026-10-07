// Тесты карт локаций: чистые функции (static/js/locmaps.js). Ни одна из них не открывает метку, которой игрок видеть не должен.
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { UI: {}, esc: util.esc });
const lm = require("../../static/js/locmaps.js");

const OPEN = { id: "a", key: "О1", name: "Ворота", kind: "area", status: "", vis: "стол", known: [], note: "Видно", gm_note: "СЕКРЕТ", at: { player: [10, 20], gm: [30, 40] } };
const HID = { id: "b", key: "О2", name: "Тайник", kind: "thing", vis: "мастер", known: [], note: "", gm_note: "СЕКРЕТ", at: { player: [1, 2] } };
const SOME = { id: "c", key: "О3", name: "Пост", kind: "danger", status: "danger", vis: "знают", known: ["rig"], note: "Для своих", gm_note: "СЕКРЕТ", at: { gm: [5, 5] } };
const DATA = {
  id: "m1", name: "Роща", dw: { player: { w: 800, h: 600, v: 1 }, gm: { w: 800, h: 600, v: 2 } },
  objects: [OPEN, HID, SOME],
  feed: [
    { id: 1, ts: 1, date: "2075-08-20", obj: "a", text: "Ворота открыты", vis: "стол", known: [] },
    { id: 2, ts: 2, date: "2075-08-21", obj: "c", text: "Пост занят", vis: "знают", known: ["rig"] },
    { id: 3, ts: 3, date: "2075-09-30", obj: "a", text: "Из будущего", vis: "стол", known: [] },
  ],
  pins: [{ id: 1, char: "rig", x: 1, y: 1, text: "Тропы врут" }],
};

test("подпись на метке короткая и не пустая", () => {
  assert.equal(lm.lmLabel({ key: "Ворота-1-длинная" }), "Ворот");                  // не больше пяти знаков
  assert.equal(lm.lmLabel({ name: "Пост" }), "Пост");
  assert.equal(lm.lmLabel({}), "?");
});

test("состояние называется по-русски, неизвестное считается «без отметки»", () => {
  assert.equal(lm.lmStatusText("cleared"), "расчищено");
  assert.equal(lm.lmStatusText("что-то"), "без отметки");
  assert.equal(lm.lmStatusText(""), "без отметки");
});

test("классы метки: вид, состояние, скрытая от игроков видна только мастеру", () => {
  assert.equal(lm.lmPinClass(OPEN, true), "lm-pin lm-k-area");
  assert.equal(lm.lmPinClass(SOME, true), "lm-pin lm-k-danger lm-s-danger");
  assert.match(lm.lmPinClass(HID, true), /lm-hid/);
  assert.doesNotMatch(lm.lmPinClass(HID, false), /lm-hid/);
  assert.match(lm.lmPinClass({ kind: "неизвестно" }, false), /lm-k-place/);
});

test("положение берётся с рисунка нужной роли", () => {
  assert.deepEqual(lm.lmAt(OPEN, "player"), [10, 20]);
  assert.deepEqual(lm.lmAt(OPEN, "gm"), [30, 40]);
  assert.equal(lm.lmAt(HID, "gm"), null);
  assert.equal(lm.lmAt({}, "player"), null);
});

test("в предпросмотре мастера карты отбираются так же, как их видит игрок", () => {
  const maps = [{ id: "1", vis: "стол", known: [] }, { id: "2", vis: "мастер", known: [] }, { id: "3", vis: "знают", known: ["rig"] }, { id: "4", vis: "знают", known: ["gate"] }];
  assert.deepEqual(lm.lmMapsFor(maps, false, null).map(m => m.id), ["1", "2", "3", "4"]);
  assert.deepEqual(lm.lmMapsFor(maps, true, ["rig"]).map(m => m.id), ["1", "3"]);
  assert.deepEqual(lm.lmMapsFor(maps, true, ["gate"]).map(m => m.id), ["1", "4"]);
  assert.deepEqual(lm.lmMapsFor(null, false, null), []);
});

test("предпросмотр: скрытые метки, заметки мастера и рисунок мастера не попадают в картинку игрока", () => {
  const v = lm.lmPlayerView(DATA, ["gate"], "");
  assert.deepEqual(v.objects.map(o => o.id), ["a"]);
  assert.deepEqual(v.objects[0].at, { player: [10, 20] });
  assert.equal(JSON.stringify(v).includes("СЕКРЕТ"), false);
  assert.deepEqual(v.dw, { player: { w: 800, h: 600, v: 1 } });
  assert.equal(v.vis, undefined);
  assert.equal(v.known, undefined);
});

test("предпросмотр: метка для выбранных видна только им, а лента режется по границе «вперёд»", () => {
  const rig = lm.lmPlayerView(DATA, ["rig"], "2075-08-31");
  assert.deepEqual(rig.objects.map(o => o.id), ["a", "c"]);
  assert.deepEqual(rig.objects[1].at, {});                                   // у этой метки нет места на рисунке игроков
  assert.deepEqual(rig.feed.map(f => f.id), [1, 2]);                          // запись из сентября за границей
  const gate = lm.lmPlayerView(DATA, ["gate"], "2075-08-31");
  assert.deepEqual(gate.feed.map(f => f.id), [1]);
  assert.deepEqual(lm.lmPlayerView(DATA, ["gate"], "").feed.map(f => f.id), [1, 3]);
  assert.deepEqual(rig.pins, DATA.pins);                                      // пометки группы общие
});

test("высота окна карты следует форме рисунка, но в пределах экрана", () => {
  const wide = { w: 1684, h: 1190 }, tall = { w: 600, h: 1800 };
  assert.equal(lm.lmHeight(390, wide, 390, 844), 292);                        // телефон: без пустого поля вокруг рисунка
  assert.equal(lm.lmHeight(1100, wide, 1200, 860), 585);                      // компьютер: не выше 68% экрана
  assert.equal(lm.lmHeight(390, tall, 390, 844), 523);                        // высокий рисунок: не выше 62% экрана
  assert.equal(lm.lmHeight(390, { w: 1000, h: 50 }, 390, 844), 260);          // очень низкий: не ниже 260
  assert.equal(lm.lmHeight(1900, tall, 2000, 1600), 660);                     // и не выше 660
});
