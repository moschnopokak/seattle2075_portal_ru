// Тесты загрузки разбора арки: поиск данных в ответе чата и строки отчёта (static/js/arcs.js).
const test = require("node:test");
const assert = require("node:assert/strict");

const util = require("../../static/js/util.js");
Object.assign(globalThis, { UI: {}, esc: util.esc });
const arcs = require("../../static/js/arcs.js");

const DATA = { plan: [{ title: "Ночной груз", from: "2075-08-22", to: "2075-08-22" }], questions: ["Верно?"] };
const JSON_TEXT = JSON.stringify(DATA, null, 2);

test("чистый JSON читается как есть", () => {
  assert.deepEqual(arcs.arcExtract(JSON_TEXT), { data: DATA });
  assert.deepEqual(arcs.arcExtract("  \n" + JSON_TEXT + "\n  "), { data: DATA });
});

test("данные берутся из блока кода посреди ответа чата", () => {
  const answer = `Часть А. Кратко об арке\nГруз и погоня.\n\nЧасть Б\n\`\`\`json\n${JSON_TEXT}\n\`\`\`\n\nЧасть В. Вопросы\n1. Верно?`;
  assert.deepEqual(arcs.arcExtract(answer), { data: DATA });
  assert.deepEqual(arcs.arcExtract("```\n" + JSON_TEXT + "\n```"), { data: DATA });                  // без подписи языка
  assert.deepEqual(arcs.arcExtract("```json " + JSON.stringify(DATA) + "```"), { data: DATA });      // в одну строку
});

test("из нескольких блоков берётся тот, где есть разделы разбора", () => {
  const answer = "```json\n{\"заметка\": 1}\n```\nи ещё\n```json\n" + JSON_TEXT + "\n```";
  assert.deepEqual(arcs.arcExtract(answer), { data: DATA });
  const python = "```python\nprint('привет')\n```\n```json\n" + JSON_TEXT + "\n```";
  assert.deepEqual(arcs.arcExtract(python), { data: DATA });
});

test("объект среди обычного текста без блока кода тоже находится", () => {
  assert.deepEqual(arcs.arcExtract("Вот данные: " + JSON.stringify(DATA) + " Надеюсь, подойдёт."), { data: DATA });
});

test("пустой текст, текст без данных и сломанные данные объясняются по-разному", () => {
  assert.match(arcs.arcExtract("").error, /Вставьте ответ/);
  assert.match(arcs.arcExtract("   \n ").error, /Вставьте ответ/);
  assert.match(arcs.arcExtract("Просто рассказ про арку, без данных.").error, /Не нашёл в тексте блок json/);
  const broken = arcs.arcExtract("```json\n{\"plan\": [{\"title\": \"без закрытия\"}\n```");
  assert.match(broken.error, /прочитать их не получилось/);
  assert.equal(broken.data, undefined);
});

test("не тот JSON не принимается: массив, объект без разделов, разделы не списками", () => {
  assert.match(arcs.arcExtract("[1, 2, 3]").error, /Не нашёл|прочитать/);
  assert.match(arcs.arcExtract('{"заметка": "привет"}').error, /прочитать/);
  assert.match(arcs.arcExtract('{"plan": "не список"}').error, /прочитать/);
  assert.deepEqual(arcs.arcExtract('{"plan": []}'), { data: { plan: [] } });                         // пустой список это ещё разбор: решит портал
});

test("все разделы, которые читает портал, перечислены", () => {
  assert.deepEqual([...arcs.ARC_KEYS].sort(), ["clocks", "dossier", "entries", "handouts", "past", "places", "plan", "rhythm", "windows"]);
});

const REPORT = {
  add: 3, merge: 1, skip: 1, error: 1,
  counts: { windows: { add: 0, merge: 0, skip: 0, error: 0 }, plan: { add: 2, merge: 0, skip: 0, error: 1 }, clocks: { add: 0, merge: 0, skip: 0, error: 0 },
            rhythm: { add: 0, merge: 0, skip: 0, error: 0 }, entries: { add: 0, merge: 0, skip: 0, error: 0 }, past: { add: 0, merge: 0, skip: 0, error: 0 },
            dossier: { add: 1, merge: 1, skip: 1, error: 0 }, places: { add: 0, merge: 0, skip: 0, error: 0 }, handouts: { add: 0, merge: 0, skip: 0, error: 0 } },
  items: [
    { kind: "plan", n: 1, title: "Груз <b>", status: "add", msg: "" },
    { kind: "plan", n: 2, title: "Погоня", status: "add", msg: "место «Склад» не найдено" },
    { kind: "plan", n: 3, title: "Вне календаря", status: "error", msg: "Дата: вне календаря кампании." },
    { kind: "dossier", n: 1, title: "Лу", status: "add", msg: "" },
    { kind: "dossier", n: 2, title: "Джонсон", status: "skip", msg: "карточка уже есть" },
    { kind: "dossier", n: 3, title: "Хансен", status: "merge", msg: "дополнится: сведений 3" },
  ],
  questions: ["Дата верна? <script>"],
};

test("итоговая строка: что добавится, что уже есть, что не пройдёт", () => {
  assert.equal(arcs.arcSummaryLine(REPORT), "Добавится: 3. Дополнится: 1. Уже есть: 1. Не пройдёт проверку: 1.");
  assert.equal(arcs.arcSummaryLine(REPORT, true), "Добавлено: 3. Дополнено: 1. Уже было: 1. Не добавлено: 1.");
  assert.equal(arcs.arcSummaryLine({ add: 4, skip: 0, error: 0 }), "Добавится: 4.");
});

test("разбивка по разделам идёт в порядке промпта и без пустых", () => {
  assert.equal(arcs.arcBreakdown(REPORT), "План мастера 2, Досье 1");
  assert.equal(arcs.arcBreakdown({ counts: {} }), "");
});

test("отчёт: разделы, статусы, кнопка с числом, всё из ответа выведено буквами", () => {
  const html = arcs.arcReportHTML(REPORT, false);
  assert.match(html, /Добавить 3 и дополнить 1/);
  assert.match(html, /data-act="arc-go"/);
  assert.match(html, /data-act="arc-back"/);
  assert.ok(html.indexOf("План мастера") < html.indexOf("Досье"));
  assert.match(html, /arc-row add/);
  assert.match(html, /arc-row error/);
  assert.match(html, /arc-row skip/);
  assert.match(html, /arc-row merge/);
  assert.match(html, /дополнится/);
  assert.match(html, /Карточки досье и места, которые уже есть, не заменяются, а дополняются/);
  assert.match(html, /не пройдёт/);
  assert.doesNotMatch(html, /<b>Груз <b>/);                                           // чужая разметка не ломает страницу
  assert.match(html, /Груз &lt;b&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /Дата верна\? &lt;script&gt;/);
});

test("подпись кнопки говорит, что именно она сделает", () => {
  assert.equal(arcs.arcGoLabel({ add: 5, merge: 0 }), "Добавить: 5");
  assert.equal(arcs.arcGoLabel({ add: 0, merge: 2 }), "Дополнить: 2");
  assert.equal(arcs.arcGoLabel({ add: 5, merge: 2 }), "Добавить 5 и дополнить 2");
  assert.match(arcs.arcReportHTML({ ...REPORT, add: 0 }, false), /Дополнить: 1/);                    // только дополнения: кнопка есть
});

test("отчёт без того, что можно добавить, не даёт нажать «Добавить»", () => {
  const html = arcs.arcReportHTML({ ...REPORT, add: 0, merge: 0, counts: {}, items: [REPORT.items[2]] }, false);
  assert.doesNotMatch(html, /data-act="arc-go"/);
  assert.match(html, /Добавлять нечего/);
});

test("после загрузки отчёт говорит в прошедшем времени и предлагает только закрыть", () => {
  const html = arcs.arcReportHTML(REPORT, true, "Добавлено: 3, пропущено: 2");
  assert.match(html, /Разбор арки загружен/);
  assert.match(html, /добавлено/);
  assert.match(html, /Игрокам ничего не отправлено/);
  assert.doesNotMatch(html, /arc-go/);
  assert.match(html, /data-act="close"/);
});
