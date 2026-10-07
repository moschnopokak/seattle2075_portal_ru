"""Импорт разбора арки: события, подготовленные в другом чате по промпту (см. ПРОМПТ_РАЗБОР_АРОК.md), загружаются на портал одной операцией.

Принимает тот же JSON, который просит промпт: разделы windows, plan, clocks, rhythm, entries, past, dossier, places, handouts и список вопросов.
Каждый элемент проходит ту же проверку, что и при ручном добавлении через форму. Что не прошло проверку, пропускается и называется в отчёте
(остальное добавляется). То, что уже есть на портале (то же название и те же даты), не дублируется, поэтому повторная загрузка того же разбора
безопасна. Существующие записи не затираются. Исключение одно, и оно только дополняет: если карточка досье или место с таким именем уже есть,
к ним добавляется то, чего в них ещё нет (новые сведения, заметка мастера), а остальные поля остаются как были; каждое такое дополнение
пишется в журнал отдельной записью и отменяется кнопкой «Вернуть как было». Игрокам при загрузке ничего не отправляется: ни уведомлений,
ни «общих событий» заранее.

Две вещи, которых в форме нет:
- места приходят без координат (только район и ориентир): они ставятся рядом с центром района, мастеру остаётся перетащить их кнопкой «Переместить»;
- записи календаря и раздатки ссылаются на место по названию (place_name): оно ищется среди мест карты и среди мест из этого же разбора.
Сначала отчёт (preview, ничего не пишет), потом запись (commit): запись заново проверяет всё на тот момент, поэтому отчёт при записи окончательный.
"""
import time
import uuid

from . import audit, db, logic
from .logic import bad, clean

MAX_TOTAL = 400                 # пунктов (событий, карточек, мест) за один раз
MAX_QUESTIONS = 30
PLACE_STEP = 700                # метров между местами, поставленными в один район
ENTRY_TYPES = ("meet", "deal", "vow")
MAX_FACTS = 80                  # столько сведений портал разрешает в одной карточке
NOTE_HEAD = "— Из разбора арки —"

# Порядок обработки: места раньше записей и раздаток, которые на них ссылаются
ORDER = ("places", "windows", "plan", "clocks", "rhythm", "past", "dossier", "handouts", "entries")
# Порядок и названия в отчёте (как в промпте)
LABELS = (("windows", "Этапы"), ("plan", "План мастера"), ("clocks", "Скрытые таймеры"), ("rhythm", "Регулярные события"),
          ("entries", "Записи календаря"), ("past", "Хроника"), ("dossier", "Досье"), ("places", "Места"), ("handouts", "Раздатки"))
TITLE_KEY = {"windows": "name", "plan": "title", "clocks": "title", "rhythm": "title", "entries": "title", "past": "title",
             "dossier": "name", "places": "name", "handouts": "title"}
LIST_KEYS = ("who", "known", "met")


def _district_centers():
    """Середины районов (по границам из static/map/map.json): куда ставятся места, у которых известен только район."""
    global _CENTERS
    if _CENTERS is None:
        import json
        centers = {}
        try:
            with open(logic.config.STATIC_DIR / "map" / "map.json", encoding="utf-8") as f:
                data = json.load(f)
            for slug, geo in data["districts"].items():
                coords = geo["coordinates"]
                points = coords[0] if geo["type"] == "Polygon" else [p for part in coords for p in part[0]]
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                centers[slug] = ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            centers = {}
        _CENTERS = centers
    return _CENTERS


_CENTERS = None


def _norm(name):
    return " ".join(str(name or "").lower().split())


def _unknown_chars(raw, chars):
    """Идентификаторы персонажей в списках элемента, которых нет в кампании (портал их просто отбросит)."""
    found = []

    def look(value):
        if isinstance(value, list):
            found.extend(x for x in value if isinstance(x, str) and x not in chars)

    for key in LIST_KEYS:
        look(raw.get(key))
    cover = raw.get("cover")
    if isinstance(cover, dict):
        look(cover.get("who"))
    for fact in raw.get("facts") if isinstance(raw.get("facts"), list) else []:
        if isinstance(fact, dict):
            look(fact.get("known"))
    who = raw.get("who")
    if isinstance(who, str) and who and who not in chars:
        found.append(who)
    return list(dict.fromkeys(found))


class _Run:
    """Один проход проверки: накапливает готовые к записи элементы и отчёт."""

    def __init__(self, v, data):
        if not v.gm:
            bad("Только для мастера.", 403)
        if not isinstance(data, dict):
            bad("Не нашёл разбор арки: нужен JSON с разделами (plan, dossier и другими).")
        total = 0
        for kind in ORDER:
            section = data.get(kind, [])
            if section is None:
                section = []
            if not isinstance(section, list):
                bad(f"Раздел «{kind}» должен быть списком.")
            total += len(section)
        if total == 0:
            bad("В разборе нет ни одного события.")
        if total > MAX_TOTAL:
            bad(f"За один раз можно загрузить не больше {MAX_TOTAL} пунктов, в разборе {total}. Разделите его на части.")
        self.data = data
        self.chars = logic.char_map()
        self.existing = {k: db.items(k) for k in ("places", "windows", "plan", "clocks", "rhythm", "past", "dossier", "handouts")}
        self.entries = [e for e in db.entries() if e.get("author") == "gm"]
        self.fresh = {k: [] for k in ORDER}
        self.merged = {k: [] for k in ORDER}            # дополнения существующих карточек и мест: {"before", "after"}
        self.items, self.warnings = [], []
        self.place_ids = {_norm(p["name"]): p["id"] for p in self.existing["places"]}
        self.taken = {k: {x["id"] for x in self.existing.get(k, [])} for k in ORDER}
        self.taken["entries"] = {e["id"] for e in db.entries()}
        self.seen = {k: set() for k in ORDER}
        self.per_district = {}
        for kind in ORDER:
            for n, raw in enumerate(data.get(kind) or [], 1):
                self._one(kind, n, raw)

    # ---- отчёт ----
    def _report(self, kind, n, raw, status, msg=""):
        title = clean(raw.get(TITLE_KEY[kind]), 120) if isinstance(raw, dict) else ""
        self.items.append({"kind": kind, "n": n, "title": title or f"№{n}", "status": status, "msg": msg})

    def _new_id(self, kind):
        while True:
            item_id = (logic.KINDS[kind] if kind != "entries" else "") + uuid.uuid4().hex[:8 if kind != "entries" else 12]
            if item_id not in self.taken[kind]:
                self.taken[kind].add(item_id)
                return item_id

    # ---- один элемент ----
    def _one(self, kind, n, raw):
        if not isinstance(raw, dict):
            return self._report(kind, n, raw, "error", "Эта часть разбора заполнена неверно: нужен набор полей (название, даты и другое).")
        raw = dict(raw)
        notes = []
        unknown = _unknown_chars(raw, self.chars)
        if unknown:
            notes.append("неизвестные персонажи не учтены: " + ", ".join(clean(u, 30) for u in unknown))
        try:
            status, payload = getattr(self, "_" + kind)(raw, notes)
        except logic.HTTPException as ex:
            return self._report(kind, n, raw, "error", str(ex.detail))
        if status == "skip":
            return self._report(kind, n, raw, "skip", payload)
        if status == "merge":
            self.merged[kind].append(payload)
            return self._report(kind, n, raw, "merge", "; ".join([payload["msg"]] + notes))
        self.fresh[kind].append(payload)
        self._report(kind, n, raw, "add", "; ".join(notes))

    def _dup(self, kind, key, message):
        """Повтор того, что уже есть или уже встречалось в этом разборе: сообщение для отчёта или пусто."""
        if key in self.seen[kind]:
            return "повтор в этом же разборе"
        self.seen[kind].add(key)
        return message if message else ""

    def _lookup_place(self, raw, notes):
        name = clean(raw.get("place_name"), 80)
        if not name:
            return ""
        found = self.place_ids.get(_norm(name))
        if not found:
            notes.append(f"место «{name}» не найдено на карте, поле «место» оставлено пустым")
        return found or ""

    # ---- разделы ----
    def _places(self, raw, notes):
        raw["vis"] = raw.get("vis") if raw.get("vis") in ("стол", "знают", "мастер") else "мастер"
        name = _norm(clean(raw.get("name"), 80))
        old_place = next((p for p in self.existing["places"] if _norm(p["name"]) == name), None) if name else None
        if old_place:                                           # место уже есть: его точка и видимость остаются, нужна только заметка мастера
            raw["x"], raw["y"] = old_place["x"], old_place["y"]
        else:
            self._put_on_map(raw, notes)
        hint = clean(raw.get("where_hint"), 200)
        if hint:
            raw["gm_note"] = (f"Ориентир: {hint}\n" + str(raw.get("gm_note") or "")).strip()
        if not old_place and raw.get("type") not in logic.PLACE_TYPES:
            notes.append(f"тип «{clean(raw.get('type'), 30)}» неизвестен, поставлено «Другое»")
        raw["bg"] = False
        item = logic._normalize("places", raw)
        name = _norm(item["name"])
        if name in self.seen["places"]:
            return "skip", "повтор в этом же разборе"
        self.seen["places"].add(name)
        if old_place:
            merged = self._append_note(old_place, item.get("gm_note", ""), 2000)
            if not merged:
                return "skip", "уже на карте"
            return "merge", {"before": old_place, "after": merged, "msg": "дополнится: заметка мастера (остальное в месте не меняется)"}
        if len(self.existing["places"]) + len(self.fresh["places"]) >= logic.MAX_ITEMS["places"]:
            bad(f"На карте не больше {logic.MAX_ITEMS['places']} мест.")
        item["id"] = self._new_id("places")
        self.place_ids[name] = item["id"]
        return "add", item

    def _put_on_map(self, raw, notes):
        """Координаты нового места: свои, если названы, иначе рядом с центром района, чтобы места одного района не лежали одно на другом."""
        has_xy = all(isinstance(raw.get(k), (int, float)) and not isinstance(raw.get(k), bool) for k in ("x", "y"))
        if has_xy:
            return
        district = raw.get("district")
        center = _district_centers().get(district) if isinstance(district, str) else None
        if not center:
            bad("Укажите район (district), чтобы поставить место на карте: downtown, bellevue, tacoma и другие.")
        k = self.per_district.setdefault(district, 0)
        self.per_district[district] += 1
        mw, mh = logic.map_size()
        raw["x"] = min(max(center[0] + round((k % 6 - 2.5) * PLACE_STEP), 0), mw)
        raw["y"] = min(max(center[1] + (k // 6) * PLACE_STEP, 0), mh)
        notes.append("поставлено рядом с центром района, затем переместите точку на карте")

    @staticmethod
    def _append_note(old, text, limit):
        """Копия старого элемента с дописанной заметкой мастера, если такого текста в ней ещё нет; иначе None.
        «Уже есть» значит: новый текст совпадает с заметкой целиком или с одним из ранее дописанных разделов (короткое слово внутри
        чужой заметки не считается)."""
        text = (text or "").strip()
        current = old.get("gm_note", "")
        if not text or _norm(text) in {_norm(part) for part in [current] + current.split(NOTE_HEAD)}:
            return None
        joined = (current.rstrip() + "\n\n" + NOTE_HEAD + "\n" + text).strip()[:limit]
        if joined == current:
            return None
        return dict(old, gm_note=joined)

    def _windows(self, raw, notes):
        item = logic._normalize("windows", raw)
        same = any((w["name"], w["from"], w["to"]) == (item["name"], item["from"], item["to"]) for w in self.existing["windows"])
        dup = self._dup("windows", (item["name"], item["from"], item["to"]), "такой этап уже заведён" if same else "")
        if dup:
            return "skip", dup
        item["id"] = "x"                                         # временный номер: проверка пересечения ждёт его
        for w in self.existing["windows"] + self.fresh["windows"]:
            if not (item["to"] < w["from"] or item["from"] > w["to"]):
                bad(f"Этап пересекается с этапом «{w.get('gm') or w['name']}».")
        item["id"] = self._new_id("windows")
        return "add", item

    def _plain(self, kind, raw, key_fields, notes):
        item = logic._normalize(kind, raw)
        key = tuple(item.get(f) if not isinstance(item.get(f), list) else tuple(item[f]) for f in key_fields)
        same = any(tuple(x.get(f) if not isinstance(x.get(f), list) else tuple(x[f]) for f in key_fields) == key for x in self.existing[kind])
        dup = self._dup(kind, key, "уже есть на портале" if same else "")
        if dup:
            return "skip", dup
        item["id"] = self._new_id(kind)
        return "add", item

    def _plan(self, raw, notes):
        return self._plain("plan", raw, ("title", "from", "to"), notes)

    def _past(self, raw, notes):
        return self._plain("past", raw, ("title", "from", "to"), notes)

    def _clocks(self, raw, notes):
        return self._plain("clocks", raw, ("title",), notes)

    def _rhythm(self, raw, notes):
        return self._plain("rhythm", raw, ("title", "wd", "monthDay"), notes)

    def _dossier(self, raw, notes):
        raw["last_place"] = ""
        name = _norm(raw.get("name"))
        old_card = next((c for c in self.existing["dossier"] if _norm(c["name"]) == name), None) if name else None
        if old_card:                                            # у существующей карточки важны только сведения и заметка
            raw["vis"], raw["known"] = "мастер", []
        item = logic._normalize("dossier", raw)
        name = _norm(item["name"])
        if name in self.seen["dossier"]:
            return "skip", "повтор в этом же разборе"
        self.seen["dossier"].add(name)
        if old_card:
            return self._merge_card(old_card, item)
        item["img"] = ""
        item["id"] = self._new_id("dossier")
        return "add", item

    def _merge_card(self, old, item):
        """Дополняет карточку, которая уже есть: сведения, которых в ней нет (по тексту), и заметка мастера. Остальное не трогает."""
        have = {_norm(f["text"]) for f in old.get("facts", [])}
        ids = {f["id"] for f in old.get("facts", [])}
        fresh = []
        for f in item["facts"]:
            if _norm(f["text"]) in have:
                continue
            have.add(_norm(f["text"]))
            while f["id"] in ids:
                f["id"] = "f" + uuid.uuid4().hex[:8]
            ids.add(f["id"])
            fresh.append(f)
        after = self._append_note(old, item.get("gm_note", ""), 4000) or dict(old)
        if fresh:
            if len(old.get("facts", [])) + len(fresh) > MAX_FACTS:
                bad(f"В карточке уже слишком много сведений: больше {MAX_FACTS} не бывает.")
            after["facts"] = old.get("facts", []) + fresh
        if after == old:
            return "skip", "карточка уже есть, нового в ней нет"
        parts = ([f"сведений {len(fresh)}"] if fresh else []) + (["заметка мастера"] if after.get("gm_note") != old.get("gm_note") else [])
        return "merge", {"before": old, "after": after, "msg": "дополнится: " + ", ".join(parts) + " (остальное в карточке не меняется)"}

    def _handouts(self, raw, notes):
        place = self._lookup_place(raw, notes)
        raw["place"] = ""
        draft = clean(raw.get("text"), 5000, True)
        if draft:
            raw["gm_note"] = (str(raw.get("gm_note") or "") + "\n\nЧерновик текста раздатки:\n" + draft).strip()
            if len(raw["gm_note"]) > 3000:
                notes.append("черновик текста не поместился в заметку мастера и обрезан: сам файл раздатки загрузите вручную")
        item = logic._normalize("handouts", raw)
        item["place"] = place
        same = any((h["title"], h["date"]) == (item["title"], item["date"]) for h in self.existing["handouts"])
        dup = self._dup("handouts", (item["title"], item["date"]), "уже есть на портале" if same else "")
        if dup:
            return "skip", dup
        item["id"] = self._new_id("handouts")
        return "add", item

    def _entries(self, raw, notes):
        typ = raw.get("type")
        if typ not in ENTRY_TYPES:
            bad("Тип записи: meet (Встреча), deal (Дело) или vow (Обещание).")
        place = self._lookup_place(raw, notes)
        raw["place"] = ""
        fields = logic._entry_fields(raw, typ, "gm")
        fields["place"] = place
        key = (fields["title"], fields["from"], fields["to"])
        same = any((e["title"], e["from"], e["to"]) == key for e in self.entries)
        dup = self._dup("entries", key, "такая запись уже есть в календаре" if same else "")
        if dup:
            return "skip", dup
        entry = {"id": self._new_id("entries"), "type": typ, "author": "gm", "status": "ok", "answers": {c: "да" for c in fields["who"]},
                 "talk": "open", "stars": [], "created": time.time()}
        entry.update(fields)
        return "add", entry

    # ---- итог ----
    def report(self):
        counts = {k: {"add": 0, "merge": 0, "skip": 0, "error": 0} for k, _ in LABELS}
        for it in self.items:
            counts[it["kind"]][it["status"]] += 1
        questions = self.data.get("questions")
        questions = [clean(q, 400) for q in questions if isinstance(q, str) and clean(q, 400)][:MAX_QUESTIONS] if isinstance(questions, list) else []
        order = {k: i for i, (k, _) in enumerate(LABELS)}
        items = sorted(self.items, key=lambda i: (order[i["kind"]], i["n"]))
        return {"add": sum(c["add"] for c in counts.values()), "merge": sum(c["merge"] for c in counts.values()),
                "skip": sum(c["skip"] for c in counts.values()), "error": sum(c["error"] for c in counts.values()),
                "counts": counts, "items": items, "questions": questions}


def preview(v, data):
    """Что будет добавлено, что пропущено и почему. Ничего не записывает."""
    return _Run(v, data).report()


def commit(v, data):
    """Добавляет и дополняет всё, что прошло проверку, одной транзакцией. (сообщение, отчёт)."""
    with db.lock:
        run = _Run(v, data)
        report = run.report()
        if report["add"] + report["merge"] == 0:
            bad("Добавлять нечего: всё уже есть на портале или не прошло проверку. Подробности в отчёте проверки.")
        titles = [it["title"] for it in report["items"] if it["status"] in ("add", "merge")][:20]
        with db.tx() as c:
            for kind in ORDER:
                fresh, merged = run.fresh[kind], run.merged[kind]
                if not (fresh or merged) or kind == "entries":
                    continue
                after = {m["after"]["id"]: m["after"] for m in merged}
                items = [after.get(x["id"], x) for x in db.items(kind)] + fresh
                if kind in ("windows", "plan", "past"):
                    items.sort(key=lambda x: x["from"])
                db.set_items(kind, items, c)
                for m in merged:                                 # каждое дополнение отдельной записью: его можно вернуть как было
                    audit.record(v, "edit", kind, m["after"]["id"], logic._item_title(m["after"]), before=m["before"], after=m["after"])
            for entry in run.fresh["entries"]:
                db.save_entry(entry)
            audit.record(v, "import", "arc", "", f"Импорт разбора арки: {report['add'] + report['merge']}",
                         after={"counts": {k: c_["add"] + c_["merge"] for k, c_ in report["counts"].items() if c_["add"] or c_["merge"]}, "titles": titles})
        db.bump()
    skipped = report["skip"] + report["error"]
    msg = f"Добавлено: {report['add']}" + (f", дополнено: {report['merge']}" if report["merge"] else "") + (f", пропущено: {skipped}" if skipped else "")
    return msg, report
