"""Правила портала. Всё, что игроку видеть не положено, отсекается здесь, до отправки в браузер."""
import json
import re
import time
import uuid
from datetime import date, timedelta

from fastapi import HTTPException

from . import audit, config, db, dice, handouts, notify, portraits, reminders, trash
from .config import people

TYPES = {"meet": "Встреча", "grow": "Развитие", "deal": "Дело", "vow": "Обещание"}
TOD = ["утро", "день", "вечер", "ночь"]
PENDING = {"gm", "reply", "resched"}
CLOSED = {"done", "failed", "rejected"}
WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WD_GEN = ["понедельника", "вторника", "среды", "четверга", "пятницы", "субботы", "воскресенья"]
WDS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u00ad\u200b-\u200d\ufeff]")



def wdi(s):
    """День недели по настоящему календарю: 0 — понедельник."""
    return date.fromisoformat(s).weekday()


def fdate(s):
    d = date.fromisoformat(s)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def ffull(s):
    return f"{WDS[wdi(s)]}, {fdate(s)}"


def add_days(s, n):
    return (date.fromisoformat(s) + timedelta(days=n)).isoformat()


def bad(message, code=400):
    raise HTTPException(code, message)


def clean(value, limit, multiline=False):
    text = str(value or "")
    if multiline:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = CTRL.sub("", text)
    else:
        text = CTRL.sub("", text.replace("\n", " "))
    return text.strip()[:limit]


def _snap(e):
    """Копия записи без обсуждения: для журнала и корзины."""
    return json.loads(json.dumps({k: v for k, v in e.items() if k != "chat"}, ensure_ascii=False))


def _item_title(item):
    return item.get("title") or item.get("name") or item.get("id", "")


def _actor_name(v):
    return "Мастер" if v.gm else v.name


AUDIT_ACTS = {"ans", "join", "kick", "approve", "reject", "outcome"}   # действия над записью, которые попадают в журнал


def _trash_entry(v, e):
    """Удалить запись в корзину вместе с обсуждением (db.lock должен быть взят)."""
    data = _snap(e)
    trash.put("entry", e["id"], e["title"], data, {"chat": db.raw_messages(e["id"])}, by=_actor_name(v))
    db.delete_entry(e["id"])
    audit.record(v, "delete", "entry", e["id"], e["title"], before=data)


def listed(value, allowed):
    """Уникальные строки из списка value, которые есть в allowed. Всё остальное (не список, вложенные списки, числа) отбрасывается."""
    if not isinstance(value, list):
        return []
    return [c for c in dict.fromkeys(x for x in value if isinstance(x, str)) if c in allowed]


def one_of(value, allowed, default):
    """value, если это строка из allowed, иначе default. Безопасно для любых типов (списки и словари не хешируются)."""
    return value if isinstance(value, str) and value in allowed else default


def to_num(value, lo, hi, message):
    """Число из запроса (целое или с дробью) в границах lo..hi; на мусоре отвечает 400."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad(message)
    try:
        number = float(value)
    except (ValueError, OverflowError):
        bad(message)
    if not (lo <= number <= hi):   # заодно отсекает nan и бесконечности
        bad(message)
    return int(number) if number == int(number) else round(number, 1)


def to_int(value, message):
    """Целое число из запроса; на мусоре отвечает 400, а не падает."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        bad(message)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        bad(message)


class Viewer:
    def __init__(self, role, obj, tg_id, username):
        self.gm = role == "gm"
        self.name = obj["name"]
        self.chars = [] if self.gm else list(obj["chars"])
        self.tg_id = tg_id
        self.username = username

    def acting(self, char):
        """От чьего имени действие: мастер или один из персонажей игрока."""
        if self.gm:
            return "gm"
        if char in self.chars:
            return char
        if not self.chars:
            bad("За вами не закреплён ни один персонаж. Обратитесь к мастеру.", 403)
        bad("Этот персонаж закреплён за другим игроком.", 403)


# ---------- чтение ----------

def now():
    return db.meta_get("now_date", "2075-08-01"), db.meta_get("now_tod", "вечер")


def cal():
    return db.meta_get("cal_start", "2075-07-01"), db.meta_get("cal_end", "2075-12-31")


def char_map():
    return {c["id"]: c for c in people()["characters"]}


def involves(e, c):
    return c in e["who"] or e["author"] == c


def horizon(v=None):
    """Последний день, который видят игроки: конец текущего этапа. Пусто, если ограничение выключено («Панель мастера, Что видят игроки
    вперёд»), сегодняшний день не входит ни в один этап или смотрит мастер. Для одного зрителя считается один раз."""
    if v is not None:
        if v.gm:
            return ""
        if not hasattr(v, "_horizon"):
            v._horizon = horizon()
        return v._horizon
    if db.meta_get("horizon", "off") != "window":
        return ""
    w = window_of(now()[0])
    return w["to"] if w else ""


def visible(e, v):
    if v.gm:
        return True
    hz = horizon(v)
    if hz and e["from"] > hz:                      # запись о том, что дальше текущего этапа, игроку не видна и не открывается
        return False
    mine = set(v.chars)
    return e["vis"] != "лично" or e["author"] in mine or bool(mine & set(e["who"]))


def is_active(e, today):
    return e["status"] not in CLOSED and (e.get("to") or "9999-12-31") >= today


def window_of(day):
    for w in db.items("windows"):
        if w["from"] <= day <= w["to"]:
            return w
    return None


PAST_PUBLIC = ("id", "from", "to", "title", "note", "session")  # поля хроники, которые видят игроки


def state_for(v):
    today, tod = now()
    cs, ce = cal()
    p = people()
    windows = db.items("windows")
    if not v.gm:
        # Будущие этапы и мастерские названия игрокам не отдаются.
        windows = [{k: w[k] for k in ("id", "from", "to", "name", "inter") if k in w}
                   for w in windows if w["from"] <= today]
    rhythm = [r for r in db.items("rhythm") if v.gm or r.get("vis") != "мастер"]
    hz = horizon(v)
    blocks = [] if v.gm else [b for b in cover_blocks() if not b["who"] or set(b["who"]) & set(v.chars)]
    past = db.items("past") if v.gm else [{k: x[k] for k in PAST_PUBLIC if k in x} for x in db.items("past")]
    handouts_list, dossier_list = handouts_for(v), dossier_for(v)
    entries = [e for e in db.entries() if visible(e, v)]
    if hz:                                          # ограничение «не дальше конца этапа»: игроку не отдаются даты позже него
        rhythm = [_clip_to(r, hz) for r in rhythm if not (r.get("from") and r["from"] > hz)]
        blocks = [_clip_to(b, hz) for b in blocks if b["from"] <= hz]
        past = [_clip_to(x, hz) for x in past if x["from"] <= hz]
        entries = [_clip_to(e, hz) for e in entries]
        handouts_list = [h for h in handouts_list if h.get("date", "") <= hz]
        dossier_list = [dict(c, facts=[f for f in c["facts"] if not f.get("date") or f["date"] <= hz]) for c in dossier_list]
    return {
        "version": int(db.meta_get("version", "0")),
        "now": {"date": today, "tod": tod},
        "quietUntil": db.meta_get("quiet_until", "") or "",
        "calStart": cs,
        "calEnd": min(ce, hz) if hz else ce,
        "windows": windows,
        "rhythm": rhythm,
        "past": past,
        "plan": db.items("plan") if v.gm else [],
        "blocks": blocks,
        "places": places_for(v),
        "dossier": dossier_list,
        "handouts": handouts_list,
        "handout_usage": handouts.usage() if v.gm else None,
        "portraits": portraits.usage() if v.gm else None,
        "dnotes": [d if v.gm else {"id": d["id"], "text": d.get("text", "")} for d in db.items("dnotes")],
        **sheet_for(v),
        "travel": [t for t in db.items("travel") if v.gm or t.get("vis") != "мастер"],
        "trash": trash.count() if v.gm else None,
        "clocks": db.items("clocks") if v.gm else [],
        "entries": entries,
        "locmaps": locmaps_for(v),
        "horizon": horizon_info(v, today),
        "characters": p["characters"],
        "players": [{"name": pl["name"], "chars": pl["chars"]} for pl in p["players"]],
        "me": {"gm": v.gm, "name": v.name, "chars": v.chars},
        "recap": bool(config.RECAP_ENABLED or config.RECAP_MANUAL) and not v.gm,          # кнопка «Что было раньше»: есть ключ Claude API или пересказ готовит мастер
        "recap_mode": "gm" if config.RECAP_MANUAL and not config.RECAP_ENABLED else "api",
        "recap_open": db.recap_open(None if v.gm else v.tg_id) if config.RECAP_MANUAL and not config.RECAP_ENABLED else 0,
        "recap_ready": db.recap_ready(v.tg_id) if config.RECAP_MANUAL and not config.RECAP_ENABLED and not v.gm else 0,
    }


_MAP_SIZE = None


def map_size():
    """Размер карты в метрах из static/map/map.json (читается один раз)."""
    global _MAP_SIZE
    if _MAP_SIZE is None:
        try:
            with open(config.STATIC_DIR / "map" / "map.json", encoding="utf-8") as f:
                data = json.load(f)
            _MAP_SIZE = (int(data["W"]), int(data["H"]))
        except (OSError, ValueError, KeyError):
            _MAP_SIZE = (200000, 300000)
    return _MAP_SIZE


def _faction_known_to(f, char):
    return f.get("vis") == "стол" or (f.get("vis") == "знают" and char in f.get("known", []))


def sheet_for(v):
    """Лист персонажа. Игрок видит только свои записи о деньгах, контакты и репутацию, и только у фракций, о которых его персонаж знает.
    Заметки мастера и чужие данные не уходят."""
    names = ("money", "factions", "standing", "contacts")
    if v.gm:
        return {k: db.items(k) for k in names}
    mine = set(v.chars)
    factions = {f["id"]: f for f in db.items("factions")}
    visible_cards = {c["id"] for c in dossier_for(v)}
    standing = [{k: s[k] for k in ("id", "char", "faction", "value", "note")} for s in db.items("standing")
                if s["char"] in mine and s["faction"] in factions and _faction_known_to(factions[s["faction"]], s["char"])]
    shown = {s["faction"] for s in standing}
    return {
        "money": [{k: m[k] for k in ("id", "char", "delta", "note", "date")} for m in db.items("money") if m["char"] in mine],
        "factions": [{"id": f["id"], "name": f["name"], "kind": f.get("kind", "other"), "note": f.get("note", "")}
                     for f in factions.values() if any(_faction_known_to(f, c) for c in mine) or f["id"] in shown],
        "standing": standing,
        "contacts": [{**{k: c[k] for k in ("id", "char", "name", "connection", "loyalty", "services", "note")},
                      **({"card": c["card"]} if c.get("card") in visible_cards else {})}
                     for c in db.items("contacts") if c["char"] in mine],
    }


def places_for(v):
    """Места карты: игрок видит общие и те, о которых знают его персонажи. Заметки мастера не уходят."""
    out = []
    mine = set(v.chars)
    for p in db.items("places"):
        if v.gm:
            out.append(p)
            continue
        if p.get("vis") == "мастер" or (p.get("vis") == "знают" and not mine & set(p.get("known", []))):
            continue
        out.append({k: p[k] for k in ("id", "name", "type", "x", "y", "note", "bg") if k in p})
    return out


def dossier_for(v):
    """Карточки досье: игрок видит открытые для него карточки и только те сведения, которые открыты его персонажам.
    Заметки мастера, поправки «на самом деле» и скрытые места до игрока не доходят."""
    cards = db.items("dossier")
    if v.gm:
        return cards
    mine = set(v.chars)
    visible_places = {p["id"] for p in places_for(v)}
    out = []
    for c in cards:
        if c.get("vis") == "мастер" or (c.get("vis") == "знают" and not mine & set(c.get("known", []))):
            continue
        facts = []
        for f in c.get("facts", []):
            if f.get("vis") == "мастер" or (f.get("vis") == "знают" and not mine & set(f.get("known", []))):
                continue
            facts.append({k: f[k] for k in ("id", "text", "date") if k in f})
        card = {k: c[k] for k in ("id", "name", "alias", "type", "role", "stance", "org", "met", "last_date", "last_note", "img") if k in c}
        if c.get("last_place") in visible_places:
            card["last_place"] = c["last_place"]
        card["facts"] = facts
        out.append(card)
    return out


def locmap_visible(m, v):
    """Видна ли карта локации игроку: «все», «знают» (его персонажи в списке) или не видна («мастер»). Мастеру видны все."""
    if v.gm:
        return True
    return m.get("vis") == "стол" or (m.get("vis") == "знают" and bool(set(v.chars) & set(m.get("known", []))))


def locmaps_for(v):
    """Карты локаций для списка: название, описание, место на городской карте, какие рисунки есть. Метки, рисунки и заметки мастера
    отдельным запросом (api/locmaps/<номер>), игроку без заметок мастера и без рисунка мастера. Для значка «новое»: игроку номера свежих
    записей ленты, мастеру число наступивших сроков и неотвеченных вопросов."""
    from . import locmaps
    visible_places = {p["id"] for p in places_for(v)}
    maps = [m for m in db.items("locmaps") if locmap_visible(m, v)]
    info = locmaps.badge_info(v, maps)
    out = []
    for m in maps:
        dw = m.get("dw", {})
        card = {"id": m["id"], "name": m["name"], "note": m.get("note", ""), "place": m.get("place", "") if v.gm or m.get("place") in visible_places else "",
                "dw": dw if v.gm else {k: x for k, x in dw.items() if k == "player"}}
        if v.gm:
            card.update(vis=m.get("vis", "мастер"), known=m.get("known", []), gm_note=m.get("gm_note", ""), count=len(m.get("objects", [])),
                        counter=m.get("counter", ""), due=info[m["id"]]["due"], open_q=info[m["id"]]["open_q"])
        else:
            card["fresh"] = info[m["id"]]["fresh"]
        out.append(card)
    return out


def handout_audience(h):
    """Кому из персонажей видна раздатка. Без файла и скрытая не видна никому."""
    if not h or not h.get("file") or h.get("vis") == "мастер":
        return set()
    return set(char_map()) if h.get("vis") == "стол" else set(h.get("known", []))


def card_audience(c):
    """Кому из персонажей открыта карточка досье (те же правила, что в dossier_for)."""
    if c.get("vis") == "мастер":
        return set()
    return set(c.get("known", [])) if c.get("vis") == "знают" else set(char_map())


def handout_notify(old, new):
    fresh = handout_audience(new) - handout_audience(old)
    hz = horizon()
    if fresh and not (hz and new.get("date", "") > hz):         # раздатка из будущего этапа игроку пока не видна, о ней не пишем
        notify.to_characters(sorted(fresh), f"Новая раздатка: «{new['title']}». Открыть можно на портале, во вкладке «Раздатки».", "handouts", kind="handout")


def handouts_for(v):
    items = db.items("handouts")
    if v.gm:
        return items
    mine = set(v.chars)
    out = []
    for h in items:
        if not (mine & handout_audience(h)):
            continue
        card = {k: h[k] for k in ("id", "title", "date", "vis", "note", "file", "kind", "size", "uploaded") if k in h}
        if h.get("vis") == "знают":
            card["known"] = [c for c in h.get("known", []) if c in mine]
        if h.get("place") and any(p["id"] == h["place"] for p in places_for(v)):
            card["place"] = h["place"]
        out.append(card)
    return out


def save_handout_file(v, item_id, raw, fname):
    if not v.gm:
        bad("Только для мастера.", 403)
    _card(db.items("handouts"), item_id)
    try:
        prepared = handouts.prepare(raw)
    except handouts.HandoutError as e:
        bad(e.message, e.code)
    with db.lock:
        items = db.items("handouts")
        h = _card(items, item_id)
        old = dict(h)
        used = handouts.usage()["used"] - handouts.item_bytes(item_id)
        if used + len(prepared["data"]) > handouts.quota_bytes():
            bad(f"Хранилище раздаток заполнено: занято {portraits.mb(used)} МБ из {portraits.mb(handouts.quota_bytes())} МБ. "
                "Удалите ненужные раздатки и попробуйте снова.", 413)
        h["file"] = handouts.store(item_id, prepared)
        h["kind"] = prepared["kind"]
        h["size"] = prepared["raw_bytes"]
        h["fname"] = clean(fname, 120) or handouts.DEFAULT_NAMES[prepared["kind"]]
        h["uploaded"] = int(time.time())
        db.set_items("handouts", items)
        audit.record(v, "upload", "handouts", item_id, h["title"])
        db.bump()
    handout_notify(old, h)
    return "Файл раздатки загружен"


def _card(cards, card_id):
    card = next((c for c in cards if c["id"] == card_id), None)
    if not card:
        bad("Карточка не найдена.", 404)
    return card


def save_portrait(v, card_id, raw):
    """Картинка карточки: проверка, сжатие, проверка общего лимита, замена прежней."""
    if not v.gm:
        bad("Только для мастера.", 403)
    _card(db.items("dossier"), card_id)
    try:
        full, thumb = portraits.process(raw)
    except portraits.PortraitError as e:
        bad(e.message, e.code)
    with db.lock:
        cards = db.items("dossier")
        card = _card(cards, card_id)
        used = portraits.usage()["used"] - portraits.card_bytes(card_id)
        if used + len(full) + len(thumb) > portraits.quota_bytes():
            bad(f"Хранилище картинок заполнено: занято {portraits.mb(used)} МБ из {portraits.mb(portraits.quota_bytes())} МБ. "
                "Уберите ненужные картинки и попробуйте снова.", 413)
        card["img"] = portraits.store(card_id, full, thumb)
        db.set_items("dossier", cards)
        audit.record(v, "upload", "dossier", card_id, card["name"])
        db.bump()
    return "Картинка сохранена"


def delete_portrait(v, card_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        cards = db.items("dossier")
        card = _card(cards, card_id)
        portraits.remove(card_id)
        card["img"] = ""
        db.set_items("dossier", cards)
        audit.record(v, "file-delete", "dossier", card_id, card["name"])
        db.bump()
    return "Картинка убрана"


def save_dnote(v, slug, b):
    if not v.gm:
        bad("Только для мастера.", 403)
    if slug not in DISTRICTS:
        bad("Неизвестный район.", 404)
    with db.lock:
        old = next((d for d in db.items("dnotes") if d["id"] == slug), None)
        items = [d for d in db.items("dnotes") if d["id"] != slug]
        new = {"id": slug, "text": clean(b.get("text"), 3000, True), "gm_text": clean(b.get("gm_text"), 3000, True)}
        items.append(new)
        db.set_items("dnotes", items)
        audit.record(v, "edit", "dnote", slug, slug, before=old, after=new)
        db.bump()
    return "Описание района сохранено"


def cover_blocks():
    """Планы мастера с маской: игроки видят только текст маски, настоящее описание не уходит."""
    out = []
    for p in db.items("plan"):
        c = p.get("cover")
        if c and c.get("title"):
            out.append({"id": p["id"], "from": p["from"], "to": p["to"], "title": c["title"],
                        "note": c.get("note", ""), "who": c.get("who", [])})
    return out


def _clip_to(item, hz):
    """Копия элемента, у которого окончание не дальше границы (начался раньше, закончится позже: игрок дальше границы не заглянет)."""
    return dict(item, to=hz) if item.get("to") and item["to"] > hz else item


def horizon_info(v, today):
    """Для игрока: действует ли ограничение и до какого дня он видит календарь. Для мастера ещё режим, текущий этап и что сейчас скрыто."""
    hz = horizon(v)
    if not v.gm:
        return {"on": bool(hz), "until": hz}
    mode, w = db.meta_get("horizon", "off") == "window" and "window" or "off", window_of(today)
    until = w["to"] if w else ""
    hidden = {}
    if mode == "window" and until:
        hidden = {"entries": sum(1 for e in db.entries() if e["from"] > until),
                  "blocks": sum(1 for b in cover_blocks() if b["from"] > until),
                  "rhythm": sum(1 for r in db.items("rhythm") if r.get("vis") != "мастер" and r.get("from", "") > until),
                  "handouts": sum(1 for h in db.items("handouts") if h.get("date", "") > until and handout_audience(h))}
    return {"mode": mode, "on": mode == "window" and bool(until), "until": until, "window": (w.get("gm") or w["name"]) if w else "", "hidden": hidden}


def set_horizon(v, b):
    """Переключатель «Что видят игроки вперёд»: до конца текущего этапа или без ограничения."""
    if not v.gm:
        bad("Только для мастера.", 403)
    mode = b.get("mode")
    if mode not in ("window", "off"):
        bad("Выберите: ограничить игроков концом текущего этапа или не ограничивать.")
    with db.lock:
        if db.meta_get("horizon", "off") != mode:
            db.meta_set("horizon", mode)
            audit.record(v, "setting", "horizon", "", "Игроки видят вперёд: " + ("до конца текущего этапа" if mode == "window" else "без ограничения"))
            db.bump()
    return "Сохранено"


def status_text():
    """Текст закреплённого сообщения в чате стола."""
    today, tod = now()
    q = db.meta_get("quiet_until", "") or ""
    w = window_of(today)
    lines = ["Сиэтл, 2075", f"{WD[wdi(today)].capitalize()}, {fdate(today)}, {tod}"]
    if w:
        lines.append(f"Этап: {w['name']}")
    if q and q >= today:
        lines.append(f"Свободное время гарантировано до {WD_GEN[wdi(q)]}, {fdate(q)} включительно.")
    else:
        lines.append("Свободное время не гарантировано.")
    return "\n".join(lines)


# ---------- проверки ----------

def check_date(s, label="Дата"):
    cs, ce = cal()
    if not isinstance(s, str) or not ISO.match(s):
        bad(f"{label}: неверный формат.")
    try:
        date.fromisoformat(s)
    except ValueError:
        bad(f"{label}: такой даты нет.")
    if not cs <= s <= ce:
        bad(f"{label}: вне календаря кампании.")
    return s


def recompute(e):
    if e["status"] not in ("ok", "reply", "resched"):
        return
    answers = list(e["answers"].values())
    e["status"] = "resched" if "нет" in answers else "reply" if "ждёт" in answers else "ok"


# ---------- записи ----------

def _check_horizon(limit, *days):
    if limit and any(d > limit for d in days):
        bad(f"Дальше {ffull(limit)} записи пока не ставятся: игрокам открыт календарь до конца текущего этапа.")


def _entry_fields(b, typ, author, limit=""):
    """Проверенные поля записи из формы. author: персонаж-автор или 'gm'. limit: последний день, который может назвать игрок (пусто: любой)."""
    title = clean(b.get("title"), 80)
    if not title:
        bad("Укажите название записи.")
    start = check_date(b.get("from"), "Начало")
    end = check_date(b.get("to"), "Окончание")
    if end < start:
        bad("Дата окончания раньше даты начала.")
    _check_horizon(limit, start, end)
    tod = b.get("tod") or ""
    if tod and tod not in TOD:
        bad("Неизвестное время суток.")
    chars = char_map()
    who = listed(b.get("who"), chars)
    if author != "gm" and author not in who:
        who.insert(0, author)
    is_open = bool(b.get("open")) and typ != "grow"
    goal = clean(b.get("goal"), 2000, multiline=True)
    if not who and not is_open:
        bad("Выберите хотя бы одного участника или отметьте «+».")
    fields = {
        "title": title, "from": start, "to": end, "tod": tod, "who": who, "open": is_open,
        "where": clean(b.get("where"), 120), "cond": clean(b.get("cond"), 160), "goal": goal,
        "vis": "стол" if is_open or b.get("vis") != "лично" else "лично",
        "place": "",
    }
    pid = str(b.get("place") or "")
    if pid:
        if not any(p["id"] == pid for p in db.items("places")):
            bad("Место на карте не найдено.")
        fields["place"] = pid
    if typ == "grow":
        if len(who) != 1:
            bad("Развитие оформляется на одного персонажа.")
        if not goal:
            bad("Для развития заполните цель: что повышается и как персонаж этого добивается.")
        eff = check_date(b.get("effect") or start, "Действует с")
        _check_horizon(limit, eff)
        fields["effect"] = max(eff, start)
    return fields


def create_entry(v, b):
    with db.lock:
        char = v.acting(b.get("char"))
        typ = b.get("type")
        if not isinstance(typ, str) or typ not in TYPES:
            bad("Неизвестный тип записи.")
        fields = _entry_fields(b, typ, char, horizon(v))
        e = {"id": uuid.uuid4().hex[:12], "type": typ, "author": char,
             "status": "ok", "answers": {}, "talk": "open", "stars": [], "created": time.time()}
        e.update(fields)
        msg, invited = "Запись добавлена", []
        if typ == "grow":
            if char != "gm":
                e["status"] = "gm"
                msg = "Заявка на развитие отправлена мастеру"
        elif char != "gm":
            mine = set(v.chars)
            for c in e["who"]:
                if c == char:
                    continue
                if c in mine:  # второй персонаж того же игрока
                    e["answers"][c] = "да"
                else:
                    e["answers"][c] = "ждёт"
                    invited.append(c)
            if invited:
                e["status"] = "reply"
                msg = "Приглашения отправлены участникам"
        else:
            e["answers"] = {c: "да" for c in e["who"]}
        db.save_entry(e)
        reminders.asked(e["id"], invited)
        audit.record(v, "create", "entry", e["id"], e["title"], after=_snap(e))
        db.bump()
    author = char_map().get(char, {}).get("name", "Мастер")
    if invited:
        notify.invite(e, invited, f"{author} приглашает в запись «{e['title']}», {ffull(e['from'])}. Ответить можно на портале.")
    if e["status"] == "gm":
        notify.to_gm(f"Заявка на развитие от {author}: «{e['title']}».", "gm", kind="grow", buttons=notify.grow_buttons(e))
    return msg


def edit_entry(v, entry_id, b):
    """Правка записи автором или мастером. Если игрок перенёс даты, приглашённых спрашивают заново."""
    with db.lock:
        e = db.entry(entry_id)
        if not e or not visible(e, v):
            bad("Запись не найдена.", 404)
        v.acting(b.get("char"))
        if not (v.gm or e["author"] in v.chars):
            bad("Изменить запись может только автор или мастер.", 403)
        if e["status"] in CLOSED:
            bad("Закрытую запись изменить нельзя.")
        before = _snap(e)
        fields = _entry_fields(b, e["type"], e["author"], horizon(v))
        moved = (fields["from"], fields["to"], fields["tod"]) != (e["from"], e["to"], e.get("tod", ""))
        old = e.get("answers", {})
        e.update(fields)
        e.pop("chat", None)
        mine = set(v.chars)
        answers, asked = {}, []
        for c in e["who"]:
            if c == e["author"]:
                continue
            prev = old.get(c)
            if v.gm:
                answers[c] = prev or "да"
            elif c in mine:
                answers[c] = "да"
            elif prev is None or (moved and prev in ("да", "нет", "сам")):
                answers[c] = "ждёт"
                asked.append(c)
            else:
                answers[c] = prev
        e["answers"] = answers
        e["stars"] = [c for c in e.get("stars", []) if c in e["who"] or c == e["author"]]
        if e["type"] == "grow":
            if not v.gm:
                e["status"] = "gm"
        else:
            recompute(e)
        db.save_entry(e)
        reminders.asked(e["id"], asked)
        audit.record(v, "edit", "entry", e["id"], e["title"], before=before, after=_snap(e))
        db.bump()
    if asked:
        author = char_map().get(e["author"], {}).get("name", "Мастер")
        notify.invite(e, asked, f"{author} изменил(а) запись «{e['title']}»: {ffull(e['from'])}. Подтвердите участие на портале.")
    if e["type"] == "grow" and not v.gm:
        notify.to_gm(f"Заявка на развитие изменена: «{e['title']}».", "gm", kind="grow", buttons=notify.grow_buttons(e))
    return "Запись обновлена"


def entry_action(v, entry_id, b):
    act, val = b.get("act"), b.get("v")
    note = None
    with db.lock:
        e = db.entry(entry_id)
        if not e or not visible(e, v):
            bad("Запись не найдена.", 404)
        today, _ = now()
        before = _snap(e)
        char = v.acting(b.get("char"))
        manage = v.gm or e["author"] in v.chars
        live = e["status"] not in CLOSED
        names = {k: c["name"] for k, c in char_map().items()}

        if act == "ans":
            if e["answers"].get(char) != "ждёт" or val not in ("да", "нет"):
                bad("Ответ на это приглашение уже не требуется.")
            e["answers"][char] = val
            recompute(e)
            msg = "Приглашение принято" if val == "да" else "Приглашение отклонено, нужна другая дата"
            label = "участие подтверждено" if val == "да" else "отказ, нужна другая дата"
            note = ("chars", [e["author"]], f"Ответ на приглашение в «{e['title']}»: {names.get(char, char)}, {label}.")
        elif act == "join":
            if v.gm or not e.get("open") or involves(e, char) or not is_active(e, today):
                bad("Попроситься в эту запись нельзя.")
            e["who"].append(char)
            e["answers"][char] = "сам"
            recompute(e)
            msg = "Вы добавлены в участники"
            note = ("chars", [e["author"]], f"В запись «{e['title']}» попросился участник: {names.get(char, char)}.")
        elif act == "kick":
            if not manage or not live:
                bad("Убрать участника может только автор записи или мастер.", 403)
            if val == e["author"] or val not in e["who"]:
                bad("Этого участника убрать нельзя.")
            e["who"].remove(val)
            e["answers"].pop(val, None)
            e["stars"] = [c for c in e["stars"] if c != val]
            recompute(e)
            msg = f"{names.get(val, val)} больше не участвует"
        elif act == "star":
            if v.gm:
                bad("Звёзды ставят игроки.", 403)
            if not involves(e, char) or not is_active(e, today):
                bad("Звезду можно поставить только на актуальное дело, где участвует персонаж.")
            if char in e["stars"]:
                e["stars"].remove(char)
                msg = "Звезда снята"
            else:
                moved = False
                for other in db.entries():
                    if other["id"] != e["id"] and char in other.get("stars", []) and is_active(other, today):
                        other["stars"].remove(char)
                        db.save_entry(other)
                        moved = True
                e["stars"].append(char)
                msg = "Звезда перенесена" if moved else "Звезда поставлена"
        elif act == "talk":
            if not manage or not live:
                bad("Завершить обсуждение может только автор записи или мастер.", 403)
            e["talk"] = "closed" if e.get("talk", "open") == "open" else "open"
            msg = "Обсуждение завершено" if e["talk"] == "closed" else "Обсуждение возобновлено"
        elif act in ("approve", "reject"):
            if not v.gm:
                bad("Развитие подтверждает только мастер.", 403)
            if e["status"] != "gm":
                bad("Эта заявка уже рассмотрена.")
            e["status"] = "ok" if act == "approve" else "rejected"
            msg = "Развитие подтверждено" if act == "approve" else "Развитие отклонено"
            verdict = "подтверждено мастером" if act == "approve" else "отклонено мастером"
            note = ("chars", [e["author"]], f"Развитие «{e['title']}» {verdict}.")
        elif act == "outcome":
            if not v.gm or val not in ("done", "failed") or not e.get("to") or e["to"] >= today or e["status"] != "ok":
                bad("Итог этой записи отметить нельзя.")
            e["status"] = val
            msg = "Отмечено: состоялось" if val == "done" else "Отмечено: сорвано"
        elif act == "del":
            if not manage or not live:
                bad("Удалить запись может только автор или мастер.", 403)
            _trash_entry(v, e)
            db.bump()
            return "Запись удалена"
        else:
            bad("Неизвестное действие.")
        db.save_entry(e)
        if act in AUDIT_ACTS:
            audit.record(v, "act:" + act, "entry", e["id"], e["title"], before=before, after=_snap(e))
        db.bump()
    if note and note[1][0] in names:
        notify.to_characters(note[1], note[2], "now", kind="answer")
    return msg


def add_message(v, entry_id, b):
    with db.lock:
        e = db.entry(entry_id)
        if not e or not visible(e, v):
            bad("Запись не найдена.", 404)
        char = v.acting(b.get("char"))
        if e.get("talk", "open") == "closed":
            bad("Обсуждение окончено, новые сообщения недоступны.")
        if not v.gm and not involves(e, char):
            bad("Писать в обсуждение могут участники и мастер.", 403)
        text = clean(b.get("text"), 2000, multiline=True)
        if not text:
            bad("Пустое сообщение.")
        db.add_message(entry_id, char, v.tg_id, text)
        db.bump()
        label = "Мастер" if char == "gm" else char_map().get(char, {}).get("name", char)
    notify.chat_message(e, label, text, v.tg_id)
    return "Сообщение отправлено"


_ROLL_TIMES = {}
ROLLS_PER_MINUTE = 30


def roll_dice(v, entry_id, b):
    """Бросок кубов в обсуждении записи: бросает сервер, результат остаётся сообщением в обсуждении."""
    with db.lock:
        e = db.entry(entry_id)
        if not e or not visible(e, v):
            bad("Запись не найдена.", 404)
        char = v.acting(b.get("char"))
        if e.get("talk", "open") == "closed":
            bad("Обсуждение окончено, бросать кубы нельзя.")
        if not v.gm and not involves(e, char):
            bad("Бросать кубы в обсуждении могут участники и мастер.", 403)
        pool = to_int(b.get("dice"), f"Число кубов: целое от 1 до {dice.MAX_POOL}.")
        if not 1 <= pool <= dice.MAX_POOL:
            bad(f"Число кубов: целое от 1 до {dice.MAX_POOL}.")
        limit = threshold = None
        if b.get("limit") not in (None, ""):
            limit = to_int(b.get("limit"), f"Предел: целое от 1 до {dice.MAX_LIMIT}.")
            if not 1 <= limit <= dice.MAX_LIMIT:
                bad(f"Предел: целое от 1 до {dice.MAX_LIMIT}.")
        if b.get("threshold") not in (None, ""):
            threshold = to_int(b.get("threshold"), f"Порог: целое от 0 до {dice.MAX_LIMIT}.")
            if not 0 <= threshold <= dice.MAX_LIMIT:
                bad(f"Порог: целое от 0 до {dice.MAX_LIMIT}.")
        now_ts = time.time()
        recent = [t for t in _ROLL_TIMES.get(v.tg_id, []) if now_ts - t < 60]
        if len(recent) >= ROLLS_PER_MINUTE:
            bad("Слишком много бросков подряд. Подождите минуту.", 429)
        _ROLL_TIMES[v.tg_id] = recent + [now_ts]
        label = clean(b.get("label"), 60)
        result = dice.roll(pool, bool(b.get("edge")), limit, threshold)
        result["label"] = label
        text = dice.describe(result, label)
        db.add_message(entry_id, char, v.tg_id, text, roll=result)
        db.bump()
        who = "Мастер" if char == "gm" else char_map().get(char, {}).get("name", char)
    notify.chat_message(e, who, text, v.tg_id)
    return "Кубы брошены"


# ---------- панель мастера ----------

def gm_time(v, b):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        today, _ = now()
        cs, ce = cal()
        before = {"date": today, "tod": now()[1], "quiet": db.meta_get("quiet_until", "") or ""}
        if b.get("date"):
            db.meta_set("now_date", check_date(b["date"], "Дата"))
        elif "shift" in b:
            n = to_int(b["shift"], "Сдвиг времени: нужно число дней.")
            if abs(n) > 400:
                bad("Слишком большой сдвиг времени.")
            d = add_days(today, n)
            db.meta_set("now_date", min(max(d, cs), ce))
        if "tod" in b:
            if b["tod"] not in TOD:
                bad("Неизвестное время суток.")
            db.meta_set("now_tod", b["tod"])
        if "quiet" in b:
            q = b["quiet"] or ""
            db.meta_set("quiet_until", check_date(q, "Свободное время") if q else "")
        after = {"date": now()[0], "tod": now()[1], "quiet": db.meta_get("quiet_until", "") or ""}
        if after != before:
            audit.record(v, "time", "time", "", "Время в игре", before=before, after=after)
        db.bump()
    notify.pin_status(status_text())
    if after["date"] != before["date"]:
        from . import locmaps
        locmaps.notify_due(before["date"], after["date"])
    return "Сохранено"


def plan_played(v, plan_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        plan = db.items("plan")
        item = next((p for p in plan if p["id"] == plan_id), None)
        if not item:
            bad("Событие плана не найдено.", 404)
        plan.remove(item)
        w = window_of(item["from"])
        label = ""
        if item.get("session"):
            label = ((w.get("gm") or w["name"]).split(".")[0] + ", " if w else "") + item["session"]
        past = db.items("past")
        past.append({"id": "p" + uuid.uuid4().hex[:8], "from": item["from"], "to": item["to"],
                     "title": item["title"], "note": "", "gm_note": item.get("note", ""), "session": label,
                     "plan_id": item["id"]})
        past.sort(key=lambda x: x["from"])
        db.set_items("plan", plan)
        db.set_items("past", past)
        audit.record(v, "played", "plan", item["id"], item["title"], before=item, after=next(x for x in past if x.get("plan_id") == item["id"]))
        db.bump()
    return "Событие перенесено в хронику"


# ---------- редактирование этапов, регулярных событий, таймеров, плана и хроники ----------

KINDS = {"windows": "w", "rhythm": "r", "clocks": "c", "plan": "g", "past": "p", "places": "m", "dossier": "n", "handouts": "h", "travel": "t",
         "money": "y", "factions": "f", "standing": "s", "contacts": "k", "locmaps": "l"}
MAX_TRAVEL = 12
# Лист персонажа (Shadowrun): нуйены (записи о доходах и расходах), фракции, репутация персонажа у фракции, контакты. Пишет только мастер.
MAX_ITEMS = {"money": 3000, "factions": 60, "standing": 600, "contacts": 300, "places": 1500, "locmaps": 40}
IMPORT_PLACES_AT_ONCE = 600
FACTION_KINDS = {"corp", "gang", "gov", "org", "other"}
STANDING_RANGE = (-5, 5)
MONEY_LIMIT = 1_000_000_000
STANCES = {"unknown", "contact", "ally", "neutral", "hostile"}
FACT_ID = re.compile(r"[A-Za-z0-9_-]{1,20}")
PLACE_TYPES = {"home", "contact", "business", "corp", "danger", "checkpoint", "other", "medical", "security", "shop", "leisure"}
DISTRICTS = {"downtown", "bellevue", "tacoma", "auburn", "renton", "everett", "snohomish", "redmond",
             "puyallup", "council", "dogtown", "fortlewis", "outremer"}


def _opt_date(value, label):
    return check_date(value, label) if value else ""


def _span(b):
    start = check_date(b.get("from"), "Начало")
    end = check_date(b.get("to") or start, "Окончание")
    if end < start:
        bad("Дата окончания раньше даты начала.")
    return start, end


def _title(b, key="title", limit=120, label="Укажите название."):
    text = clean(b.get(key), limit)
    if not text:
        bad(label)
    return text


def _char_of(b, chars):
    char = b.get("char")
    if not isinstance(char, str) or char not in chars:
        bad("Выберите персонажа.")
    return char


def _fmt_money(n):
    return f"{'+' if n > 0 else '−'}{abs(n):,}".replace(",", "\u00a0") + "\u00a0¥"


def _normalize_sheet(kind, b, chars):
    """Нуйены, фракции, репутация и контакты. Названия персонажей и фракций попадают в заголовок для журнала и корзины."""
    name_of = lambda c: chars[c]["name"]
    if kind == "factions":
        vis = one_of(b.get("vis"), ("стол", "знают", "мастер"), "мастер")
        known = listed(b.get("known"), chars)
        if vis == "знают" and not known:
            bad("Отметьте, какие персонажи знают эту фракцию.")
        return {"name": _title(b, "name", 60, "Укажите название фракции."), "kind": one_of(b.get("kind"), FACTION_KINDS, "other"),
                "note": clean(b.get("note"), 1000, True), "gm_note": clean(b.get("gm_note"), 1000, True),
                "vis": vis, "known": known if vis == "знают" else []}
    char = _char_of(b, chars)
    if kind == "money":
        delta = to_int(b.get("delta"), "Укажите сумму: целое число нуйенов. Доход со знаком «+», расход со знаком «−».")
        if delta == 0 or abs(delta) > MONEY_LIMIT:
            bad("Сумма: целое число нуйенов от 1 до 1 000 000 000. Доход со знаком «+», расход со знаком «−».")
        note = clean(b.get("note"), 200)
        return {"char": char, "delta": delta, "note": note, "date": _opt_date(b.get("date"), "Дата") or now()[0],
                "gm_note": clean(b.get("gm_note"), 500, True), "title": f"{name_of(char)}: {_fmt_money(delta)}" + (f", {note}" if note else "")}
    if kind == "standing":
        faction = b.get("faction")
        found = next((f for f in db.items("factions") if f["id"] == faction), None) if isinstance(faction, str) else None
        if not found:
            bad("Выберите фракцию.")
        value = to_int(b.get("value"), f"Репутация: целое число от {STANDING_RANGE[0]} до {STANDING_RANGE[1]}.")
        if not STANDING_RANGE[0] <= value <= STANDING_RANGE[1]:
            bad(f"Репутация: целое число от {STANDING_RANGE[0]} до {STANDING_RANGE[1]}.")
        if any(s["char"] == char and s["faction"] == faction and s["id"] != b.get("id") for s in db.items("standing")):
            bad("Репутация этого персонажа у этой фракции уже записана. Измените её.", 409)
        return {"char": char, "faction": faction, "value": value, "note": clean(b.get("note"), 300), "gm_note": clean(b.get("gm_note"), 500, True),
                "title": f"{name_of(char)} и «{found['name']}»: " + f"{value:+d}".replace("-", "−")}
    # contacts
    card = b.get("card") or ""
    cards = db.items("dossier")
    linked = next((c for c in cards if c["id"] == card), None) if isinstance(card, str) and card else None
    if card and not linked:
        bad("Карточка досье не найдена.")
    name = clean(b.get("name"), 80) or (linked["name"] if linked else "")
    if not name:
        bad("Укажите имя контакта или выберите карточку досье.")
    connection = to_int(b.get("connection"), "Связи: целое число от 1 до 12.")
    loyalty = to_int(b.get("loyalty"), "Лояльность: целое число от 1 до 6.")
    if not 1 <= connection <= 12:
        bad("Связи: целое число от 1 до 12.")
    if not 1 <= loyalty <= 6:
        bad("Лояльность: целое число от 1 до 6.")
    return {"char": char, "name": name, "card": linked["id"] if linked else "", "connection": connection, "loyalty": loyalty,
            "services": clean(b.get("services"), 300), "note": clean(b.get("note"), 1000, True), "gm_note": clean(b.get("gm_note"), 1000, True),
            "title": f"{name_of(char)}: контакт «{name}»"}


def _normalize(kind, b):
    chars = char_map()
    if kind == "windows":
        start, end = _span(b)
        item = {"name": _title(b, "name", 80, "Укажите название этапа для игроков."), "from": start, "to": end}
        gm = clean(b.get("gm"), 120)
        if gm:
            item["gm"] = gm
        if b.get("inter"):
            item["inter"] = True
        return item
    if kind == "rhythm":
        item = {"title": _title(b), "note": clean(b.get("note"), 1000, True),
                "vis": "мастер" if b.get("vis") == "мастер" else "стол"}
        if b.get("mode") == "monthly":
            try:
                day = int(b.get("monthDay"))
            except (TypeError, ValueError, OverflowError):
                day = 0
            if not 1 <= day <= 31:
                bad("Число месяца должно быть от 1 до 31.")
            item["monthDay"] = day
        else:
            wd = b.get("wd")
            try:
                days = sorted({int(x) for x in (wd if isinstance(wd, list) else []) if not isinstance(x, bool) and 0 <= int(x) <= 6})
            except (TypeError, ValueError, OverflowError):
                days = []
            if not days:
                bad("Отметьте хотя бы один день недели.")
            item["wd"] = days
        start = _opt_date(b.get("from"), "Начиная с")
        end = _opt_date(b.get("to"), "Заканчивается")
        if start and end and end < start:
            bad("Дата окончания раньше даты начала.")
        if start:
            item["from"] = start
        if end:
            item["to"] = end
        if isinstance(b.get("who"), str) and b["who"] in chars:
            item["who"] = b["who"]
        return item
    if kind == "clocks":
        item = {"title": _title(b), "note": clean(b.get("note"), 1000, True)}
        when = _opt_date(b.get("when"), "Срок")
        if when:
            item["when"] = when
        return item
    if kind == "handouts":
        vis = b.get("vis") if b.get("vis") in ("стол", "знают", "мастер") else "мастер"
        known = listed(b.get("known"), chars)
        if vis == "знают" and not known:
            bad("Отметьте, кто из персонажей получил раздатку.")
        place = str(b.get("place") or "")
        if place and not any(p["id"] == place for p in db.items("places")):
            bad("Место на карте не найдено.")
        return {"title": _title(b, "title", 120, "Укажите название раздатки."),
                "date": check_date(b.get("date"), "Дата получения"), "vis": vis, "known": known if vis == "знают" else [],
                "note": clean(b.get("note"), 3000, True), "gm_note": clean(b.get("gm_note"), 3000, True), "place": place}
    if kind in ("money", "factions", "standing", "contacts"):
        return _normalize_sheet(kind, b, chars)
    if kind == "travel":
        tkind = one_of(b.get("kind"), ("roads", "straight"), "roads")
        speeds = {k: to_num(b.get(k, 0), 0, 2000, f"Скорость «{label}»: число от 0 до 2000 км/ч.")
                  for k, label in (("motorway", "магистрали"), ("trunk", "трассы"), ("primary", "основные дороги"), ("off", "вне дорог"))}
        if speeds["off"] <= 0:
            bad("Скорость вне дорог (у вида «по прямой» это общая скорость) должна быть больше нуля.")
        if tkind == "roads" and not any(speeds[k] > 0 for k in ("motorway", "trunk", "primary")):
            bad("У вида «по дорогам» хотя бы на одном классе дорог скорость должна быть больше нуля.")
        return {"name": _title(b, "name", 60, "Укажите название вида транспорта."), "kind": tkind, **speeds,
                "delay": to_num(b.get("delay", 0), 0, 1440, "Задержка: число минут от 0 до 1440."),
                "wall": to_num(b.get("wall", 0), 0, 1440, "Пропускной пункт: число минут от 0 до 1440."),
                "vis": "мастер" if b.get("vis") == "мастер" else "стол", "note": clean(b.get("note"), 300)}
    if kind == "dossier":
        vis = b.get("vis") if b.get("vis") in ("стол", "знают", "мастер") else "мастер"
        known = listed(b.get("known"), chars)
        if vis == "знают" and not known:
            bad("Отметьте, кому из персонажей открыта карточка.")
        last_date = _opt_date(b.get("last_date"), "Дата последней встречи")
        last_place = str(b.get("last_place") or "")
        if last_place and not any(p["id"] == last_place for p in db.items("places")):
            bad("Место последней встречи не найдено.")
        facts, seen_ids = [], set()
        raw = b.get("facts") if isinstance(b.get("facts"), list) else []
        if len(raw) > 80:
            bad("Слишком много сведений в одной карточке.")
        for f in raw:
            if not isinstance(f, dict):
                continue
            text = clean(f.get("text"), 1500, True)
            if not text:
                bad("В карточке есть пустое сведение.")
            fvis = f.get("vis") if f.get("vis") in ("стол", "знают", "мастер") else "мастер"
            fknown = listed(f.get("known"), chars)
            if fvis == "знают" and not fknown:
                bad("У сведения выбрано «только знающие», но не отмечены персонажи.")
            fid = str(f.get("id") or "")
            if not FACT_ID.fullmatch(fid) or fid in seen_ids:
                fid = "f" + uuid.uuid4().hex[:8]
            seen_ids.add(fid)
            fact = {"id": fid, "text": text, "vis": fvis,
                    "known": fknown if fvis == "знают" else [], "truth": clean(f.get("truth"), 1500, True)}
            fdate = _opt_date(f.get("date"), "Дата сведения")
            if fdate:
                fact["date"] = fdate
            facts.append(fact)
        return {"name": _title(b, "name", 80, "Укажите имя или название."), "alias": clean(b.get("alias"), 80),
                "type": "org" if b.get("type") == "org" else "person", "role": clean(b.get("role"), 140),
                "stance": one_of(b.get("stance"), STANCES, "unknown"),
                "org": clean(b.get("org"), 120), "vis": vis, "known": known if vis == "знают" else [],
                "met": listed(b.get("met"), chars),
                "last_date": last_date, "last_place": last_place, "last_note": clean(b.get("last_note"), 200),
                "facts": facts, "gm_note": clean(b.get("gm_note"), 4000, True)}
    if kind == "locmaps":
        vis = b.get("vis") if b.get("vis") in ("стол", "знают", "мастер") else "мастер"
        known = listed(b.get("known"), chars)
        if vis == "знают" and not known:
            bad("Отметьте, какие персонажи знают об этой карте.")
        place = str(b.get("place") or "")
        if place and not any(p["id"] == place for p in db.items("places")):
            bad("Место на городской карте не найдено.")
        return {"name": _title(b, "name", 80, "Укажите название карты."), "note": clean(b.get("note"), 2000, True),
                "gm_note": clean(b.get("gm_note"), 4000, True), "vis": vis, "known": known if vis == "знают" else [], "place": place,
                "counter": clean(b.get("counter"), 30)}
    if kind == "places":
        x, y = to_int(b.get("x"), "Не указано место на карте."), to_int(b.get("y"), "Не указано место на карте.")
        mw, mh = map_size()
        if not (0 <= x <= mw and 0 <= y <= mh):
            bad("Точка за краем карты. Поставьте место внутри карты.")
        typ = one_of(b.get("type"), PLACE_TYPES, "other")
        vis = b.get("vis") if b.get("vis") in ("стол", "знают", "мастер") else "стол"
        known = listed(b.get("known"), chars)
        if vis == "знают" and not known:
            bad("Отметьте, кто из персонажей знает об этом месте.")
        return {"name": _title(b, "name", 80, "Укажите название места."), "type": typ, "x": x, "y": y, "vis": vis,
                "known": known if vis == "знают" else [], "note": clean(b.get("note"), 2000, True),
                "gm_note": clean(b.get("gm_note"), 2000, True), "bg": b.get("bg") is True}
    if kind in ("plan", "past"):
        start, end = _span(b)
        item = {"title": _title(b), "from": start, "to": end,
                "note": clean(b.get("note"), 2000, True), "session": clean(b.get("session"), 60)}
        if kind == "past":
            item["gm_note"] = clean(b.get("gm_note"), 2000, True)
        cover = b.get("cover") if kind == "plan" else None
        if isinstance(cover, dict) and clean(cover.get("title"), 120):
            item["cover"] = {"title": clean(cover.get("title"), 120),
                             "note": clean(cover.get("note"), 1000, True),
                             "who": listed(cover.get("who"), chars)}
        return item
    bad("Неизвестный раздел.")


def _rotate_if_narrowed(kind, old, item):
    """Кто потерял доступ к карточке или раздатке, не должен открывать файл по старой ссылке: токен меняется."""
    if kind == "dossier" and old and item.get("img") and card_audience(old) - card_audience(item):
        item["img"] = portraits.rotate(item["id"]) or item["img"]
    if kind == "handouts" and old and item.get("file") and handout_audience(old) - handout_audience(item):
        item["file"] = handouts.rotate(item["id"]) or item["file"]


def _check_windows(items, item):
    for w in items:
        if w["id"] != item["id"] and not (item["to"] < w["from"] or item["from"] > w["to"]):
            bad(f"Этап пересекается с этапом «{w.get('gm') or w['name']}».", 409)


def import_places(v, items):
    """Пакетное добавление мест на карту одной операцией (набор из «Seattle 2072» или KML из Google My Maps).
    Каждое место проходит ту же проверку, что и при ручном добавлении; существующие места не меняются.
    В журнал уходит одна запись об импорте: отменяется он удалением мест на карте (или из корзины)."""
    if not v.gm:
        bad("Только для мастера.", 403)
    if not isinstance(items, list) or not items:
        bad("Не выбрано ни одного места.")
    if len(items) > IMPORT_PLACES_AT_ONCE:
        bad(f"За один раз можно добавить не больше {IMPORT_PLACES_AT_ONCE} мест.")
    fresh = []
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            bad(f"Место №{n} заполнено неверно.")
        try:
            fresh.append(_normalize("places", it))
        except HTTPException as e:
            bad(f"Место №{n} («{clean(it.get('name'), 80)}»): {e.detail}")
    with db.lock:
        places = db.items("places")
        if len(places) + len(fresh) > MAX_ITEMS["places"]:
            bad(f"На карте не больше {MAX_ITEMS['places']} мест: сейчас {len(places)}, добавляется {len(fresh)}. Удалите ненужные.", 409)
        taken = {p["id"] for p in places}
        for it in fresh:
            while True:
                it["id"] = KINDS["places"] + uuid.uuid4().hex[:8]
                if it["id"] not in taken:
                    break
            taken.add(it["id"])
            places.append(it)
        db.set_items("places", places)
        audit.record(v, "import", "places", "", f"Импорт мест: {len(fresh)}", after={"count": len(fresh), "names": [it["name"] for it in fresh[:20]]})
        db.bump()
    return f"Добавлено мест: {len(fresh)}"


def save_item(v, kind, b):
    if not v.gm:
        bad("Только для мастера.", 403)
    if kind not in KINDS:
        bad("Неизвестный раздел.", 404)
    with db.lock:
        items = db.items(kind)
        item_id = b.get("id")
        old = next((x for x in items if x["id"] == item_id), None) if item_id else None
        if item_id and not old:
            bad("Запись не найдена, возможно, её уже удалили.", 404)
        if kind == "travel" and not old and len(items) >= MAX_TRAVEL:
            bad(f"Видов транспорта не больше {MAX_TRAVEL}.")
        if kind in MAX_ITEMS and not old and len(items) >= MAX_ITEMS[kind]:
            bad("Достигнут предел числа записей этого раздела. Уберите ненужные.", 409)
        item = _normalize(kind, b)
        item["id"] = old["id"] if old else KINDS[kind] + uuid.uuid4().hex[:8]
        if kind == "dossier":
            item["img"] = (old or {}).get("img", "")
        if kind == "handouts":
            for k in ("file", "kind", "size", "fname", "uploaded"):
                if old and k in old:
                    item[k] = old[k]
        _rotate_if_narrowed(kind, old, item)
        if kind == "past" and old and old.get("plan_id"):
            item["plan_id"] = old["plan_id"]
        if kind == "locmaps":                          # метки и сведения о рисунках правятся отдельно, форма карты их не трогает
            for k, empty in MAP_KEPT.items():
                item[k] = (old or {}).get(k, empty() if callable(empty) else empty)
        if kind == "windows":
            for w in items:
                if w is not old and not (item["to"] < w["from"] or item["from"] > w["to"]):
                    bad(f"Этап пересекается с этапом «{w.get('gm') or w['name']}».")
        if old:
            items[items.index(old)] = item
        else:
            items.append(item)
        if kind in ("windows", "plan", "past"):
            items.sort(key=lambda x: x["from"])
        db.set_items(kind, items)
        audit.record(v, "edit" if old else "create", kind, item["id"], _item_title(item),
                     before=_audit_view(kind, old), after=_audit_view(kind, item))
        db.bump()
    if kind == "handouts":
        handout_notify(old, item)
    cover = item.get("cover")
    hz = horizon()
    if kind == "plan" and cover and not (hz and item["from"] > hz) and (not old or old.get("cover") != cover
                                     or (old["from"], old["to"]) != (item["from"], item["to"])):
        when = ffull(item["from"]) if item["from"] == item["to"] else f"{ffull(item['from'])} – {ffull(item['to'])}"
        targets = cover["who"] or list(char_map())
        notify.to_characters(targets, f"Общее событие, {when}: {cover['title']}. На это время лучше не планировать других дел.", "cal", kind="cover")
    return "Сохранено" if old else "Добавлено"


MAP_KEPT = {"objects": list, "dw": dict, "deadlines": list, "party": dict}      # что у карты локации правится отдельно от формы карты


def _audit_view(kind, item):
    """Что попадает в журнал: у карты локации без меток (их может быть сотни, а правится в журнале только описание карты)."""
    if kind == "locmaps" and item:
        return {k: x for k, x in item.items() if k not in MAP_KEPT}
    return item


def _delete_item_locked(v, kind, item_id):
    """Убрать элемент в корзину (db.lock должен быть взят). Картинка и файл раздатки остаются в базе, но закрыты."""
    items = db.items(kind)
    item = next((x for x in items if x["id"] == item_id), None)
    if not item:
        bad("Запись не найдена.", 404)
    db.set_items(kind, [x for x in items if x["id"] != item_id])
    if kind == "dossier":
        portraits.trash(item_id)
    if kind == "handouts":
        handouts.trash(item_id)
    trash.put(kind, item_id, _item_title(item), item, by=_actor_name(v))
    audit.record(v, "delete", kind, item_id, _item_title(item), before=item)


def delete_item(v, kind, item_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    if kind not in KINDS:
        bad("Неизвестный раздел.", 404)
    with db.lock:
        _delete_item_locked(v, kind, item_id)
        db.bump()
    return "Удалено. Восстановить можно из корзины в панели мастера"


# ---------- корзина, журнал, откат ----------

def _check_insert(kind, item):
    items = db.items(kind)
    if any(x["id"] == item["id"] for x in items):
        bad("Такая запись уже есть.", 409)
    if kind == "windows":
        _check_windows(items, item)
    if kind == "travel" and len(items) >= MAX_TRAVEL:
        bad(f"Видов транспорта не больше {MAX_TRAVEL}.")
    if kind == "standing" and any(x["char"] == item["char"] and x["faction"] == item["faction"] for x in items):
        bad("Репутация этого персонажа у этой фракции уже записана.", 409)
    if kind in MAX_ITEMS and len(items) >= MAX_ITEMS[kind]:
        bad("Достигнут предел числа записей этого раздела.", 409)


def _insert_item(kind, item):
    items = db.items(kind)
    items.append(item)
    if kind in ("windows", "plan", "past"):
        items.sort(key=lambda x: x["from"])
    db.set_items(kind, items)


def restore_trash(v, trash_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        row = trash.get(trash_id)
        if not row:
            bad("Этого уже нет в корзине: возможно, вышел срок хранения.", 404)
        kind, data = row["kind"], row["data"]
        if kind == "entry":
            if db.entry(data["id"]):
                bad("Такая запись уже есть.", 409)
            db.save_entry(data)
            reminders.asked(data["id"], [c for c, a in data.get("answers", {}).items() if a == "ждёт"])
            for m in (row["extra"] or {}).get("chat", []):
                db.add_message(data["id"], m["author"], m["user_id"], m["text"], m["ts"], m.get("roll"))
        else:
            _check_insert(kind, data)
            if kind == "dossier" and data.get("img"):
                if portraits.usage()["used"] + portraits.trashed_bytes(data["id"]) > portraits.quota_bytes():
                    bad("Не хватает места в хранилище картинок: освободите место и попробуйте снова.", 413)
                portraits.untrash(data["id"])
                data["img"] = portraits.rotate(data["id"]) or ""      # старая ссылка к тому времени могла разойтись
            if kind == "handouts" and data.get("file"):
                if handouts.usage()["used"] + handouts.trashed_bytes(data["id"]) > handouts.quota_bytes():
                    bad("Не хватает места в хранилище раздаток: освободите место и попробуйте снова.", 413)
                handouts.untrash(data["id"])
                data["file"] = handouts.rotate(data["id"]) or ""
            _insert_item(kind, data)
        trash.remove(trash_id, drop_blobs=False)
        audit.record(v, "restore", kind, data["id"], row["title"], after=data)
        db.bump()
    return f"Восстановлено: «{row['title']}»"


def purge_trash(v, trash_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        if not trash.remove(trash_id):
            bad("Этого уже нет в корзине.", 404)
        db.bump()
    return "Удалено окончательно"


def empty_trash(v):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        n = trash.empty()
        db.bump()
    return f"Корзина очищена, удалено: {n}"


def revert_change(v, audit_id):
    """Откатить правку из журнала: вернуть прежнее состояние, отменить добавление или вернуть удалённое."""
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        row = audit.get(audit_id)
        if not row:
            bad("Запись журнала не найдена.", 404)
        action, kind, item_id, before = row["action"], row["kind"], row["item_id"], row["before"]
        if action == "delete":
            tid = trash.latest_for(kind, item_id)
            if not tid:
                bad("В корзине этого уже нет.", 404)
            return restore_trash(v, tid)
        if action == "create":
            if kind == "entry":
                e = db.entry(item_id)
                if not e:
                    bad("Запись уже удалена.", 404)
                _trash_entry(v, e)
            elif kind in KINDS:
                _delete_item_locked(v, kind, item_id)
            else:
                bad("Это добавление отменить нельзя.")
            db.bump()
            return "Добавление отменено, запись в корзине"
        if action == "time":
            for key, meta in (("date", "now_date"), ("tod", "now_tod"), ("quiet", "quiet_until")):
                db.meta_set(meta, before.get(key, ""))
            audit.record(v, "revert", "time", "", "Время в игре", before=row["after"], after=before)
            db.bump()
            return "Время в игре возвращено"
        if action != "edit" or not isinstance(before, dict):
            bad("Это изменение вернуть нельзя.")
        if kind == "entry":
            current = db.entry(item_id)
            if not current:
                bad("Запись удалена: сначала восстановите её из корзины.", 409)
            now_state = _snap(current)
            db.save_entry(dict(before))
            audit.record(v, "revert", "entry", item_id, before.get("title", ""), before=now_state, after=before)
        elif kind == "dnote":
            old = next((d for d in db.items("dnotes") if d["id"] == item_id), None)
            items = [d for d in db.items("dnotes") if d["id"] != item_id] + [before]
            db.set_items("dnotes", items)
            audit.record(v, "revert", "dnote", item_id, item_id, before=old, after=before)
        elif kind in KINDS:
            items = db.items(kind)
            current = next((x for x in items if x["id"] == item_id), None)
            if not current:
                bad("Эта запись удалена: сначала восстановите её из корзины.", 409)
            restored = dict(before)
            for k in ("img", "file", "size", "fname", "uploaded", "plan_id", *MAP_KEPT):     # ссылки на файлы и метки не откатываются
                if k in current:
                    restored[k] = current[k]
                else:
                    restored.pop(k, None)
            if kind == "windows":
                _check_windows(items, restored)
            _rotate_if_narrowed(kind, current, restored)
            items[items.index(current)] = restored
            if kind in ("windows", "plan", "past"):
                items.sort(key=lambda x: x["from"])
            db.set_items(kind, items)
            audit.record(v, "revert", kind, item_id, _item_title(restored), before=current, after=restored)
        else:
            bad("Это изменение вернуть нельзя.")
        db.bump()
    return "Вернули как было"
