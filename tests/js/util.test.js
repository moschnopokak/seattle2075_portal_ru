// Тесты чистых функций интерфейса (даты, экранирование, склонения).
const test = require("node:test");
const assert = require("node:assert/strict");
const u = require("../../static/js/util.js");

test("даты: разбор, добавление дней, день недели по настоящему календарю", () => {
  assert.equal(u.fromT(u.toT("2075-08-01")), "2075-08-01");
  assert.equal(u.addDays("2075-08-31", 1), "2075-09-01");
  assert.equal(u.addDays("2075-01-01", -1), "2074-12-31");
  assert.equal(u.addDays("2075-02-27", 2), "2075-03-01");           // 2075 не високосный
  assert.equal(u.wdi("2075-08-01"), 3);                              // четверг
  assert.equal(u.wdi("2075-08-04"), 6);                              // воскресенье
});

test("даты: форматирование", () => {
  assert.equal(u.fDate("2075-08-01"), "1 августа");
  assert.equal(u.fDate("2076-01-05"), "5 января 2076");
  assert.equal(u.fFull("2075-08-01"), "чт, 1 августа");
  assert.equal(u.fSpan("2075-08-01", "2075-08-01"), u.fFull("2075-08-01"));
  assert.equal(u.fSpan("2075-08-01", "2075-08-03"), "чт, 1 августа – сб, 3 августа");
  assert.equal(u.fRange("2075-08-01", "2075-08-03"), "1–3 августа");
  assert.equal(u.fRange("2075-08-30", "2075-09-02"), "30 августа – 2 сентября");
});

test("range даёт все дни включительно", () => {
  assert.deepEqual(u.range("2075-08-30", "2075-09-02"), ["2075-08-30", "2075-08-31", "2075-09-01", "2075-09-02"]);
  assert.deepEqual(u.range("2075-08-01", "2075-08-01"), ["2075-08-01"]);
  assert.deepEqual(u.range("2075-08-02", "2075-08-01"), []);
});

test("границы календаря: clampDate и buildMonths", () => {
  u.setCalendar("2075-07-01", "2075-12-31");
  assert.equal(u.clampDate("2075-06-01"), "2075-07-01");
  assert.equal(u.clampDate("2076-01-01"), "2075-12-31");
  assert.equal(u.clampDate("2075-09-09"), "2075-09-09");
  assert.deepEqual(u.buildMonths(), ["2075-07", "2075-08", "2075-09", "2075-10", "2075-11", "2075-12"]);
  u.setCalendar("2075-11-15", "2076-02-01");
  assert.deepEqual(u.buildMonths(), ["2075-11", "2075-12", "2076-01", "2076-02"]);
  u.setCalendar("2075-07-01", "2075-12-31");
});

test("esc экранирует всё опасное и не ломает null", () => {
  assert.equal(u.esc('<img src=x onerror="a()">'), "&lt;img src=x onerror=&quot;a()&quot;&gt;");
  assert.equal(u.esc("it's & <b>"), "it&#39;s &amp; &lt;b&gt;");
  assert.equal(u.esc(null), "");
  assert.equal(u.esc(undefined), "");
  assert.equal(u.esc(0), "0");
  for (const bad of ["<", ">", '"', "'"]) assert.ok(!u.esc(`a${bad}b`).includes(bad));
});

test("plural и joinNames", () => {
  const f = (n) => u.plural(n, "запись", "записи", "записей");
  assert.deepEqual([1, 2, 5, 11, 12, 14, 21, 22, 25, 101, 111].map(f),
    ["запись", "записи", "записей", "записей", "записей", "записей", "запись", "записи", "записей", "запись", "записей"]);
  assert.equal(u.joinNames([]), "");
  assert.equal(u.joinNames(["Риг"]), "Риг");
  assert.equal(u.joinNames(["Риг", "Гейт"]), "Риг и Гейт");
  assert.equal(u.joinNames(["Риг", "Гейт", "Кару"]), "Риг, Гейт и Кару");
  assert.equal(u.cap("четверг"), "Четверг");
});

test("что видят игроки вперёд: строки панели мастера", () => {
  const fmt = (d) => `«${d}»`;
  assert.equal(u.horizonLine(undefined, fmt), "");
  assert.equal(u.horizonLine({ mode: "window", until: "2075-08-31", window: "Промежуточная арка", hidden: { entries: 1, blocks: 2, rhythm: 5, handouts: 0 } }, fmt),
    "Игроки видят календарь до «2075-08-31» («Промежуточная арка»). Скрыто от них: 1 запись, 2 общих события, 5 регулярных событий.");
  assert.equal(u.horizonLine({ mode: "window", until: "2075-08-31", window: "", hidden: {} }, fmt), "Игроки видят календарь до «2075-08-31». Пока ничего не скрыто.");
  assert.match(u.horizonLine({ mode: "window", until: "", hidden: {} }, fmt), /не входит ни в один этап/);
  assert.match(u.horizonLine({ mode: "off", until: "2075-08-31", window: "Этап" }, fmt), /до конца кампании.*будут видеть до «2075-08-31» \(«Этап»\)/);
  assert.equal(u.horizonLine({ mode: "off", until: "" }, fmt), "Игроки видят календарь до конца кампании.");
});

test("счёт скрытого склоняется: одна запись, две записи, пять записей, двадцать одна запись", () => {
  const c = (n) => u.horizonCounts({ entries: n });
  assert.deepEqual([1, 2, 5, 11, 21, 22].map(c), ["1 запись", "2 записи", "5 записей", "11 записей", "21 запись", "22 записи"]);
  assert.equal(u.horizonCounts({}), "");
  assert.equal(u.horizonCounts({ handouts: 3, entries: 0 }), "3 раздатки");
});
