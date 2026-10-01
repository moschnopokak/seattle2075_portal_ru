// Тесты листа персонажа (static/js/sheet.js) и отрисовки бросков (static/js/dice.js): чистые функции и экранирование.
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { UI: {}, esc: util.esc });                    // sheet.js и dice.js дописывают в общий объект UI и берут esc из общей области
const sheet = require("../../static/js/sheet.js");
const dice = require("../../static/js/dice.js");

const money = [
  { id: "m1", char: "rig", delta: 1500, note: "Награда", date: "2075-08-01" },
  { id: "m2", char: "rig", delta: -200, note: "Ремонт", date: "2075-08-03" },
  { id: "m3", char: "gate", delta: 100, note: "", date: "2075-08-02" },
  { id: "m4", char: "rig", delta: -50, note: "Кофе", date: "2075-08-03" },
];

test("баланс и порядок проводок", () => {
  assert.equal(sheet.sheetBalance("rig", money), 1250);
  assert.equal(sheet.sheetBalance("gate", money), 100);
  assert.equal(sheet.sheetBalance("нет", money), 0);
  assert.equal(sheet.sheetBalance("rig", undefined), 0);
  assert.deepEqual(sheet.sheetLedger("rig", money).map((m) => m.id), ["m4", "m2", "m1"]);       // новые сверху, при равной дате позже внесённая выше
});

test("суммы в нуйенах", () => {
  assert.equal(sheet.fmtNuyen(1500), "+1 500 ¥");
  assert.equal(sheet.fmtNuyen(-1234567), "−1 234 567 ¥");
  assert.equal(sheet.fmtNuyen(40), "+40 ¥");
  assert.equal(sheet.fmtBalance(-2500), "−2 500 ¥");
  assert.equal(sheet.fmtBalance(0), "0 ¥");
  assert.equal(sheet.signed(0), "0");
  assert.equal(sheet.signed(-3), "−3");
});

test("подписи репутации от −5 до +5", () => {
  for (let v = -5; v <= 5; v++) assert.ok(sheet.standingLabel(v), String(v));
  assert.equal(sheet.standingLabel(7), "");
});

const full = {
  factions: [
    { id: "f1", name: "Открытая", kind: "corp", vis: "стол", note: "Публично" },
    { id: "f2", name: "Для Рига", kind: "gang", vis: "знают", known: ["rig"] },
    { id: "f3", name: "Скрытая", vis: "мастер" },
  ],
  standing: [
    { id: "s1", char: "rig", faction: "f1", value: 2, note: "", gm_note: "СЕКРЕТ" },
    { id: "s2", char: "rig", faction: "f2", value: -3 },
    { id: "s3", char: "rig", faction: "f3", value: 5 },
    { id: "s4", char: "gate", faction: "f2", value: 4 },
    { id: "s5", char: "rig", faction: "нет", value: 1 },
  ],
  money,
  contacts: [
    { id: "c1", char: "rig", name: "Ли", card: "n2", connection: 4, loyalty: 2, gm_note: "СЕКРЕТ" },
    { id: "c2", char: "rig", name: "Эй", card: "n1", connection: 1, loyalty: 1 },
    { id: "c3", char: "gate", name: "Чужой", connection: 3, loyalty: 3 },
  ],
};

test("предпросмотр мастера повторяет правила видимости сервера", () => {
  const v = sheet.sheetView(full, ["rig"], new Set(["n1"]));
  assert.deepEqual(v.standing.map((s) => s.id), ["s1", "s2"]);                                  // скрытая и несуществующая фракции не показываются
  assert.deepEqual(v.factions.map((f) => f.id), ["f1", "f2"]);
  assert.deepEqual(v.money.map((m) => m.id), ["m1", "m2", "m4"]);
  assert.deepEqual(v.contacts.map((c) => c.id), ["c1", "c2"]);
  assert.equal(v.contacts[0].card, undefined);                                                  // карточка n2 этому игроку не открыта
  assert.equal(v.contacts[1].card, "n1");
  assert.ok(!JSON.stringify(v).includes("СЕКРЕТ"));                                             // заметки мастера не просачиваются
});

test("знающий фракцию другой персонаж видит свою репутацию, а чужую нет", () => {
  const v = sheet.sheetView(full, ["gate"], new Set());
  assert.deepEqual(v.standing.map((s) => s.id), []);                                            // Гейт фракцию f2 не знает
  assert.deepEqual(v.factions.map((f) => f.id), ["f1"]);
});

test("игрок с двумя персонажами видит данные обоих, но не чужих", () => {
  const v = sheet.sheetView(full, ["rig", "gate"], new Set());
  assert.deepEqual(v.money.map((m) => m.char).sort(), ["gate", "rig", "rig", "rig"]);
  assert.ok(v.contacts.every((c) => ["rig", "gate"].includes(c.char)));
});

test("ответ сервера без поля vis у фракций проходит как есть", () => {
  const served = { factions: [{ id: "f1", name: "А", kind: "corp", note: "" }], standing: [{ id: "s1", char: "rig", faction: "f1", value: 1, note: "" }], money: [], contacts: [] };
  const v = sheet.sheetView(served, ["rig"], new Set());
  assert.equal(v.standing.length, 1);
  assert.equal(v.factions.length, 1);
});

test("пустые и неполные данные не роняют", () => {
  const v = sheet.sheetView({}, ["rig"], new Set());
  assert.deepEqual(v, { money: [], standing: [], factions: [], contacts: [] });
});

// ---- кубы

const roll = (over = {}) => ({ a: "rig", t: "", r: { pool: 4, dice: [6, 5, 1, 2], extra: [], hits: 2, counted: 2, ones: 1, glitch: "", edge: false, limit: null, threshold: null, success: null, net: null, label: "", ...over } });

test("бросок рисуется кубиками и итогом", () => {
  const html = dice.rollHTML(roll());
  assert.match(html, /Бросок 4d6/);
  assert.equal((html.match(/class="die hit"/g) || []).length, 2);
  assert.equal((html.match(/class="die one"/g) || []).length, 1);
  assert.match(html, /Успехов: 2/);
  assert.match(html, /aria-label="Выпало: 6, 5, 1, 2"/);
});

test("предел, порог, риск и глитч показываются", () => {
  const html = dice.rollHTML(roll({ limit: 1, counted: 1, threshold: 2, success: false, glitch: "critical", edge: false }));
  assert.match(html, /с учётом предела 1: <b>1<\/b>/);
  assert.match(html, /порог 2: <b class="roll-fail">провал/);
  assert.match(html, /критический глитч/);
  const edge = dice.rollHTML(roll({ edge: true, limit: 3, extra: [6, 2], hits: 3, counted: 3, dice: [6, 5, 1, 6] }));
  assert.match(edge, /с риском/);
  assert.match(edge, /предел не действует/);
  assert.match(edge, /class="die hit extra"/);
  assert.ok(!/glitch/.test(dice.rollHTML(roll())) && !/глитч/.test(dice.rollHTML(roll())));
});

test("метка броска экранируется", () => {
  const html = dice.rollHTML(roll({ label: '<img src=x onerror=alert(1)>"' }));
  assert.ok(!html.includes("<img"));
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;&quot;/);
});
