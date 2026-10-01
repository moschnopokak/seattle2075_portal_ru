"""Правила портала. Всё, что игроку видеть не положено, отсекается здесь, до отправки в браузер."""
import json
import re
import time
import uuid
from datetime import date, timedelta

from fastapi import HTTPException

from . import config, db, handouts, notify, portraits
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
    if isinstance(value, bool):
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


def visible(e, v):
    if v.gm:
        return True
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
    return {
        "version": int(db.meta_get("version", "0")),
        "now": {"date": today, "tod": tod},
        "quietUntil": db.meta_get("quiet_until", "") or "",
        "calStart": cs,
        "calEnd": ce,
        "windows": windows,
        "rhythm": rhythm,
        "past": db.items("past") if v.gm else [{k: x[k] for k in PAST_PUBLIC if k in x} for x in db.items("past")],
        "plan": db.items("plan") if v.gm else [],
        "blocks": [] if v.gm else [b for b in cover_blocks() if not b["who"] or set(b["who"]) & set(v.chars)],
        "places": places_for(v),
        "dossier": dossier_for(v),
        "handouts": handouts_for(v),
        "handout_usage": handouts.usage() if v.gm else None,
        "portraits": portraits.usage() if v.gm else None,
        "dnotes": [d if v.gm else {"id": d["id"], "text": d.get("text", "")} for d in db.items("dnotes")],
        "travel": [t for t in db.items("travel") if v.gm or t.get("vis") != "мастер"],
        "clocks": db.items("clocks") if v.gm else [],
        "entries": [e for e in db.entries() if visible(e, v)],
        "characters": p["characters"],
        "players": [{"name": pl["name"], "chars": pl["chars"]} for pl in p["players"]],
        "me": {"gm": v.gm, "name": v.name, "chars": v.chars},
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
        out.append({k: p[k] for k in ("id", "name", "type", "x", "y", "note") if k in p})
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
    if fresh:
        notify.to_characters(sorted(fresh), f"Новая раздатка: «{new['title']}». Открыть можно на портале, во вкладке «Раздатки».", "handouts")


def handouts_for(v):
    items = db.items("handouts")
    if v.gm:
        return items
    mine = set(v.chars)
    out = []
    for h in items:
        if not (mine & handout_audience(h)):
            continue
        card = {k: h[k] for k in ("id", "title", "date", "vis", "note", "file", "size", "uploaded") if k in h}
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
        packed, raw_bytes = handouts.check(raw)
    except handouts.HandoutError as e:
        bad(e.message, e.code)
    with db.lock:
        items = db.items("handouts")
        h = _card(items, item_id)
        old = dict(h)
        used = handouts.usage()["used"] - handouts.item_bytes(item_id)
        if used + len(packed) > handouts.quota_bytes():
            bad(f"Хранилище раздаток заполнено: занято {portraits.mb(used)} МБ из {portraits.mb(handouts.quota_bytes())} МБ. "
                "Удалите ненужные раздатки и попробуйте снова.", 413)
        h["file"] = handouts.store(item_id, packed, raw_bytes)
        h["size"] = raw_bytes
        h["fname"] = clean(fname, 120) or "раздатка.html"
        h["uploaded"] = int(time.time())
        db.set_items("handouts", items)
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
        db.bump()
    return "Картинка убрана"


def save_dnote(v, slug, b):
    if not v.gm:
        bad("Только для мастера.", 403)
    if slug not in DISTRICTS:
        bad("Неизвестный район.", 404)
    with db.lock:
        items = [d for d in db.items("dnotes") if d["id"] != slug]
        items.append({"id": slug, "text": clean(b.get("text"), 3000, True), "gm_text": clean(b.get("gm_text"), 3000, True)})
        db.set_items("dnotes", items)
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

def _entry_fields(b, typ, author):
    """Проверенные поля записи из формы. author: персонаж-автор или 'gm'."""
    title = clean(b.get("title"), 80)
    if not title:
        bad("Укажите название записи.")
    start = check_date(b.get("from"), "Начало")
    end = check_date(b.get("to"), "Окончание")
    if end < start:
        bad("Дата окончания раньше даты начала.")
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
        fields["effect"] = max(eff, start)
    return fields


def create_entry(v, b):
    with db.lock:
        char = v.acting(b.get("char"))
        typ = b.get("type")
        if not isinstance(typ, str) or typ not in TYPES:
            bad("Неизвестный тип записи.")
        fields = _entry_fields(b, typ, char)
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
        db.bump()
    author = char_map().get(char, {}).get("name", "Мастер")
    if invited:
        notify.to_characters(invited, f"{author} приглашает в запись «{e['title']}», {ffull(e['from'])}. Ответить можно на портале.", "now")
    if e["status"] == "gm":
        notify.to_gm(f"Заявка на развитие от {author}: «{e['title']}».", "gm")
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
        fields = _entry_fields(b, e["type"], e["author"])
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
        db.bump()
    if asked:
        author = char_map().get(e["author"], {}).get("name", "Мастер")
        notify.to_characters(asked, f"{author} изменил(а) запись «{e['title']}»: {ffull(e['from'])}. Подтвердите участие на портале.", "now")
    if e["type"] == "grow" and not v.gm:
        notify.to_gm(f"Заявка на развитие изменена: «{e['title']}».", "gm")
    return "Запись обновлена"


def entry_action(v, entry_id, b):
    act, val = b.get("act"), b.get("v")
    note = None
    with db.lock:
        e = db.entry(entry_id)
        if not e or not visible(e, v):
            bad("Запись не найдена.", 404)
        today, _ = now()
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
                bad("Напроситься в эту запись нельзя.")
            e["who"].append(char)
            e["answers"][char] = "сам"
            recompute(e)
            msg = "Вы добавлены в участники"
            note = ("chars", [e["author"]], f"В запись «{e['title']}» напросился участник: {names.get(char, char)}.")
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
            db.delete_entry(entry_id)
            db.bump()
            return "Запись удалена"
        else:
            bad("Неизвестное действие.")
        db.save_entry(e)
        db.bump()
    if note and note[1][0] in names:
        notify.to_characters(note[1], note[2], "now")
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
    return "Сообщение отправлено"


# ---------- панель мастера ----------

def gm_time(v, b):
    if not v.gm:
        bad("Только для мастера.", 403)
    with db.lock:
        today, _ = now()
        cs, ce = cal()
        if b.get("date"):
            db.meta_set("now_date", check_date(b["date"], "Дата"))
        elif "shift" in b:
            n = to_int(b["shift"], "Сдвиг времени: нужно число дней.")
            if abs(n) > 400:
                bad("Слишком большой сдвиг.")
            d = add_days(today, n)
            db.meta_set("now_date", min(max(d, cs), ce))
        if "tod" in b:
            if b["tod"] not in TOD:
                bad("Неизвестное время суток.")
            db.meta_set("now_tod", b["tod"])
        if "quiet" in b:
            q = b["quiet"] or ""
            db.meta_set("quiet_until", check_date(q, "Свободное время") if q else "")
        db.bump()
    notify.pin_status(status_text())
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
        db.bump()
    return "Событие перенесено в хронику"


# ---------- редактирование этапов, регулярных событий, таймеров, плана и хроники ----------

KINDS = {"windows": "w", "rhythm": "r", "clocks": "c", "plan": "g", "past": "p", "places": "m", "dossier": "n", "handouts": "h", "travel": "t"}
MAX_TRAVEL = 12
STANCES = {"unknown", "contact", "ally", "neutral", "hostile"}
FACT_ID = re.compile(r"[A-Za-z0-9_-]{1,20}")
PLACE_TYPES = {"home", "contact", "business", "corp", "danger", "checkpoint", "other"}
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
                "gm_note": clean(b.get("gm_note"), 2000, True)}
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
        item = _normalize(kind, b)
        item["id"] = old["id"] if old else KINDS[kind] + uuid.uuid4().hex[:8]
        if kind == "dossier":
            item["img"] = (old or {}).get("img", "")
            # Кто потерял доступ к карточке, не должен открывать картинку по старой ссылке: токен меняется.
            if old and item["img"] and card_audience(old) - card_audience(item):
                item["img"] = portraits.rotate(item["id"]) or item["img"]
        if kind == "handouts":
            for k in ("file", "size", "fname", "uploaded"):
                if old and k in old:
                    item[k] = old[k]
            if old and item.get("file") and handout_audience(old) - handout_audience(item):
                item["file"] = handouts.rotate(item["id"]) or item["file"]
        if kind == "past" and old and old.get("plan_id"):
            item["plan_id"] = old["plan_id"]
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
        db.bump()
    if kind == "handouts":
        handout_notify(old, item)
    cover = item.get("cover")
    if kind == "plan" and cover and (not old or old.get("cover") != cover
                                     or (old["from"], old["to"]) != (item["from"], item["to"])):
        when = ffull(item["from"]) if item["from"] == item["to"] else f"{ffull(item['from'])} – {ffull(item['to'])}"
        targets = cover["who"] or list(char_map())
        notify.to_characters(targets, f"Общее событие, {when}: {cover['title']}. На это время лучше не планировать других дел.", "cal")
    return "Сохранено" if old else "Добавлено"


def delete_item(v, kind, item_id):
    if not v.gm:
        bad("Только для мастера.", 403)
    if kind not in KINDS:
        bad("Неизвестный раздел.", 404)
    with db.lock:
        items = db.items(kind)
        rest = [x for x in items if x["id"] != item_id]
        if len(rest) == len(items):
            bad("Запись не найдена.", 404)
        db.set_items(kind, rest)
        if kind == "dossier":
            portraits.remove(item_id)
        if kind == "handouts":
            handouts.remove(item_id)
        db.bump()
    return "Удалено"
