// Тесты «кто свободен» (static/js/free.js): чистые функции без браузера.
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { wdi: util.wdi, dOf: util.dOf, addDays: util.addDays });   // free.js берёт их из общей области, как в браузере
const free = require("../../static/js/free.js");

const meet = (o) => ({ id: "e" + Math.random(), type: "meet", author: "gate", who: ["gate", "rig"], from: "2075-08-05", to: "2075-08-05",
  tod: "вечер", status: "ok", answers: { rig: "да" }, title: "Встреча", ...o });
const D = (entries = [], blocks = [], rhythm = []) => ({ entries, blocks, rhythm });

test("свободен, когда ничего нет", () => {
  assert.deepEqual(free.busyReasons("rig", "2075-08-05", "вечер", D()), []);
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", D()).status, "free");
});

test("встреча занимает участников и автора", () => {
  const d = D([meet()]);
  for (const c of ["gate", "rig"]) assert.equal(free.busyReport(c, "2075-08-05", "2075-08-05", "вечер", d).status, "busy");
  assert.equal(free.busyReport("karu", "2075-08-05", "2075-08-05", "вечер", d).status, "free");
});

test("время суток: другое время того же дня свободно, не указано занимает всё", () => {
  const d = D([meet()]);
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "утро", d).status, "free");
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "", d).status, "busy");          // «любое время» пересекается
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", d).status, "busy");
  const allDay = D([meet({ tod: "" })]);
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "утро", allDay).status, "busy");  // запись без времени суток занимает весь день
});

test("границы дат включаются, соседние дни свободны", () => {
  const d = D([meet({ from: "2075-08-05", to: "2075-08-07", tod: "" })]);
  const st = (day) => free.busyReport("rig", day, day, "", d).status;
  assert.deepEqual(["2075-08-04", "2075-08-05", "2075-08-06", "2075-08-07", "2075-08-08"].map(st), ["free", "busy", "busy", "busy", "free"]);
});

test("отказавшийся, закрытые записи, развитие и обещания не занимают", () => {
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", D([meet({ answers: { rig: "нет" } })])).status, "free");
  for (const status of ["done", "failed", "rejected"]) assert.equal(free.busyReport("gate", "2075-08-05", "2075-08-05", "вечер", D([meet({ status })])).status, "free");
  for (const type of ["grow", "vow"]) assert.equal(free.busyReport("gate", "2075-08-05", "2075-08-05", "вечер", D([meet({ type })])).status, "free");
  assert.equal(free.busyReport("gate", "2075-08-05", "2075-08-05", "вечер", D([meet({ type: "deal" })])).status, "busy");      // дело занимает
});

test("приглашение без ответа и запись, которой нужна другая дата: возможно занят", () => {
  const waiting = D([meet({ status: "reply", answers: { rig: "ждёт" } })]);
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", waiting).status, "maybe");
  assert.equal(free.busyReport("gate", "2075-08-05", "2075-08-05", "вечер", waiting).status, "busy");                          // автор занят наверняка
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", D([meet({ status: "resched" })])).status, "maybe");
  assert.match(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", waiting).reasons[0].why, /ответил/);
});

test("правимая запись себя не занимает", () => {
  const e = meet({ id: "mine" });
  const d = { ...D([e]), ignoreId: "mine" };
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "вечер", d).status, "free");
});

test("общее событие мастера: для всех или только для названных", () => {
  const all = { id: "b1", from: "2075-08-10", to: "2075-08-11", title: "Облава", who: [] };
  const some = { id: "b2", from: "2075-08-10", to: "2075-08-10", title: "Личное", who: ["rig"] };
  const d = D([], [all, some]);
  assert.equal(free.busyReport("karu", "2075-08-10", "2075-08-10", "утро", d).status, "busy");
  assert.equal(free.busyReport("karu", "2075-08-11", "2075-08-11", "утро", d).status, "busy");
  assert.equal(free.busyReport("karu", "2075-08-12", "2075-08-12", "утро", d).status, "free");
  assert.deepEqual(free.busyReport("rig", "2075-08-10", "2075-08-10", "", d).reasons.map((r) => r.title), ["Облава", "Личное"]);
  assert.deepEqual(free.busyReport("karu", "2075-08-10", "2075-08-10", "", d).reasons.map((r) => r.title), ["Облава"]);
});

test("привычка персонажа: возможно занят в её дни, чужая привычка не мешает", () => {
  const monday = (who) => ({ id: "h", title: "Дежурство", who, wd: [0], from: "", to: "" });
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "", D([], [], [monday("rig")])).status, "maybe");     // 5 августа 2075 понедельник
  assert.equal(free.busyReport("rig", "2075-08-06", "2075-08-06", "", D([], [], [monday("rig")])).status, "free");
  assert.equal(free.busyReport("karu", "2075-08-05", "2075-08-05", "", D([], [], [monday("rig")])).status, "free");
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "", D([], [], [monday("")])).status, "free");        // событие города привычкой не считается
  const monthly = { id: "m", title: "Выплата", who: "rig", monthDay: 15, from: "2075-09-01", to: "2075-09-30" };
  assert.equal(free.busyReport("rig", "2075-09-15", "2075-09-15", "", D([], [], [monthly])).status, "maybe");
  assert.equal(free.busyReport("rig", "2075-08-15", "2075-08-15", "", D([], [], [monthly])).status, "free");           // до начала действия
});

test("период из нескольких дней собирает причины и дни", () => {
  const d = D([meet({ from: "2075-08-06", to: "2075-08-07", tod: "" })]);
  const rep = free.busyReport("rig", "2075-08-05", "2075-08-08", "", d);
  assert.equal(rep.status, "busy");
  assert.equal(rep.reasons.length, 1);
  assert.deepEqual(rep.reasons[0].days, ["2075-08-06", "2075-08-07"]);
});

test("ближайшие дни, когда свободны все", () => {
  const d = D([meet({ from: "2075-08-05", to: "2075-08-06", tod: "" })], [{ id: "b", from: "2075-08-08", to: "2075-08-08", title: "Облава", who: [] }]);
  const res = free.freeStarts(["gate", "rig"], "2075-08-04", 1, "", d, "2075-12-31", 3);
  assert.deepEqual(res.free, ["2075-08-04", "2075-08-07", "2075-08-09"]);
});

test("для периода из нескольких дней ищется окно целиком", () => {
  const d = D([meet({ from: "2075-08-06", to: "2075-08-06", tod: "" })]);
  const res = free.freeStarts(["rig"], "2075-08-04", 3, "", d, "2075-12-31", 2);
  assert.deepEqual(res.free, ["2075-08-07", "2075-08-08"]);                       // окна 4–6 и 5–7 и 6–8 задевают 6-е
});

test("если свободных дней нет, остаются «возможно»; календарь не переступается", () => {
  const waiting = [];
  for (let i = 0; i < 70; i++) waiting.push(meet({ from: util.addDays("2075-08-01", i), to: util.addDays("2075-08-01", i), tod: "", status: "reply", answers: { rig: "ждёт" }, author: "gate", who: ["gate", "rig"] }));
  const res = free.freeStarts(["rig"], "2075-08-01", 1, "", D(waiting), "2075-12-31", 3);
  assert.deepEqual(res.free, []);
  assert.equal(res.maybe.length, 3);
  const edge = free.freeStarts(["rig"], "2075-12-30", 3, "", D(), "2075-12-31");
  assert.deepEqual(edge.free, []);                                                  // трёхдневное окно в конец календаря не влезает
});

test("пустые и неполные данные не роняют расчёт", () => {
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "", {}).status, "free");
  const odd = { entries: [{ id: "x", type: "meet", status: "ok", from: "2075-08-05", who: null, author: "rig" }], blocks: [{ from: "2075-08-05", to: "2075-08-05", title: "t" }], rhythm: [{ who: "rig", wd: null, monthDay: 0 }] };
  assert.equal(free.busyReport("rig", "2075-08-05", "2075-08-05", "", odd).status, "busy");
});
