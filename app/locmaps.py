"""Карты локаций: план места (Роща, здание, база) с рисунком для игроков и отдельным рисунком мастера, метками, лентой общих обновлений
и пометками группы.

- У карты два рисунка (SVG): «игроков» и «мастера». Рисунок мастера никогда не уходит игроку (отдельный путь с проверкой роли).
- Рисунок при загрузке очищается по белому списку: скрипты, внешние ссылки, встроенные картинки и обработчики событий убираются. Отдаётся с
  заголовком sandbox и показывается как картинка, поэтому даже непонятная разметка выполнить ничего не может.
- Метки (объекты) лежат в самой карте (items, раздел locmaps), у каждой видимость «стол / знают / мастер», состояние, заметка для игроков
  и заметка мастера. Положение у метки своё на каждом рисунке (at.player и at.gm): рисунки разные, поэтому и координаты разные.
- Общие обновления: когда мастер открывает метку игрокам или меняет её состояние, в ленту карты попадает запись; вручную можно дописать
  объявление, при желании с сообщением в Telegram. Записи позже границы «что видят игроки вперёд» игрок не получает.
- Пометки группы: короткие заметки игроков на их рисунке, видны всем игрокам с доступом к карте и мастеру.
"""
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET

from . import db, logic, notify
from .logic import bad, clean, listed, one_of

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

ROLES = ("player", "gm")
MAX_SVG_BYTES = 3 * 1024 * 1024
MAX_NODES = 40000
MAX_DEPTH = 60
MAX_DIM = 100000
MAX_OBJECTS = 300
MAX_PINS = 60
MAX_FEED = 300
MAX_IMPORT = 300
OBJ_KINDS = {"area": "Сектор", "thing": "Находка", "danger": "Угроза", "creature": "Существо", "place": "Место", "note": "Пометка"}
STATUSES = {"": "", "scouted": "разведано", "cleared": "расчищено", "danger": "опасно", "found": "найдено", "lost": "потеряно"}
VIS = ("стол", "знают", "мастер")
SERVE_HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:",
    "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable", "Cross-Origin-Resource-Policy": "same-origin",
}

ALLOWED_TAGS = {"svg", "g", "defs", "symbol", "use", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "title", "desc",
                "pattern", "marker", "clipPath", "linearGradient", "radialGradient", "stop", "style",
                # эффекты (текстура бумаги, тени): только безопасные, feImage умеет грузить чужое и поэтому не разрешён
                "filter", "feTurbulence", "feDisplacementMap", "feGaussianBlur", "feColorMatrix", "feComposite", "feOffset", "feMerge", "feMergeNode",
                "feFlood", "feBlend", "feMorphology", "feComponentTransfer", "feFuncR", "feFuncG", "feFuncB", "feFuncA", "feDropShadow"}
_ATTR_NAME = re.compile(r"^[A-Za-z_][-A-Za-z0-9_.:]*$")
_BAD_VALUE = re.compile(r"(?i)javascript:|vbscript:|data:text|<\s*script|expression\s*\(|@import|behavior\s*:|-moz-binding")
_URL = re.compile(r"url\(\s*(['\"]?)([^)'\"]*)\1\s*\)", re.I)
_FONT_DATA = re.compile(r"(?i)^data:(font/|application/(x-)?font|application/vnd\.ms-fontobject|application/octet-stream)")


class SvgError(Exception):
    pass


# ---------- очистка рисунка ----------

def _clean_css(text):
    """Стили рисунка: без @import и выражений; url() только на части самого рисунка (#…) и на встроенные шрифты."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if _BAD_VALUE.search(text):
        return ""

    def keep(m):
        ref = m.group(2).strip()
        return m.group(0) if ref.startswith("#") or _FONT_DATA.match(ref) else "none"
    return _URL.sub(keep, text)


def _clean_attrs(attrs):
    out = {}
    for name, value in attrs.items():
        if name.startswith("{"):
            ns, _, local = name[1:].partition("}")
            if ns == XLINK_NS and local == "href":
                name = f"{{{XLINK_NS}}}href"
            elif ns == XML_NS and local in ("space", "lang"):
                name = f"{{{XML_NS}}}{local}"
            else:
                continue
            local_name = local
        else:
            local_name = name
        if not _ATTR_NAME.match(local_name) or local_name.lower().startswith("on"):
            continue
        value = str(value)
        if local_name == "href":
            if value.startswith("#"):                            # ссылка только на часть этого же рисунка
                out[name] = value
            continue
        if local_name == "style":
            value = _clean_css(value)
            if value:
                out[name] = value
            continue
        if _BAD_VALUE.search(value):
            continue
        if "url(" in value.lower() and any(not m.group(2).strip().startswith("#") for m in _URL.finditer(value)):
            continue
        out[name] = value
    return out


def sanitize_svg(raw):
    """Очищенный SVG-текст и размеры (ширина, высота, убранные теги). SvgError с понятным текстом, если файл не подходит."""
    if len(raw) > MAX_SVG_BYTES:
        raise SvgError(f"Рисунок больше {MAX_SVG_BYTES // 1048576} МБ. Упростите его или сожмите.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SvgError("Файл не в кодировке UTF-8. Сохраните SVG заново.") from None
    if re.search(r"(?i)<!DOCTYPE|<!ENTITY", text):
        raise SvgError("В рисунке есть описания типа документа (DOCTYPE): такой файл не принимается. Сохраните SVG без них.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise SvgError("Файл не читается как SVG. Откройте его в браузере: если там картинка, пересохраните как «обычный SVG».") from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise SvgError("Это не SVG-рисунок.")
    removed, count = {}, [0]

    def rebuild(node, depth):
        count[0] += 1
        if count[0] > MAX_NODES or depth > MAX_DEPTH:
            raise SvgError("Рисунок слишком сложный: упростите его.")
        ns, _, tag = node.tag[1:].partition("}") if node.tag.startswith("{") else ("", "", node.tag)
        if ns != SVG_NS or tag not in ALLOWED_TAGS:
            removed[tag] = removed.get(tag, 0) + 1
            return None
        out = ET.Element(f"{{{SVG_NS}}}{tag}", _clean_attrs(node.attrib))
        if node.text and node.text.strip():
            out.text = _clean_css(node.text) if tag == "style" else node.text
        for child in node:
            built = rebuild(child, depth + 1)
            if built is not None:
                if child.tail and child.tail.strip():
                    built.tail = child.tail
                out.append(built)
        return out

    clean_root = rebuild(root, 0)
    vb = root.attrib.get("viewBox", "")
    try:
        if vb:
            nums = [float(x) for x in re.split(r"[ ,]+", vb.strip())]
            if len(nums) != 4:
                raise ValueError
            x0, y0, w, h = nums
            if abs(x0) > 0.001 or abs(y0) > 0.001:
                raise SvgError("viewBox рисунка должен начинаться с 0 0 (например «0 0 1684 1190»).")
        else:
            w, h = (float(re.sub(r"[a-z%]+$", "", root.attrib.get(k, ""), flags=re.I)) for k in ("width", "height"))
    except ValueError:
        raise SvgError("У рисунка нет размеров. Нужен viewBox, например «0 0 1684 1190».") from None
    if not (0 < w <= MAX_DIM and 0 < h <= MAX_DIM):
        raise SvgError("Размер рисунка должен быть от 1 до 100 000.")
    for key in ("width", "height", "viewBox"):
        clean_root.attrib.pop(key, None)
    clean_root.set("viewBox", f"0 0 {w:g} {h:g}")
    clean_root.set("width", f"{w:g}")
    clean_root.set("height", f"{h:g}")
    return ET.tostring(clean_root, encoding="unicode"), round(w), round(h), removed


# ---------- доступ к картам ----------

def _map(map_id):
    m = next((x for x in db.items("locmaps") if x["id"] == map_id), None)
    if not m:
        bad("Карта не найдена.", 404)
    return m


def _visible_map(v, map_id):
    m = _map(map_id)
    if not logic.locmap_visible(m, v):
        bad("Карта не найдена.", 404)
    return m


def _save_map(m):
    items = [m if x["id"] == m["id"] else x for x in db.items("locmaps")]
    db.set_items("locmaps", items)


def _gm(v):
    if not v.gm:
        bad("Только для мастера.", 403)


def _audience(vis, known):
    """Персонажи, которым видна запись с такой видимостью."""
    if vis == "стол":
        return sorted(logic.char_map())
    return sorted(known) if vis == "знают" else []


def _obj_visible(o, v):
    if v.gm:
        return True
    return o.get("vis") == "стол" or (o.get("vis") == "знают" and bool(set(v.chars) & set(o.get("known", []))))


# ---------- рисунки ----------

def drawing(v, map_id, role):
    """(SVG-текст, версия) для показа. Рисунок мастера только мастеру; рисунок игроков тем, кому видна карта."""
    if role not in ROLES:
        bad("Рисунок не найден.", 404)
    if role == "gm":
        _gm(v)
    _visible_map(v, map_id)
    with db.lock:
        row = db.conn().execute("SELECT svg, updated FROM locmap_files WHERE map_id=? AND role=?", (map_id, role)).fetchone()
    if not row:
        bad("Рисунка нет.", 404)
    return row["svg"], int(row["updated"])


def save_drawing(v, map_id, role, raw):
    """Загрузка рисунка мастером. Возвращает сообщение (с предупреждением, если что-то пришлось убрать)."""
    _gm(v)
    if role not in ROLES:
        bad("Выберите рисунок: игроков или мастера.")
    try:
        svg, w, h, removed = sanitize_svg(raw)
    except SvgError as ex:
        bad(str(ex))
    with db.lock:
        m = _map(map_id)
        old = m.get("dw", {}).get(role)
        db.conn().execute("INSERT INTO locmap_files(map_id,role,svg,w,h,updated) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT(map_id,role) DO UPDATE SET svg=excluded.svg, w=excluded.w, h=excluded.h, updated=excluded.updated",
                          (map_id, role, svg, w, h, time.time()))
        m.setdefault("dw", {})[role] = {"w": w, "h": h, "v": int(time.time())}
        _save_map(m)
        db.bump()
    msg = "Рисунок загружен"
    if removed:
        msg += ". Из него убрано то, что портал не показывает: " + ", ".join(f"{t} ×{n}" for t, n in sorted(removed.items()))
    if old and (old["w"], old["h"]) != (w, h):
        msg += ". Размер рисунка изменился: проверьте, не сместились ли метки"
    return msg


def delete_drawing(v, map_id, role):
    _gm(v)
    if role not in ROLES:
        bad("Рисунок не найден.", 404)
    with db.lock:
        m = _map(map_id)
        if role not in m.get("dw", {}):
            bad("Такого рисунка нет.", 404)
        db.conn().execute("DELETE FROM locmap_files WHERE map_id=? AND role=?", (map_id, role))
        m["dw"].pop(role, None)
        for o in m.get("objects", []):
            o.get("at", {}).pop(role, None)
        _save_map(m)
        db.bump()
    return "Рисунок убран"


def remove(map_id):
    """Окончательное удаление карты из корзины: рисунки, лента и пометки."""
    with db.lock:
        for table in ("locmap_files", "locmap_feed", "locmap_pins"):
            db.conn().execute(f"DELETE FROM {table} WHERE map_id=?", (map_id,))


# ---------- метки ----------

KEY_RE = re.compile(r"^[\w .\-/№]{1,20}$")


def _norm_object(raw, m, old):
    """Проверенная метка. raw поверх old: можно прислать только то, что меняется (например, одно состояние)."""
    chars = logic.char_map()
    cur = dict(old or {})
    cur.update({k: v for k, v in raw.items() if k != "id"})
    name = clean(cur.get("name"), 80)
    if not name:
        bad("Укажите название метки.")
    key = str(cur.get("key") or "").strip()
    if key and (len(key) > 20 or not KEY_RE.match(key)):
        bad("Короткая подпись метки: до 20 знаков, буквы, цифры и пробел.")
    vis = one_of(cur.get("vis"), VIS, "мастер")
    known = listed(cur.get("known"), chars)
    if vis == "знают" and not known:
        bad("Отметьте, какие персонажи знают об этой метке.")
    at = {}
    raw_at = cur.get("at") if isinstance(cur.get("at"), dict) else {}
    for role in ROLES:
        p = raw_at.get(role)
        if p is None or p == "":
            continue
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            bad("Положение метки: два числа (x, y) на рисунке.")
        x, y = logic.to_int(p[0], "Положение метки: целые числа."), logic.to_int(p[1], "Положение метки: целые числа.")
        size = m.get("dw", {}).get(role)
        wmax, hmax = (size["w"], size["h"]) if size else (MAX_DIM, MAX_DIM)
        if not (0 <= x <= wmax and 0 <= y <= hmax):
            bad("Метка за краем рисунка. Поставьте её внутри рисунка.")
        at[role] = [x, y]
    return {"id": (old or {}).get("id") or "o" + uuid.uuid4().hex[:8], "key": key, "name": name,
            "kind": one_of(cur.get("kind"), OBJ_KINDS, "place"), "status": one_of(cur.get("status"), STATUSES, ""),
            "vis": vis, "known": known if vis == "знают" else [], "note": clean(cur.get("note"), 1000, True),
            "gm_note": clean(cur.get("gm_note"), 2000, True), "at": at}


def _same_key(m, obj):
    return obj["key"] and any(o["key"].lower() == obj["key"].lower() and o["id"] != obj["id"] for o in m.get("objects", []))


def _announcement(old, obj):
    """Что написать в ленту, когда метка стала видна или поменяла состояние. Пусто, если игрокам сообщать нечего."""
    if obj["vis"] == "мастер":
        return ""
    if not old or old["vis"] == "мастер":
        return f"Открыто на карте: «{obj['name']}»"
    if old["status"] != obj["status"] and obj["status"]:
        return f"«{obj['name']}»: {STATUSES[obj['status']]}"
    return ""


def _post_feed(map_id, text, vis, known, obj_id="", ts=None):
    today = logic.now()[0]
    with db.lock:
        db.conn().execute("INSERT INTO locmap_feed(map_id,ts,gdate,obj,text,vis,known) VALUES(?,?,?,?,?,?,?)",
                          (map_id, ts or time.time(), today, obj_id, text, vis, json.dumps(known, ensure_ascii=False)))
        db.conn().execute("DELETE FROM locmap_feed WHERE map_id=? AND id NOT IN (SELECT id FROM locmap_feed WHERE map_id=? ORDER BY id DESC LIMIT ?)",
                          (map_id, map_id, MAX_FEED))


def save_object(v, map_id, raw, announce=True, notify_players=False):
    """Добавить или изменить метку (raw["id"] есть: изменить). Возвращает (сообщение, метка)."""
    _gm(v)
    if not isinstance(raw, dict):
        bad("Метка заполнена неверно.")
    with db.lock:
        m = _map(map_id)
        objects = m.setdefault("objects", [])
        old = next((o for o in objects if o["id"] == raw.get("id")), None) if raw.get("id") else None
        if raw.get("id") and not old:
            bad("Метка не найдена, возможно, её уже удалили.", 404)
        if not old and len(objects) >= MAX_OBJECTS:
            bad(f"На карте не больше {MAX_OBJECTS} меток.", 409)
        obj = _norm_object(raw, m, old)
        if _same_key(m, obj):
            bad(f"Подпись «{obj['key']}» уже занята другой меткой этой карты.", 409)
        if old:
            objects[objects.index(old)] = obj
        else:
            objects.append(obj)
        _save_map(m)
        text = _announcement(old, obj) if announce else ""
        if text:
            _post_feed(map_id, text, obj["vis"], obj["known"], obj["id"])
        db.bump()
    if text and notify_players:
        notify.to_characters(_audience(obj["vis"], obj["known"]), f"Карта «{m['name']}»: {text}.", "maps", kind="map")
    return ("Метка сохранена" if old else "Метка добавлена"), obj


def delete_object(v, map_id, obj_id):
    _gm(v)
    with db.lock:
        m = _map(map_id)
        found = next((o for o in m.get("objects", []) if o["id"] == obj_id), None)
        if not found:
            bad("Метка не найдена.", 404)
        m["objects"] = [o for o in m["objects"] if o["id"] != obj_id]
        _save_map(m)
        db.bump()
    return "Метка удалена"


def import_objects(v, map_id, items):
    """Метки пачкой (JSON из чата, где сделана карта). По короткой подписи (key) метка обновляется, новые добавляются. Видимость и состояние
    существующих меток не меняются, новые метки скрыты от игроков. Возвращает отчёт."""
    _gm(v)
    if not isinstance(items, list) or not items:
        bad("Нет ни одной метки.")
    if len(items) > MAX_IMPORT:
        bad(f"За один раз можно загрузить не больше {MAX_IMPORT} меток.")
    report = {"add": 0, "update": 0, "skip": 0, "error": 0, "items": []}
    with db.lock:
        m = _map(map_id)
        objects = m.setdefault("objects", [])
        seen = set()
        for n, raw in enumerate(items, 1):
            title = clean(raw.get("name") or raw.get("key"), 80) if isinstance(raw, dict) else ""
            try:
                if not isinstance(raw, dict):
                    bad("Метка заполнена неверно.")
                key = clean(raw.get("key"), 20)
                if key and key.lower() in seen:
                    bad("Подпись повторяется в этом файле.")
                old = next((o for o in objects if key and o["key"].lower() == key.lower()), None)
                body = {k: x for k, x in raw.items() if k not in ("id", "vis", "known", "status")}
                if old:
                    merged_at = dict(old.get("at", {}))
                    given = raw.get("at") if isinstance(raw.get("at"), dict) else {}
                    merged_at.update({r: p for r, p in given.items() if p is not None})     # присланное положение дополняет прежнее
                    body["at"] = merged_at
                    obj = _norm_object(dict(old, **body), m, old)
                    if obj == old:
                        report["skip"] += 1
                        report["items"].append({"n": n, "title": title, "status": "skip", "msg": "без изменений"})
                        seen.add(key.lower())
                        continue
                    objects[objects.index(old)] = obj
                    report["update"] += 1
                    report["items"].append({"n": n, "title": title, "status": "update", "msg": "обновлено (видимость и состояние не менялись)"})
                else:
                    if len(objects) >= MAX_OBJECTS:
                        bad(f"На карте не больше {MAX_OBJECTS} меток.")
                    obj = _norm_object(body, m, None)
                    if _same_key(m, obj):
                        bad("Эта подпись уже занята.")
                    objects.append(obj)
                    report["add"] += 1
                    report["items"].append({"n": n, "title": title, "status": "add", "msg": "новая метка скрыта от игроков"})
                if key:
                    seen.add(key.lower())
            except logic.HTTPException as ex:
                report["error"] += 1
                report["items"].append({"n": n, "title": title or f"№{n}", "status": "error", "msg": str(ex.detail)})
        if report["add"] or report["update"]:
            _save_map(m)
            db.bump()
    return report


# ---------- лента обновлений ----------

def post_update(v, map_id, text, vis="стол", known=None, notify_players=False):
    """Объявление мастера в ленту карты."""
    _gm(v)
    text = clean(text, 300)
    if not text:
        bad("Напишите, что изменилось.")
    vis = one_of(vis, ("стол", "знают"), "стол")
    known = listed(known, logic.char_map())
    if vis == "знают" and not known:
        bad("Отметьте, каким персонажам это видно.")
    with db.lock:
        m = _map(map_id)
        _post_feed(map_id, text, vis, known if vis == "знают" else [])
        db.bump()
    if notify_players:
        notify.to_characters(_audience(vis, known), f"Карта «{m['name']}»: {text}", "maps", kind="map")
    return "Объявление добавлено"


def delete_update(v, map_id, feed_id):
    _gm(v)
    with db.lock:
        _map(map_id)
        cur = db.conn().execute("DELETE FROM locmap_feed WHERE id=? AND map_id=?", (feed_id, map_id))
        if cur.rowcount != 1:
            bad("Записи в ленте нет.", 404)
        db.bump()
    return "Запись убрана из ленты"


def _feed(v, map_id):
    hz = logic.horizon(v)
    with db.lock:
        rows = db.conn().execute("SELECT id,ts,gdate,obj,text,vis,known FROM locmap_feed WHERE map_id=? ORDER BY id DESC LIMIT 100", (map_id,)).fetchall()
    mine = set(v.chars)
    out = []
    for r in rows:
        known = json.loads(r["known"])
        if not v.gm:
            if r["vis"] == "знают" and not mine & set(known):
                continue
            if hz and r["gdate"] > hz:
                continue
        out.append({"id": r["id"], "ts": int(r["ts"] * 1000), "date": r["gdate"], "obj": r["obj"], "text": r["text"],
                    **({"vis": r["vis"], "known": known} if v.gm else {})})
    return out


# ---------- пометки группы ----------

def add_pin(v, map_id, text, x, y, char=None):
    if v.gm:
        bad("Пометки на карту ставят игроки.", 403)
    char = v.acting(char or (v.chars[0] if len(v.chars) == 1 else None))
    text = clean(text, 120)
    if not text:
        bad("Напишите пометку.")
    with db.lock:
        m = _visible_map(v, map_id)
        size = m.get("dw", {}).get("player")
        if not size:
            bad("У этой карты пока нет рисунка для игроков.")
        px, py = logic.to_int(x, "Положение пометки: целые числа."), logic.to_int(y, "Положение пометки: целые числа.")
        if not (0 <= px <= size["w"] and 0 <= py <= size["h"]):
            bad("Пометка за краем рисунка.")
        n = db.conn().execute("SELECT COUNT(*) AS n FROM locmap_pins WHERE map_id=?", (map_id,)).fetchone()["n"]
        if n >= MAX_PINS:
            bad(f"На карте уже {MAX_PINS} пометок. Попросите мастера или товарищей убрать лишние.", 409)
        db.conn().execute("INSERT INTO locmap_pins(map_id,tg_id,char,x,y,text,created) VALUES(?,?,?,?,?,?,?)", (map_id, v.tg_id, char, px, py, text, time.time()))
        db.bump()
    return "Пометка добавлена"


def delete_pin(v, map_id, pin_id):
    with db.lock:
        _visible_map(v, map_id)
        row = db.conn().execute("SELECT tg_id, char FROM locmap_pins WHERE id=? AND map_id=?", (pin_id, map_id)).fetchone()
        if not row:
            bad("Пометки нет.", 404)
        if not v.gm and row["tg_id"] != v.tg_id and row["char"] not in v.chars:
            bad("Убрать можно только свою пометку.", 403)
        db.conn().execute("DELETE FROM locmap_pins WHERE id=?", (pin_id,))
        db.bump()
    return "Пометка убрана"


def _pins(map_id):
    with db.lock:
        rows = db.conn().execute("SELECT id,char,x,y,text,created FROM locmap_pins WHERE map_id=? ORDER BY id", (map_id,)).fetchall()
    return [{"id": r["id"], "char": r["char"], "x": r["x"], "y": r["y"], "text": r["text"], "ts": int(r["created"] * 1000)} for r in rows]


# ---------- карта целиком ----------

def detail(v, map_id):
    """Карта со всем, что видит этот человек: метки, лента, пометки. Игроку без заметок мастера, без положения на рисунке мастера и без скрытых меток."""
    m = _visible_map(v, map_id)
    objects = []
    for o in m.get("objects", []):
        if not _obj_visible(o, v):
            continue
        if v.gm:
            objects.append(o)
        else:
            card = {k: o[k] for k in ("id", "key", "name", "kind", "status", "note")}
            if "player" in o.get("at", {}):
                card["at"] = {"player": o["at"]["player"]}
            objects.append(card)
    out = {"id": m["id"], "name": m["name"], "note": m.get("note", ""), "place": m.get("place", ""), "objects": objects,
           "dw": m.get("dw", {}) if v.gm else {k: x for k, x in m.get("dw", {}).items() if k == "player"},
           "feed": _feed(v, map_id), "pins": _pins(map_id), "kinds": OBJ_KINDS, "statuses": STATUSES}
    if v.gm:
        out.update(gm_note=m.get("gm_note", ""), vis=m.get("vis", "мастер"), known=m.get("known", []))
    elif m.get("place") and m["place"] not in {p["id"] for p in logic.places_for(v)}:
        out["place"] = ""
    return out
