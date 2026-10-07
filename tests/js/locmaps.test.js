// Тесты карт локаций: чистые функции (static/js/locmaps.js). Ни одна из них не открывает метку, которой игрок видеть не должен.
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { UI: {}, esc: util.esc });
const lm = require("../../static/js/locmaps.js");
Object.assign(globalThis, { lmShape: lm.lmShape, LM_STATUS: lm.LM_STATUS, plural: util.plural });
const lp = require("../../static/js/locplay.js");

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

test("контур зоны берётся для нужного рисунка и должен быть настоящим многоугольником", () => {
  const z = { shape: { player: [[0, 0], [10, 0], [10, 10]], gm: [[0, 0], [1, 1]] } };
  assert.deepEqual(lm.lmShape(z, "player"), [[0, 0], [10, 0], [10, 10]]);
  assert.equal(lm.lmShape(z, "gm"), null);                                     // две точки не зона
  assert.equal(lm.lmShape({}, "player"), null);
  assert.equal(lm.lmPlaced({ shape: z.shape }, "player"), true);               // зона без метки-точки тоже «стоит на рисунке»
  assert.equal(lm.lmPlaced({ at: { gm: [1, 1] } }, "player"), false);
});

test("центр зоны считается по площади и лежит внутри обычного контура", () => {
  assert.deepEqual(lm.lmCentroid([[0, 0], [100, 0], [100, 50], [0, 50]]), [50, 25]);
  assert.deepEqual(lm.lmCentroid([[0, 0], [90, 0], [0, 90]]), [30, 30]);
  assert.deepEqual(lm.lmCentroid([[0, 0], [10, 10], [20, 20]]), [10, 10]);     // контур-линия не ломает подпись
  const L = [[0, 0], [100, 0], [100, 10], [10, 10], [10, 100], [0, 100]];      // буква Г: центр по площади
  const [x, y] = lm.lmCentroid(L); assert.ok(x > 0 && x < 100 && y > 0 && y < 100);
});

test("подпись зоны стоит там, где задано, а без места в центре контура", () => {
  const sq = [[0, 0], [100, 0], [100, 100], [0, 100]];
  assert.deepEqual(lm.lmLabelAt({ at: { player: [5, 6] }, shape: { player: sq } }, "player"), [5, 6]);
  assert.deepEqual(lm.lmLabelAt({ shape: { player: sq } }, "player"), [50, 50]);
  assert.equal(lm.lmLabelAt({ shape: { gm: sq } }, "player"), null);
});

test("игрок может отметить только то, что подходит виду метки", () => {
  assert.deepEqual(lm.lmPlayStatuses({ kind: "area" }), ["scouted", "cleared", "danger"]);
  assert.deepEqual(lm.lmPlayStatuses({ kind: "thing" }), ["scouted", "found", "lost"]);
  assert.deepEqual(lm.lmPlayStatuses({ kind: "что-то" }), ["scouted", "cleared", "danger"]);
  for (const list of Object.values(lm.LM_PLAY_STATUS)) for (const s of list) assert.ok(lm.LM_STATUS[s], s);
});

test("кто отметил: имя персонажа, мастер или никто", () => {
  const names = { rig: "Риг" };
  assert.equal(lm.lmByName({ by: "rig" }, names), "Риг");
  assert.equal(lm.lmByName({ by: "gm" }, names), "мастер");
  assert.equal(lm.lmByName({ by: "" }, names), "");
  assert.equal(lm.lmByName({ by: "ушёл" }, names), "");
});

test("классы контура зоны: вид, состояние, право игроков, скрытая от игроков только у мастера", () => {
  assert.equal(lm.lmZoneClass({ kind: "area" }, false), "lm-zone lm-k-area");
  assert.equal(lm.lmZoneClass({ kind: "area", status: "cleared", play: true }, true), "lm-zone lm-k-area lm-s-cleared lm-play");
  assert.match(lm.lmZoneClass({ kind: "area", vis: "мастер" }, true), /lm-hid/);
  assert.doesNotMatch(lm.lmZoneClass({ kind: "area", vis: "мастер" }, false), /lm-hid/);
});

test("предпросмотр глазами игрока оставляет контур зоны и право отмечать, но не контур мастера", () => {
  const data = { id: "m", dw: { player: { w: 1, h: 1, v: 1 } }, feed: [], pins: [], objects: [
    { id: "z", key: "О1", name: "Аллея", kind: "area", status: "cleared", vis: "стол", known: [], note: "", gm_note: "СЕКРЕТ", play: true, by: "rig", date: "2075-08-01",
      at: { player: [1, 1], gm: [2, 2] }, shape: { player: [[0, 0], [5, 0], [5, 5]], gm: [[9, 9], [8, 8], [7, 9]] } }] };
  const z = lm.lmPlayerView(data, ["rig"], "").objects[0];
  assert.deepEqual(z.shape, { player: [[0, 0], [5, 0], [5, 5]] });
  assert.equal(z.play, true); assert.equal(z.by, "rig"); assert.equal(z.date, "2075-08-01");
  assert.equal(JSON.stringify(z).includes("СЕКРЕТ"), false); assert.equal(JSON.stringify(z).includes("[9,9]"), false);
});

// ---- locplay.js: то, что помогает на игре

const SQ = [[0, 0], [100, 0], [100, 100], [0, 100]];
const zone = (status, extra = {}) => Object.assign({ shape: { player: SQ }, status }, extra);

test("прогресс считает только зоны с контуром на этом рисунке", () => {
  const objs = [zone("cleared"), zone("cleared"), zone("danger"), zone("scouted"), zone(""), { status: "cleared" }, { shape: { gm: SQ }, status: "cleared" }];
  assert.deepEqual(lp.lmProgress(objs, "player"), { total: 5, cleared: 2, danger: 1, scouted: 1 });
  assert.deepEqual(lp.lmProgress(objs, "gm"), { total: 1, cleared: 1, danger: 0, scouted: 0 });
  assert.deepEqual(lp.lmProgress([], "player"), { total: 0, cleared: 0, danger: 0, scouted: 0 });
});

test("точка внутри или снаружи контура, в том числе у вогнутой фигуры", () => {
  assert.equal(lp.lmInside([50, 50], SQ), true);
  assert.equal(lp.lmInside([150, 50], SQ), false);
  const g = [[0, 0], [100, 0], [100, 10], [10, 10], [10, 100], [0, 100]];             // буква Г
  assert.equal(lp.lmInside([5, 50], g), true);
  assert.equal(lp.lmInside([50, 50], g), false);
});

test("в какой зоне стоит группа: из вложенных берётся самая маленькая, вне зон пусто", () => {
  const big = { id: "big", shape: { player: SQ } }, small = { id: "small", shape: { player: [[40, 40], [60, 40], [60, 60], [40, 60]] } };
  assert.equal(lp.lmZoneAt([big, small], "player", [50, 50]).id, "small");
  assert.equal(lp.lmZoneAt([big, small], "player", [10, 10]).id, "big");
  assert.equal(lp.lmZoneAt([big, small], "player", [500, 500]), null);
  assert.equal(lp.lmZoneAt([big], "gm", [50, 50]), null);
});

test("дни до срока и слова о нём", () => {
  assert.equal(lp.lmDays("2075-08-31", "2075-09-02"), 2);
  assert.equal(lp.lmDays("2075-09-02", "2075-08-31"), -2);
  assert.equal(lp.lmDays("2075-02-27", "2075-03-01"), 2);                                  // граница месяцев
  assert.equal(lp.lmDueText("2075-08-31", "2075-08-31"), "сегодня");
  assert.equal(lp.lmDueText("2075-09-01", "2075-08-31"), "через 1 день");
  assert.equal(lp.lmDueText("2075-09-03", "2075-08-31"), "через 3 дня");
  assert.equal(lp.lmDueText("2075-09-10", "2075-08-31"), "через 10 дней");
  assert.equal(lp.lmDueText("2075-08-30", "2075-08-31"), "1 день назад");
  assert.equal(lp.lmDueText("2075-08-26", "2075-08-31"), "5 дней назад");
});

test("новые записи ленты: сколько новее последней виденной", () => {
  assert.equal(lp.lmNewCount([9, 7, 5, 2], 5), 2);
  assert.equal(lp.lmNewCount([9, 7, 5, 2], undefined), 4);
  assert.equal(lp.lmNewCount([9, 7], 9), 0);
  assert.equal(lp.lmNewCount(undefined, 3), 0);
});

test("значок вкладки: игроку новые записи по всем картам, мастеру наступившие сроки и неотвеченные вопросы", () => {
  const maps = [{ id: "a", fresh: [9, 8, 3], due: 9 }, { id: "b", fresh: [4, 2], open_q: 9 }];
  assert.equal(lp.lmBadgeCount(maps, { a: 8, b: 0 }, false), 1 + 2);
  assert.equal(lp.lmBadgeCount(maps, {}, false), 5);
  assert.equal(lp.lmBadgeCount([{ id: "a", due: 2, open_q: 1 }, { id: "b", due: 0, open_q: 3 }], {}, true), 6);
  assert.equal(lp.lmBadgeCount([], {}, false), 0);
});

test("правила расчистки читаются из текста и пишутся обратно", () => {
  assert.deepEqual(lp.lmParseFx("этой −2; Сердце −1"), { fx: [{ to: "self", delta: -2 }, { to: "Сердце", delta: -1 }], error: "" });
  assert.deepEqual(lp.lmParseFx("сама -3\nГ1 +2"), { fx: [{ to: "self", delta: -3 }, { to: "Г1", delta: 2 }], error: "" });
  assert.deepEqual(lp.lmParseFx("Верхний сектор 1"), { fx: [{ to: "Верхний сектор", delta: 1 }], error: "" });
  assert.deepEqual(lp.lmParseFx(""), { fx: [], error: "" });
  assert.match(lp.lmParseFx("этой много").error, /Не понял «этой много»/);
  assert.equal(lp.lmFxText([{ to: "self", delta: -2 }, { to: "Сердце", delta: 1 }]), "этой −2; Сердце +1");
  assert.deepEqual(lp.lmParseFx(lp.lmFxText([{ to: "self", delta: -2 }, { to: "Сердце", delta: 3 }])).fx, [{ to: "self", delta: -2 }, { to: "Сердце", delta: 3 }]);
});

test("последствия срока словами для мастера", () => {
  assert.equal(lp.lmEffectsText({}, ""), "без последствий");
  assert.equal(lp.lmEffectsText({ status: "danger", reveal: true, delta: -1, obj: "x" }, "Аллея"), "«Аллея»: состояние «опасно», открыть метку игрокам, счётчик −1 у зоны");
  assert.equal(lp.lmEffectsText({ delta: 1 }, ""), "счётчик +1 везде");
});

test("предпросмотр глазами игрока: сроки только открытые, без заметок мастера, журнала и счётчика", () => {
  const data = { id: "m", counter: "Фон", log: [{ id: 1 }], dw: { player: { w: 1, h: 1, v: 1 } }, feed: [], pins: [],
    objects: [{ id: "z", key: "О1", name: "Аллея", kind: "area", vis: "стол", known: [], count: 3, fx: [{ to: "self", delta: -1 }], links: [{ kind: "dossier", id: "d1" }] },
              { id: "h", key: "Х", name: "Скрытая", kind: "area", vis: "мастер", known: [] }],
    deadlines: [{ id: "1", date: "2075-08-05", title: "Тайный", vis: "мастер", known: [], note: "СЕКРЕТ", obj: "", done: false },
                { id: "2", date: "2075-08-06", title: "Открытый", vis: "стол", known: [], note: "СЕКРЕТ", obj: "z", status: "danger", delta: 2, done: false },
                { id: "3", date: "2075-08-07", title: "Для Рига", vis: "знают", known: ["rig"], obj: "h", done: true },
                { id: "4", date: "2075-09-30", title: "Далеко", vis: "стол", known: [], obj: "" }] };
  const rig = lm.lmPlayerView(data, ["rig"], "2075-08-31"), gate = lm.lmPlayerView(data, ["gate"], "");
  assert.deepEqual(rig.deadlines.map(d => d.title), ["Открытый", "Для Рига"]);                      // тайный скрыт, дальний за границей
  assert.deepEqual(gate.deadlines.map(d => d.title), ["Открытый", "Далеко"]);
  assert.deepEqual(Object.keys(rig.deadlines[0]).sort(), ["date", "done", "id", "obj", "title"]);
  assert.equal(rig.deadlines[0].obj, "z"); assert.equal(rig.deadlines[1].obj, "");                  // скрытую метку по сроку не узнать
  assert.equal(rig.log, undefined); assert.equal(rig.counter, undefined);
  const text = JSON.stringify(rig);
  assert.equal(text.includes("СЕКРЕТ"), false); assert.equal(text.includes('"count"'), false); assert.equal(text.includes('"fx"'), false);
  assert.deepEqual(rig.objects[0].links, [{ kind: "dossier", id: "d1" }]);
});
