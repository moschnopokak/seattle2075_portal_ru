// Тесты импорта мест (static/js/import.js): поиск дублей, пересчёт координат из KML, разбор файла KML. Без браузера.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const imp = require("../../static/js/import.js");
const grid = JSON.parse(fs.readFileSync(path.join(__dirname, "../../static/map/llgrid.json"), "utf8"));
const W = 125000, H = 150000;

test("слова для сравнения названий: короткие и служебные отбрасываются, регистр не важен", () => {
  assert.deepEqual([...imp.impWords("Штаб Баргест, больница The Clinic")].sort(), ["clinic", "баргест"]);
  assert.deepEqual([...imp.impWords("ЦЕНТР Ренраку")].sort(), ["ренраку", "центр"]);
  assert.equal(imp.impWords("а б в").size, 0);
});

const P = [{ name: "АЧЕ, бывшая аркология Ренраку", x: 36000, y: 52000 }, { name: "Бар «Тузы»", x: 58000, y: 50000 }];

test("дубль по ключевым словам набора («same»), где бы место ни стояло", () => {
  assert.match(imp.impDup({ name: "Arcology", x: 1, y: 1, same: [["АЧЕ"]] }, P), /уже на карте: «АЧЕ/);
  assert.match(imp.impDup({ name: "X", x: 1, y: 1, same: [["аркологи"], ["нет"]] }, P), /уже на карте/);
  assert.equal(imp.impDup({ name: "X", x: 1, y: 1, same: [["аче", "нет-такого"]] }, P), "");          // нужны ВСЕ слова ключа
});

test("дубль по названию рядом, по похожему названию и по месту", () => {
  assert.match(imp.impDup({ name: "бар «тузы»", x: 58400, y: 50000 }, P), /^уже на карте «Бар «Тузы»», 400 м$/);
  assert.match(imp.impDup({ name: "Новый тузы-клуб", x: 58100, y: 50100 }, P), /^рядом уже есть «Бар «Тузы»», 141 м$/);   // общее слово и рядом
  assert.equal(imp.impDup({ name: "Новый тузы-клуб", x: 58400, y: 50000 }, P), "");                   // общее слово, но далеко (400 м)
  assert.match(imp.impDup({ name: "Совсем другое", x: 58010, y: 50010 }, P), /^рядом уже есть/);      // та же точка, любое название
  assert.equal(imp.impDup({ name: "Совсем другое", x: 70000, y: 70000 }, P), "");
  assert.equal(imp.impDup({ name: "Что-то", x: 1, y: 1 }, []), "");
});

test("координаты: узел сетки переходит в свои значения (с погрешностью в метр от чисел с плавающей точкой), середина клетки в среднее четырёх углов", () => {
  const { lon0, lat0, step, nx } = grid, i = 20, j = 25, at = (a, ii, jj) => a[jj * nx + ii];
  const [x, y] = imp.llToXY(lon0 + i * step, lat0 + j * step, grid, 10 ** 7, 10 ** 7);
  assert.ok(Math.abs(x - at(grid.x, i, j)) <= 1 && Math.abs(y - at(grid.y, i, j)) <= 1, `${x},${y}`);
  const mid = imp.llToXY(lon0 + (i + 0.5) * step, lat0 + (j + 0.5) * step, grid, 10 ** 7, 10 ** 7);
  const avg = (a) => Math.round((at(a, i, j) + at(a, i + 1, j) + at(a, i, j + 1) + at(a, i + 1, j + 1)) / 4);
  assert.ok(Math.abs(mid[0] - avg(grid.x)) <= 1 && Math.abs(mid[1] - avg(grid.y)) <= 1, mid.join());
});

test("координаты: за краем сетки или карты возвращается null", () => {
  const { lon0, lat0, step, nx, ny } = grid;
  assert.equal(imp.llToXY(lon0 - 0.01, lat0 + 0.5, grid, W, H), null);
  assert.equal(imp.llToXY(lon0 + (nx - 1) * step + 0.01, lat0 + 0.5, grid, W, H), null);
  assert.equal(imp.llToXY(lon0 + 0.5, lat0 + (ny - 1) * step + 0.01, grid, W, H), null);
  assert.equal(imp.llToXY(lon0 + 20 * step, lat0 + 25 * step, grid, 100, 100), null);               // внутри сетки, но за картой
});

const node = (i, j, d = 0.004) => `${grid.lon0 + i * grid.step + d},${grid.lat0 + j * grid.step + d},0`;
const KML = `<?xml version="1.0"?><kml><Document><name>Моя карта</name>
<Placemark><name>Без папки</name><Point><coordinates>${node(20, 25)}</coordinates></Point></Placemark>
<Folder><name><![CDATA[Бары &amp; клубы]]></name>
  <Placemark><name>Бар &quot;Ночь&quot;</name><description><![CDATA[Хорошее место<br>для встреч, &lt;b&gt;тихо&lt;/b&gt;]]></description><Point><coordinates> ${node(21, 26)} </coordinates></Point></Placemark>
  <Placemark><name>Линия, не точка</name><LineString><coordinates>${node(21, 26)} ${node(22, 26)}</coordinates></LineString></Placemark>
  <Placemark><name>Далеко</name><Point><coordinates>10.0,10.0,0</coordinates></Point></Placemark>
</Folder>
<Folder><name></name><Placemark><Point><coordinates>${node(22, 27)}</coordinates></Point></Placemark></Folder>
</Document></kml>`;

test("KML: точки, слои, очистка текста, пропуск линий и точек за картой", () => {
  const r = imp.kmlItems(KML, grid, 10 ** 7, 10 ** 7);
  assert.equal(r.skipped, 1);
  assert.equal(r.items.length, 3);
  const [a, b, c] = r.items;
  assert.deepEqual([a.name, a.group, a.id, a.type, a.rec, a.same], ["Без папки", "Без слоя", "k0", "other", true, []]);
  assert.deepEqual([b.name, b.group, b.id], ['Бар "Ночь"', "Бары & клубы", "k1"]);
  assert.equal(b.gm_note, "Из KML: Хорошее место для встреч, <b>тихо</b>");                         // теги из CDATA убраны (<br> стал пробелом), а экранированное &lt;b&gt; осталось текстом
  assert.deepEqual([c.name, c.group], ["Без названия", "Слой 2"]);                                  // пустое имя слоя и точки
  for (const it of r.items) assert.ok(Number.isInteger(it.x) && Number.isInteger(it.y));
  assert.deepEqual([a.x, a.y], imp.llToXY(grid.lon0 + 20 * grid.step + 0.004, grid.lat0 + 25 * grid.step + 0.004, grid, 10 ** 7, 10 ** 7));
});

test("KML: пустой и чужой текст не ломают разбор, длинные поля обрезаются", () => {
  assert.deepEqual(imp.kmlItems("", grid, W, H), { items: [], skipped: 0 });
  assert.deepEqual(imp.kmlItems("<html>не KML</html>", grid, W, H), { items: [], skipped: 0 });
  const long = `<Placemark><name>${"я".repeat(500)}</name><description>${"д".repeat(5000)}</description><Point><coordinates>${node(20, 25)}</coordinates></Point></Placemark>`;
  const [it] = imp.kmlItems(long, grid, 10 ** 7, 10 ** 7).items;
  assert.equal(it.name.length, 80);
  assert.equal(it.gm_note.length, 2000);
});

test("KMZ (архив) отличается от KML по первым байтам", () => {
  assert.equal(imp.impIsKmz(new Uint8Array([0x50, 0x4b, 3, 4])), true);
  assert.equal(imp.impIsKmz(new TextEncoder().encode("<?xm")), false);
  assert.equal(imp.impIsKmz(new Uint8Array([])), false);
});

test("порядок групп в списке: известные первыми, остальные в конце", () => {
  assert.equal(imp.IMP_ORDER[0], "Корпорации");
  assert.ok(imp.IMP_ORDER.includes("Фон: еда") && imp.IMP_ORDER.includes("Внутри стены Догтауна"));
});
