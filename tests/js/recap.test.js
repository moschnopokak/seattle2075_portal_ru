// Тесты выбора периода для пересказа (static/js/recap.js).
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { UI: {}, esc: util.esc });
const recap = require("../../static/js/recap.js");

const past = [
  { id: "p3", from: "2075-07-27", to: "2075-07-27", title: "в", session: "Сессия 3" },
  { id: "p1", from: "2075-07-10", to: "2075-07-10", title: "а", session: "Сессия 1" },
  { id: "p2", from: "2075-07-20", to: "2075-07-21", title: "б", session: " Сессия 2 " },
  { id: "p2b", from: "2075-07-22", to: "2075-07-22", title: "б2", session: "Сессия 2" },
  { id: "px", from: "2075-07-25", to: "2075-07-25", title: "без сессии" },
];

test("сессии идут по первой дате, пустые подписи пропускаются, пробелы убираются", () => {
  assert.deepEqual(recap.recapSessions(past), [
    { label: "Сессия 1", from: "2075-07-10" }, { label: "Сессия 2", from: "2075-07-20" }, { label: "Сессия 3", from: "2075-07-27" }]);
  assert.deepEqual(recap.recapSessions([]), []);
  assert.deepEqual(recap.recapSessions(undefined), []);
});

test("варианты: последняя сессия, две последние, неделя", () => {
  const p = recap.recapPresets(past, "2075-08-01", util.addDays);
  assert.deepEqual(p.map((x) => [x.id, x.since]), [["last", "2075-07-27"], ["two", "2075-07-20"], ["week", "2075-07-25"]]);
  assert.match(p[0].label, /Сессия 3/);
  assert.match(p[1].label, /Сессия 2/);
});

test("с одной сессией «две последние» нет, без сессий остаётся неделя", () => {
  assert.deepEqual(recap.recapPresets([past[1]], "2075-08-01", util.addDays).map((x) => x.id), ["last", "week"]);
  assert.deepEqual(recap.recapPresets([], "2075-08-01", util.addDays).map((x) => x.id), ["week"]);
});

test("дата не позже сегодняшней", () => {
  const p = recap.recapPresets([{ from: "2075-09-01", session: "Из будущего" }], "2075-08-01", util.addDays);
  assert.equal(p[0].since, "2075-08-01");
});

test("напоминание об отправке в Anthropic есть", () => {
  assert.match(recap.RECAP_NOTE, /Anthropic/);
});

test("в режиме «через мастера» заметка говорит, что пересказ готовит мастер и что он видит то же, что игрок", () => {
  assert.match(recap.RECAP_NOTE_GM, /готовит мастер/);
  assert.match(recap.RECAP_NOTE_GM, /видит ровно то, что видите вы/);
  assert.doesNotMatch(recap.RECAP_NOTE_GM, /Anthropic/);                          // ничего никуда не отправляется
});

test("строка о просьбе: ждёт, готов, отказ с причиной и без", () => {
  const fmt = (d) => `«${d}»`;
  assert.deepEqual(recap.recapRequestLine({ status: "open", since: "2075-07-20" }, fmt), { tone: "wait", text: "ждёт мастера, с «2075-07-20»" });
  assert.deepEqual(recap.recapRequestLine({ status: "done", since: "2075-07-20", text: "Длинный текст" }, fmt), { tone: "ok", text: "пересказ готов, с «2075-07-20»" });
  assert.deepEqual(recap.recapRequestLine({ status: "declined", since: "2075-07-20", text: "Расскажу на игре" }, fmt), { tone: "no", text: "мастер пока не может, с «2075-07-20»: Расскажу на игре" });
  assert.equal(recap.recapRequestLine({ status: "declined", since: "2075-07-20", text: "" }, fmt).text, "мастер пока не может, с «2075-07-20»");
  assert.equal(recap.recapRequestLine({ status: "open", since: "2075-07-20" }).text, "ждёт мастера, с 2075-07-20");
});

test("подпись кнопки: ответ готов важнее ожидания, вне режима «через мастера» подписи не меняются", () => {
  assert.equal(recap.recapButtonLabel({ recap_mode: "gm", recap_ready: 1, recap_open: 1 }), "Что было раньше (ответ готов)");
  assert.equal(recap.recapButtonLabel({ recap_mode: "gm", recap_ready: 0, recap_open: 2 }), "Что было раньше (ждёт мастера)");
  assert.equal(recap.recapButtonLabel({ recap_mode: "gm", recap_ready: 0, recap_open: 0 }), "Что было раньше");
  assert.equal(recap.recapButtonLabel({ recap_mode: "api", recap_ready: 3, recap_open: 3 }), "Что было раньше");
  assert.equal(recap.recapButtonLabel(undefined), "Что было раньше");
});
