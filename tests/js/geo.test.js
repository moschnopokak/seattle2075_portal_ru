// Тесты геометрии и маршрутов (static/js/geo.js): на маленьких сетях с точным ответом и на настоящей карте.
const test = require("node:test");
const assert = require("node:assert/strict");
const geo = require("../../static/js/geo.js");
const map = require("../../static/map/map.json");

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);
const roads = (m = [], t = [], p = []) => ({
  motorway: { coordinates: m }, trunk: { coordinates: t }, primary: { coordinates: p },
});
const CAR = { off: 20, motorway: 60, trunk: 60, primary: 60, delay: 0, wall: 0 };

test("pip: точка в полигоне, в дыре и вне", () => {
  const g = { type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]] };
  assert.equal(geo.pip(2, 2, g), true);
  assert.equal(geo.pip(5, 5, g), false);   // дыра
  assert.equal(geo.pip(20, 5, g), false);
});

test("geoProject: проекция на отрезок и на его концы", () => {
  const p = geo.geoProject(5, 3, 0, 0, 10, 0);
  assert.deepEqual([p.px, p.py, p.d, p.t], [5, 0, 3, 0.5]);
  const e = geo.geoProject(-5, 0, 0, 0, 10, 0);
  assert.deepEqual([e.px, e.t, e.d], [0, 0, 5]);
});

test("маршрут по Г-образной дороге: расстояние и время точные", () => {
  const g = geo.buildRoadGraph(roads([[[0, 0], [10000, 0], [10000, 10000]]]));
  const r = geo.planTrip([[0, 0], [10000, 10000]], CAR, { graph: g });
  near(r.meters, 20000);
  near(r.minutes, 20);                       // 20 км со скоростью 60 км/ч
  near(r.roadMeters[0], 20000);
  assert.equal(r.fallback, false);
  assert.deepEqual(r.path[0], [0, 0]);
  assert.deepEqual(r.path[r.path.length - 1], [10000, 10000]);
});

test("точки в стороне от дороги: добавляется путь вне дорог", () => {
  const g = geo.buildRoadGraph(roads([[[0, 0], [10000, 0]]]));
  const r = geo.planTrip([[0, 1000], [10000, -2000]], CAR, { graph: g });
  near(r.offMeters, 3000);
  near(r.meters, 13000);
  near(r.minutes, 10000 / 1000 + 3000 / (20 * 1000 / 60) / 1);   // 10 мин по дороге + 9 мин вне дорог
});

test("обе точки на одном ребре: едем напрямую по нему", () => {
  const g = geo.buildRoadGraph(roads([[[0, 0], [10000, 0]]]));
  const r = geo.routeOnRoads(g, [2000, 0], [7000, 0], CAR);
  near(r.meters, 5000);
  assert.equal(r.fallback, false);
});

test("быстрее не значит короче: выбирается путь по времени", () => {
  // короткий путь по медленной дороге (8 км) против длинного по скоростной (12 км)
  const slow = [[0, 0], [8000, 0]];
  const fast = [[0, 0], [0, 6000], [8000, 6000], [8000, 0]];
  const g = geo.buildRoadGraph(roads([fast], [], [slow]));
  const car = { ...CAR, motorway: 120, primary: 20 };
  const r = geo.planTrip([[0, 0], [8000, 0]], car, { graph: g });
  assert.ok(r.roadMeters[0] > 0 && r.roadMeters[2] === 0, "ожидался объезд по скоростной");
  const walk = { off: 5, motorway: 5, trunk: 5, primary: 5, delay: 0, wall: 0 };
  const w = geo.planTrip([[0, 0], [8000, 0]], walk, { graph: g });
  near(w.meters, 8000);                      // пешком одинаково везде, значит по кратчайшему
});

test("скорость 0 на классе дорог закрывает его; нет пути: по прямой с пометкой", () => {
  const g = geo.buildRoadGraph(roads([[[0, 0], [10000, 0]]]));
  const bike = { off: 12, motorway: 0, trunk: 15, primary: 15, delay: 0, wall: 0 };
  const r = geo.planTrip([[0, 0], [10000, 0]], bike, { graph: g });
  assert.equal(r.fallback, true);
  near(r.meters, 10000);
  near(r.minutes, 10000 / (12 * 1000 / 60));
});

test("дорога дальше предела: по прямой", () => {
  const g = geo.buildRoadGraph(roads([[[0, 0], [1000, 0]]]));
  const r = geo.planTrip([[0, 50000], [1000, 50000]], CAR, { graph: g });
  assert.equal(r.fallback, true);
});

test("близкие вершины склеиваются, висячие концы соединяются мостом", () => {
  const joined = geo.buildRoadGraph(roads([[[0, 0], [5000, 0]]], [], [[[5010, 0], [10000, 0]]]));       // зазор 10 м
  near(geo.planTrip([[0, 0], [10000, 0]], CAR, { graph: joined }).minutes, 10, 0.1);
  const bridged = geo.buildRoadGraph(roads([[[0, 0], [5000, 0]]], [], [[[5200, 0], [10000, 0]]]));     // зазор 200 м
  const r = geo.planTrip([[0, 0], [10000, 0]], CAR, { graph: bridged });
  assert.equal(r.fallback, false);
  const apart = geo.buildRoadGraph(roads([[[0, 0], [5000, 0]]], [], [[[5600, 0], [10000, 0]]]));       // зазор 600 м: не соединять
  assert.equal(geo.planTrip([[0, 0], [10000, 0]], CAR, { graph: apart }).fallback, true);
});

test("пересекающиеся без общей вершины дороги не соединяются", () => {
  const g = geo.buildRoadGraph(roads([[[0, 5000], [10000, 5000]]], [], [[[5000, 0], [5000, 10000]]]));   // «эстакада»
  const r = geo.planTrip([[0, 5000], [5000, 0]], CAR, { graph: g });
  assert.equal(r.fallback, true);                                  // связи нет: пути по дорогам не существует
  const crossing = geo.planTrip([[0, 5000], [10000, 5000]], CAR, { graph: g });
  assert.equal(crossing.fallback, false);                          // а вдоль одной дороги едем нормально
});

test("штраф за стену: только когда один конец внутри; задержка один раз", () => {
  const dog = { type: "Polygon", coordinates: [[[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]]] };
  const g = geo.buildRoadGraph(roads([[[500, 500], [20000, 500]]]));
  const p = { ...CAR, wall: 15, delay: 4 };
  const inOut = geo.planTrip([[500, 500], [20000, 500]], p, { graph: g, dogtown: dog });
  const outOut = geo.planTrip([[5000, 500], [20000, 500]], p, { graph: g, dogtown: dog });
  assert.equal(inOut.walls, 1);
  assert.equal(outOut.walls, 0);
  near(inOut.minutes, 19500 / 1000 + 15 + 4, 1e-6);
  near(outOut.minutes, 15000 / 1000 + 4, 1e-6);
  const through = geo.planTrip([[500, 500], [800, 800], [20000, 500]], p, { graph: g, dogtown: dog });
  assert.equal(through.walls, 1);                                  // внутри остались, вышли один раз
  assert.equal(through.legs.length, 2);
});

test("прямая линия: вертолёт и режим «по прямой»", () => {
  const heli = { kind: "straight", off: 120, motorway: 0, trunk: 0, primary: 0, delay: 6, wall: 0 };
  const r = geo.planTrip([[0, 0], [3000, 4000]], heli, { graph: null });
  near(r.meters, 5000);
  near(r.minutes, 5000 / 2000 + 6);
  const g = geo.buildRoadGraph(roads([[[0, 0], [10000, 0]]]));
  const s = geo.planTrip([[0, 0], [3000, 4000]], CAR, { graph: g, straight: true });
  near(s.meters, 5000);
  assert.equal(s.roadMeters.reduce((a, b) => a + b, 0), 0);
});

test("форматирование расстояний и времени", () => {
  assert.equal(geo.formatKm(450), "450 м");
  assert.equal(geo.formatKm(1234), "1,2 км");
  assert.equal(geo.formatKm(12400), "12 км");
  assert.equal(geo.formatMinutes(0.4), "меньше минуты");
  assert.equal(geo.formatMinutes(7), "7 мин");
  assert.equal(geo.formatMinutes(62), "1 ч");                   // от получаса округляется до пяти минут
  assert.equal(geo.formatMinutes(95), "1 ч 35 мин");
  assert.equal(geo.formatMinutes(1500), "1 д 1 ч");
  assert.equal(geo.formatMinutes(Infinity), "—");
});

// ---------- настоящая карта кампании ----------
const graph = geo.buildRoadGraph(map.roads);
const at = (slug) => map.labels.find((l) => l.slug === slug).xy;
const PROFILES = {
  walk: { off: 4.5, motorway: 5, trunk: 5, primary: 5, delay: 0, wall: 10 },
  car: { off: 20, motorway: 80, trunk: 60, primary: 40, delay: 3, wall: 20 },
  heli: { kind: "straight", off: 220, motorway: 0, trunk: 0, primary: 0, delay: 10, wall: 0 },
};
const dogtown = map.districts.dogtown;
const trip = (a, b, p, extra = {}) => geo.planTrip([at(a), at(b)], PROFILES[p], { graph, dogtown, ...extra });

test("карта: граф построен и почти вся сеть связна", () => {
  assert.ok(graph.n > 5000 && graph.ea.length > 6000);
  const parent = Array.from({ length: graph.n }, (_, i) => i);
  const find = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  for (let e = 0; e < graph.ea.length; e++) parent[find(graph.ea[e])] = find(graph.eb[e]);
  const len = new Map();
  for (let e = 0; e < graph.ea.length; e++) { const r = find(graph.ea[e]); len.set(r, (len.get(r) || 0) + graph.elen[e]); }
  const total = [...len.values()].reduce((a, b) => a + b, 0);
  assert.ok(Math.max(...len.values()) / total > 0.95, "крупнейшая связная часть меньше 95% дорог");
});

test("карта: Даунтаун → Эверетт по дорогам правдоподобен", () => {
  const car = trip("downtown", "everett", "car");
  assert.equal(car.fallback, false);
  assert.ok(car.meters > 38000 && car.meters < 60000, `расстояние ${car.meters}`);
  assert.ok(car.minutes > 30 && car.minutes < 90, `время ${car.minutes}`);
  assert.ok(car.roadMeters[0] > car.meters * 0.5, "большая часть пути должна идти по магистрали");
  const walk = trip("downtown", "everett", "walk");
  assert.ok(walk.minutes > 6 * 60, "пешком это долго");
  const heli = trip("downtown", "everett", "heli");
  const direct = geo.geoDist(at("downtown"), at("everett"));
  near(heli.meters, direct, 1e-6);
  assert.ok(heli.minutes < car.minutes);
});

test("карта: туда и обратно почти одинаково, ближе значит быстрее", () => {
  const ab = trip("downtown", "tacoma", "car"), ba = trip("tacoma", "downtown", "car");
  assert.ok(Math.abs(ab.minutes - ba.minutes) / ab.minutes < 0.05);
  assert.ok(Math.abs(ab.meters - ba.meters) / ab.meters < 0.05);
  assert.ok(trip("downtown", "bellevue", "car").minutes < ab.minutes);
});

test("карта: въезд в Догтаун даёт штраф за стену, а между районами снаружи нет", () => {
  const dog = trip("redmond", "dogtown", "car");
  assert.equal(dog.walls, 1);
  assert.equal(trip("redmond", "bellevue", "car").walls, 0);
  const noWall = geo.planTrip([at("redmond"), at("dogtown")], { ...PROFILES.car, wall: 0 }, { graph, dogtown });
  near(dog.minutes - noWall.minutes, 20, 1e-6);
});

test("карта: поиск ближайшей дороги и скорость расчёта", () => {
  const p = geo.nearestRoad(graph, ...at("downtown"));
  assert.ok(p && p.d < 3000);
  assert.equal(geo.nearestRoad(graph, -500000, -500000), null);
  const t0 = Date.now();
  for (let i = 0; i < 20; i++) trip("downtown", "tacoma", "car");
  assert.ok((Date.now() - t0) / 20 < 200, "один маршрут считается слишком долго");
});
