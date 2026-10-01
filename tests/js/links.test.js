// Тесты ссылок [[Имя]] на карточки досье (static/js/links.js): разбор, поиск карточки, упоминания, подмена для бота.
const test = require("node:test");
const assert = require("node:assert/strict");
const links = require("../../static/js/links.js");

const cards = [
  { id: "c1", name: "Ёжик Мак-Грегор", alias: "Колючка" },
  { id: "c2", name: "Бар «Мост»", alias: "" },
  { id: "c3", name: "Колючка", alias: "" },            // имя совпадает с чужим позывным
];

test("текст без ссылок остаётся одним куском", () => {
  assert.deepEqual(links.linkSegments("просто текст"), [{ text: "просто текст" }]);
  assert.deepEqual(links.linkSegments(""), []);
  assert.deepEqual(links.linkSegments(null), []);
});

test("ссылки режут текст на куски, подпись после |", () => {
  assert.deepEqual(links.linkSegments("Встреча с [[Ёжик Мак-Грегор]] у [[Бар «Мост»|моста]]."), [
    { text: "Встреча с " }, { name: "Ёжик Мак-Грегор", label: "Ёжик Мак-Грегор" },
    { text: " у " }, { name: "Бар «Мост»", label: "моста" }, { text: "." }]);
});

test("ссылка в самом начале и в самом конце, две подряд", () => {
  assert.deepEqual(links.linkSegments("[[А]][[Б]]"), [{ name: "А", label: "А" }, { name: "Б", label: "Б" }]);
  assert.deepEqual(links.linkSegments("[[А]] и"), [{ name: "А", label: "А" }, { text: " и" }]);
});

test("неправильные скобки ссылками не считаются", () => {
  for (const bad of ["[[]]", "[[ ]] ", "[Имя]", "[[Имя]", "[[Имя\nс переносом]]", "[[" + "я".repeat(61) + "]]", "[[[[вложенная]]]]x"]) {
    const segs = links.linkSegments(bad).filter((s) => s.name !== undefined);
    if (bad === "[[ ]] ") assert.equal(segs[0].name, "");               // пробелы: имя пустое, карточка по нему не найдётся
    else if (bad === "[[[[вложенная]]]]x") assert.deepEqual(segs.map((s) => s.name), ["вложенная"]);
    else assert.deepEqual(segs, [], bad);
  }
  assert.equal(links.findCard("", cards), null);
  assert.equal(links.findCard("   ", cards), null);
});

test("поиск без учёта регистра, ё и лишних пробелов; имя важнее позывного", () => {
  assert.equal(links.findCard("ежик  мак-грегор", cards).id, "c1");
  assert.equal(links.findCard("БАР «МОСТ»", cards).id, "c2");
  assert.equal(links.findCard("колючка", cards).id, "c3");               // и имя, и позывной: выигрывает имя
  assert.equal(links.findCard("Никто", cards), null);
});

test("позывной находит карточку, если имени с таким названием нет", () => {
  assert.equal(links.findCard("колючка", [cards[0]]).id, "c1");
});

test("упоминания: только источники, где ссылка ведёт на эту карточку", () => {
  const sources = [
    { key: "e:1", texts: ["Идём к [[Бар «Мост»]]"] },
    { key: "e:2", texts: ["без ссылок", "ещё [[Ёжик Мак-Грегор|Ёж]]"] },
    { key: "e:3", texts: ["[[Никто]]"] },
    { key: "e:4", texts: [undefined, null, "Бар «Мост» без скобок"] },
  ];
  assert.deepEqual(links.mentionsOf(cards[1], cards, sources).map((s) => s.key), ["e:1"]);
  assert.deepEqual(links.mentionsOf(cards[0], cards, sources).map((s) => s.key), ["e:2"]);
  assert.deepEqual(links.mentionsOf(cards[0], cards.slice(1), sources), []);        // карточка скрыта от смотрящего: найти не по чему
});

test("упоминание не засчитывается карточке, которая закрыта поиском на имя-двойник", () => {
  const sources = [{ key: "e:1", texts: ["[[Колючка]]"] }];
  assert.deepEqual(links.mentionsOf(cards[2], cards, sources).map((s) => s.key), ["e:1"]);   // c3 по имени
  assert.deepEqual(links.mentionsOf(cards[0], cards, sources), []);                          // c1 по позывному: имя c3 выигрывает
});

test("для бота ссылки превращаются в имя или подпись", () => {
  assert.equal(links.stripLinks("К [[Бар «Мост»]] и [[Ёжик|Ёжу]]!"), "К Бар «Мост» и Ёжу!");
  assert.equal(links.stripLinks("без ссылок"), "без ссылок");
});

test("regexp не виснет на длинных вредных строках", () => {
  const evil = "[[" + "а".repeat(50000);
  const t0 = Date.now();
  links.linkSegments(evil);
  links.linkSegments("[[".repeat(20000));
  assert.ok(Date.now() - t0 < 500, "разбор должен быть линейным");
});
