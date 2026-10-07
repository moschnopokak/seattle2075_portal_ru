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

from . import db, logic, notify, outbox
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
MAX_SHAPE = 150
MAX_DEADLINES = 60
MAX_LINKS = 12
MAX_LOG = 500
MAX_FX = 6
COUNT_MIN, COUNT_MAX = -999, 9999
LINK_KINDS = ("dossier", "handouts")
PIN_KINDS = {"note": "Заметка", "danger": "Опасность", "find": "Находка", "question": "Вопрос мастеру"}
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
            o.get("shape", {}).pop(role, None)
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
    at, shape = {}, {}
    raw_at = cur.get("at") if isinstance(cur.get("at"), dict) else {}
    raw_shape = cur.get("shape") if isinstance(cur.get("shape"), dict) else {}
    for role in ROLES:
        size = m.get("dw", {}).get(role)
        wmax, hmax = (size["w"], size["h"]) if size else (MAX_DIM, MAX_DIM)
        p = raw_at.get(role)
        if p is not None and p != "":
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                bad("Положение метки: два числа (x, y) на рисунке.")
            x, y = logic.to_int(p[0], "Положение метки: целые числа."), logic.to_int(p[1], "Положение метки: целые числа.")
            if not (0 <= x <= wmax and 0 <= y <= hmax):
                bad("Метка за краем рисунка. Поставьте её внутри рисунка.")
            at[role] = [x, y]
        if raw_shape.get(role) not in (None, "", []):
            shape[role] = _shape_points(raw_shape[role], wmax, hmax)
    return {"id": (old or {}).get("id") or "o" + uuid.uuid4().hex[:8], "key": key, "name": name,
            "kind": one_of(cur.get("kind"), OBJ_KINDS, "place"), "status": one_of(cur.get("status"), STATUSES, ""),
            "vis": vis, "known": known if vis == "знают" else [], "note": clean(cur.get("note"), 1000, True),
            "gm_note": clean(cur.get("gm_note"), 2000, True), "at": at, "shape": shape, "play": cur.get("play") is True,
            "by": (old or {}).get("by", ""), "date": (old or {}).get("date", ""),
            "count": _count(cur.get("count")), "fx": _fx_list(cur.get("fx")), "fx_on": (old or {}).get("fx_on", False),
            "links": _links(cur.get("links"))}


def _count(value):
    """Счётчик мастера у зоны (например, «фон»): целое число или пусто."""
    if value is None or value == "":
        return None
    n = logic.to_int(value, "Счётчик: целое число.")
    if not COUNT_MIN <= n <= COUNT_MAX:
        bad(f"Счётчик: число от {COUNT_MIN} до {COUNT_MAX}.")
    return n


def _fx_list(value):
    """Правила расчистки: что менять в счётчиках, когда зона расчищена. [{"to": "self" или подпись другой метки, "delta": -2}]"""
    if value is None or value == "" or value == []:
        return []
    if not isinstance(value, list) or len(value) > MAX_FX:
        bad(f"Правила расчистки: не больше {MAX_FX} пунктов.")
    out = []
    for e in value:
        if not isinstance(e, dict):
            bad("Правило расчистки заполнено неверно.")
        to = clean(e.get("to"), 20)
        delta = logic.to_int(e.get("delta"), "Правило расчистки: изменение счётчика, целое число.")
        if not to or not -99 <= delta <= 99 or delta == 0:
            bad("Правило расчистки: укажите, чей счётчик менять, и на сколько (от −99 до 99, не ноль).")
        out.append({"to": "self" if to.lower() in ("self", "этой", "эта", "сама") else to, "delta": delta})
    return out


def _links(value):
    """Связи метки с карточками досье и раздатками: только существующие, без повторов."""
    if value is None or value == "" or value == []:
        return []
    if not isinstance(value, list) or len(value) > MAX_LINKS:
        bad(f"К метке можно привязать не больше {MAX_LINKS} карточек.")
    out = []
    for e in value:
        if not isinstance(e, dict) or e.get("kind") not in LINK_KINDS or not isinstance(e.get("id"), str):
            bad("Связь метки заполнена неверно.")
        if not any(x["id"] == e["id"] for x in db.items(e["kind"])):
            bad("Связанная карточка не найдена: возможно, её уже удалили.")
        if {"kind": e["kind"], "id": e["id"]} not in out:
            out.append({"kind": e["kind"], "id": e["id"]})
    return out


def _shape_points(points, wmax, hmax):
    """Контур зоны: от 3 до MAX_SHAPE точек внутри рисунка, числа округляются до целых. Контур не должен быть линией."""
    if not isinstance(points, (list, tuple)) or not 3 <= len(points) <= MAX_SHAPE:
        bad(f"Контур зоны: от 3 до {MAX_SHAPE} точек.")
    out = []
    for p in points:
        if not (isinstance(p, (list, tuple)) and len(p) == 2) or any(isinstance(c, bool) or not isinstance(c, (int, float)) or c != c or abs(c) > MAX_DIM for c in p):
            bad("Контур зоны: каждая точка это два числа (x, y).")
        x, y = int(round(p[0])), int(round(p[1]))
        if not (0 <= x <= wmax and 0 <= y <= hmax):
            bad("Контур зоны выходит за край рисунка.")
        if not out or out[-1] != [x, y]:
            out.append([x, y])
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()                                                   # замыкающая точка, равная первой, не нужна
    twice = sum(out[i][0] * out[(i + 1) % len(out)][1] - out[(i + 1) % len(out)][0] * out[i][1] for i in range(len(out)))
    if len(out) < 3 or twice == 0:
        bad("Контур зоны не должен быть линией: поставьте не меньше трёх точек не на одной прямой.")
    return out


def _apply_fx(m, o, sign):
    """Правила расчистки: счётчик этой зоны или другой (по подписи) меняется на delta (sign=-1 откатывает)."""
    for e in o.get("fx", []):
        target = o if e["to"] == "self" else next((x for x in m.get("objects", []) if x["key"] and x["key"].lower() == e["to"].lower()), None)
        if target is not None and target.get("count") is not None:
            target["count"] += sign * e["delta"]


def _fx_sync(m, o):
    """Правила действуют, пока зона расчищена: при расчистке применяются один раз, при снятии отметки откатываются."""
    want = o.get("status") == "cleared"
    if want and not o.get("fx_on"):
        _apply_fx(m, o, 1)
        o["fx_on"] = True
    elif not want and o.get("fx_on"):
        _apply_fx(m, o, -1)
        o["fx_on"] = False


def _transition(m, o, by, date):
    """Состояние метки изменилось: записать, кто и когда отметил, и применить правила расчистки (метка уже лежит в m["objects"])."""
    o["by"], o["date"] = (by, date) if o["status"] else ("", "")
    _fx_sync(m, o)


def _log(map_id, who, kind, obj_id, text, prev=None):
    """Журнал карты (виден мастеру): что и кто менял; у состояния и удаления хранится прежнее значение для отмены."""
    with db.lock:
        db.conn().execute("INSERT INTO locmap_log(map_id,ts,gdate,who,kind,obj,text,prev) VALUES(?,?,?,?,?,?,?,?)",
                          (map_id, time.time(), logic.now()[0], who, kind, obj_id, text, json.dumps(prev or {}, ensure_ascii=False)))
        db.conn().execute("DELETE FROM locmap_log WHERE map_id=? AND id NOT IN (SELECT id FROM locmap_log WHERE map_id=? ORDER BY id DESC LIMIT ?)",
                          (map_id, map_id, MAX_LOG))


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
        if obj["status"] != (old or {}).get("status", ""):
            _transition(m, obj, "gm", logic.now()[0])
            _log(map_id, "gm", "status", obj["id"], f"Мастер: «{obj['name']}», {STATUSES[obj['status']] or 'отметка снята'}",
                 {"status": (old or {}).get("status", ""), "by": (old or {}).get("by", ""), "date": (old or {}).get("date", "")})
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
        _log(map_id, "gm", "delete", obj_id, f"Мастер удалил метку «{found['name']}»", found)
        _save_map(m)
        db.bump()
    return "Метка удалена"


_DEFAULTS = {"play": False, "shape": {}, "by": "", "date": "", "count": None, "fx": [], "fx_on": False, "links": []}    # поля, которых нет у старых меток


def import_objects(v, map_id, items, open_new=False, deadlines=None, counter=None):
    """Метки пачкой (JSON из чата, где сделана карта). По короткой подписи (key) метка обновляется, новые добавляются. Видимость и состояние
    существующих меток не меняются, новые метки скрыты от игроков (или открыты всем, если мастер так выбрал: open_new). Вместе с метками можно
    прислать сроки (deadlines, метка указывается подписью) и название счётчика (counter). Возвращает отчёт."""
    _gm(v)
    if items is None and deadlines:
        items = []
    if not isinstance(items, list) or not (items or deadlines):
        bad("Нет ни одной метки.")
    if len(items) > MAX_IMPORT:
        bad(f"За один раз можно загрузить не больше {MAX_IMPORT} меток.")
    if deadlines is not None and (not isinstance(deadlines, list) or len(deadlines) > MAX_DEADLINES):
        bad(f"Сроки: список, не больше {MAX_DEADLINES}.")
    report = {"add": 0, "update": 0, "skip": 0, "error": 0, "items": [], "d_add": 0, "d_update": 0, "d_skip": 0}
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
                body = {k: x for k, x in raw.items() if k not in ("id", "vis", "known", "status", "links", "fx_on", "by", "date")}
                if old:
                    body.pop("count", None)                                                        # повторная загрузка не сбрасывает счётчик, который мастер уже менял
                    for field in ("at", "shape"):                                                   # присланное положение и контур дополняют прежние
                        merged = dict(old.get(field, {}))
                        given = raw.get(field) if isinstance(raw.get(field), dict) else {}
                        merged.update({r: p for r, p in given.items() if p is not None})
                        body[field] = merged
                    obj = _norm_object(dict(old, **body), m, old)
                    if obj == {**_DEFAULTS, **old}:
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
                    obj = _norm_object(dict(body, vis="стол") if open_new else body, m, None)
                    if _same_key(m, obj):
                        bad("Эта подпись уже занята.")
                    objects.append(obj)
                    report["add"] += 1
                    report["items"].append({"n": n, "title": title, "status": "add", "msg": "новая метка открыта игрокам" if open_new else "новая метка скрыта от игроков"})
                if key:
                    seen.add(key.lower())
            except logic.HTTPException as ex:
                report["error"] += 1
                report["items"].append({"n": n, "title": title or f"№{n}", "status": "error", "msg": str(ex.detail)})
        if open_new and report["add"]:
            _post_feed(map_id, f"Открыто на карте: {report['add']} {outbox._plural(report['add'], 'метка', 'метки', 'меток')}", "стол", [])
        changed = bool(report["add"] or report["update"])
        name = clean(counter, 30) if isinstance(counter, str) else ""
        if name and m.get("counter") != name:
            m["counter"] = name
            changed = True
        if deadlines:
            changed = _import_deadlines(m, deadlines, report) or changed
        if changed:
            _save_map(m)
            db.bump()
    return report


def _import_deadlines(m, deadlines, report):
    """Сроки из загрузки: метка указывается подписью (obj: «Г4»). Тот же день и то же название считаются уже имеющимся сроком."""
    items = m.setdefault("deadlines", [])
    keys = {o["key"].lower(): o["id"] for o in m.get("objects", []) if o["key"]}
    changed = False
    for n, raw in enumerate(deadlines, 1):
        title = clean(raw.get("title"), 120) if isinstance(raw, dict) else ""
        try:
            if not isinstance(raw, dict):
                bad("Срок заполнен неверно.")
            body = {k: x for k, x in raw.items() if k not in ("id", "done", "done_date")}
            ref = body.pop("obj", "")
            body["obj"] = ""
            if ref not in (None, ""):
                body["obj"] = keys.get(str(ref).strip().lower()) or bad(f"Метки с подписью «{ref}» на карте нет.")
            old = next((d for d in items if d["date"] == raw.get("date") and d["title"].lower() == title.lower()), None) if title else None
            if not old and len(items) >= MAX_DEADLINES:
                bad(f"На карте не больше {MAX_DEADLINES} сроков.")
            d = _norm_deadline(body, m, old)
            if old and d == old:
                report["d_skip"] += 1
            elif old:
                items[items.index(old)] = d
                report["d_update"] += 1
                changed = True
            else:
                items.append(d)
                report["d_add"] += 1
                changed = True
        except logic.HTTPException as ex:
            report["error"] += 1
            report["items"].append({"n": n, "title": "Срок: " + (title or f"№{n}"), "status": "error", "msg": str(ex.detail)})
    items.sort(key=lambda x: (x["date"], x["title"]))
    return changed


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


# ---------- отметка зоны игроками ----------

def mark_object(v, map_id, obj_id, status, text="", char=None):
    """Игрок отмечает состояние метки или зоны («расчищено», «опасно»), если мастер это разрешил (play). Запись попадает в ленту
    для тех, кто видит метку, а мастеру уходит сообщение. Можно только дописать короткий комментарий, не меняя состояние."""
    if v.gm:
        bad("Состояние в карточке метки мастер меняет сам.", 403)
    char = v.acting(char or (v.chars[0] if len(v.chars) == 1 else None))
    if not isinstance(status, str) or status not in STATUSES:
        bad("Неизвестное состояние.")
    text = clean(text, 120)
    with db.lock:
        m = _visible_map(v, map_id)
        o = next((x for x in m.get("objects", []) if x["id"] == obj_id), None)
        if not o or not _obj_visible(o, v):
            bad("Метка не найдена, возможно, её уже убрали.", 404)
        if not o.get("play"):
            bad("Мастер не разрешил игрокам отмечать эту метку.", 403)
        changed = status != o["status"]
        if not changed and not text:
            return "Состояние уже такое", None
        who = logic.char_map().get(char, {}).get("name", char)
        what = (STATUSES[status] or "отметка снята") if changed else ""
        line = f"{who}: «{o['name']}»" + (f", {what}" if what else "") + (f". {text}" if text else "")
        if changed:
            prev = {"status": o["status"], "by": o.get("by", ""), "date": o.get("date", "")}
            o["status"] = status
            _transition(m, o, char, logic.now()[0])
            _log(map_id, char, "status", o["id"], line, prev)
            _save_map(m)
        _post_feed(map_id, line, o["vis"], o["known"], o["id"])
        db.bump()
    notify.to_gm(f"Карта «{m['name']}»: {line}.", "maps", kind="map")
    return ("Отмечено: " + what if what else "Комментарий добавлен"), line


# ---------- пометки группы ----------

def add_pin(v, map_id, text, x, y, char=None, kind="note"):
    if v.gm:
        bad("Пометки на карту ставят игроки.", 403)
    char = v.acting(char or (v.chars[0] if len(v.chars) == 1 else None))
    kind = one_of(kind, PIN_KINDS, "note")
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
        db.conn().execute("INSERT INTO locmap_pins(map_id,tg_id,char,x,y,text,created,kind) VALUES(?,?,?,?,?,?,?,?)",
                          (map_id, v.tg_id, char, px, py, text, time.time(), kind))
        db.bump()
    if kind == "question":
        who = logic.char_map().get(char, {}).get("name", char)
        notify.to_gm(f"Вопрос с карты «{m['name']}»: {who}: {text}", "maps", kind="map")
    return "Вопрос мастеру отправлен" if kind == "question" else "Пометка добавлена"


def answer_pin(v, map_id, pin_id, text, notify_players=False):
    """Ответ мастера на вопрос игрока. Видят все, у кого открыта карта; в ленту идёт запись, чтобы никто не пропустил."""
    _gm(v)
    text = clean(text, 300)
    if not text:
        bad("Напишите ответ.")
    with db.lock:
        m = _map(map_id)
        row = db.conn().execute("SELECT kind, text, char FROM locmap_pins WHERE id=? AND map_id=?", (pin_id, map_id)).fetchone()
        if not row:
            bad("Пометки нет.", 404)
        if row["kind"] != "question":
            bad("Отвечать можно только на вопросы мастеру.")
        db.conn().execute("UPDATE locmap_pins SET answer=?, answered=? WHERE id=?", (text, time.time(), pin_id))
        line = f"Ответ мастера на вопрос «{row['text']}»: {text}"
        _post_feed(map_id, line, "стол", [])
        db.bump()
    if notify_players:
        notify.to_characters(_audience(m.get("vis", "мастер"), m.get("known", [])), f"Карта «{m['name']}»: {line}", "maps", kind="map")
    return "Ответ записан"


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
        rows = db.conn().execute("SELECT id,char,x,y,text,created,kind,answer,answered FROM locmap_pins WHERE map_id=? ORDER BY id", (map_id,)).fetchall()
    return [{"id": r["id"], "char": r["char"], "x": r["x"], "y": r["y"], "text": r["text"], "ts": int(r["created"] * 1000), "kind": r["kind"],
             "answer": r["answer"], "answered": int((r["answered"] or 0) * 1000)} for r in rows]


# ---------- фишка группы «Мы здесь» ----------

def set_party(v, map_id, x, y):
    """Где сейчас группа: одна точка на рисунке игроков, её ставят и двигают игроки и мастер."""
    with db.lock:
        m = _visible_map(v, map_id)
        size = m.get("dw", {}).get("player")
        if not size:
            bad("У этой карты пока нет рисунка для игроков.")
        px, py = logic.to_int(x, "Положение группы: целые числа."), logic.to_int(y, "Положение группы: целые числа.")
        if not (0 <= px <= size["w"] and 0 <= py <= size["h"]):
            bad("Группа за краем рисунка.")
        who = "gm" if v.gm else (v.chars[0] if v.chars else "")
        m["party"] = {"x": px, "y": py, "by": who, "date": logic.now()[0]}
        _save_map(m)
        db.bump()
    return "Группа отмечена на карте"


def clear_party(v, map_id):
    with db.lock:
        m = _visible_map(v, map_id)
        if not m.get("party"):
            return "Группа и так не отмечена"
        m["party"] = {}
        _save_map(m)
        db.bump()
    return "Отметка группы убрана"


# ---------- сроки ----------

def _norm_deadline(raw, m, old=None):
    chars = logic.char_map()
    cur = dict(old or {})
    cur.update({k: x for k, x in raw.items() if k not in ("id", "done", "done_date")})
    title = clean(cur.get("title"), 120)
    if not title:
        bad("Назовите срок: что наступит в этот день.")
    date = logic.check_date(cur.get("date"), "Дата срока")
    obj = cur.get("obj") if isinstance(cur.get("obj"), str) else ""
    if obj and not any(o["id"] == obj for o in m.get("objects", [])):
        bad("Метка, к которой привязан срок, не найдена.")
    vis = one_of(cur.get("vis"), VIS, "мастер")
    known = listed(cur.get("known"), chars)
    if vis == "знают" and not known:
        bad("Отметьте, каким персонажам виден срок.")
    status = cur.get("status") or ""
    if not isinstance(status, str) or status not in STATUSES:
        bad("Неизвестное состояние в сроке.")
    delta = cur.get("delta")
    delta = None if delta in (None, "") else logic.to_int(delta, "Изменение счётчика в сроке: целое число.")
    if delta is not None and not -99 <= delta <= 99:
        bad("Изменение счётчика в сроке: от −99 до 99.")
    return {"id": (old or {}).get("id") or "d" + uuid.uuid4().hex[:8], "date": date, "title": title, "note": clean(cur.get("note"), 1000, True), "obj": obj,
            "vis": vis, "known": known if vis == "знают" else [], "status": status, "reveal": cur.get("reveal") is True, "delta": delta or None,
            "done": (old or {}).get("done", False), "done_date": (old or {}).get("done_date", "")}


def save_deadline(v, map_id, raw):
    _gm(v)
    if not isinstance(raw, dict):
        bad("Срок заполнен неверно.")
    with db.lock:
        m = _map(map_id)
        items = m.setdefault("deadlines", [])
        old = next((d for d in items if d["id"] == raw.get("id")), None) if raw.get("id") else None
        if raw.get("id") and not old:
            bad("Срок не найден, возможно, его уже убрали.", 404)
        if not old and len(items) >= MAX_DEADLINES:
            bad(f"На карте не больше {MAX_DEADLINES} сроков.", 409)
        d = _norm_deadline(raw, m, old)
        if old:
            items[items.index(old)] = d
        else:
            items.append(d)
        items.sort(key=lambda x: (x["date"], x["title"]))
        _save_map(m)
        db.bump()
    return ("Срок сохранён" if old else "Срок добавлен"), d


def delete_deadline(v, map_id, deadline_id):
    _gm(v)
    with db.lock:
        m = _map(map_id)
        if not any(d["id"] == deadline_id for d in m.get("deadlines", [])):
            bad("Срок не найден.", 404)
        m["deadlines"] = [d for d in m["deadlines"] if d["id"] != deadline_id]
        _save_map(m)
        db.bump()
    return "Срок убран"


def _add_count(m, targets, delta):
    n = 0
    for o in targets:
        if o.get("count") is not None:
            o["count"] += delta
            n += 1
    return n


def apply_deadline(v, map_id, deadline_id, apply=True):
    """Срок наступил: применить его последствия (состояние, открыть метку, счётчик) или просто отметить выполненным (apply=False)."""
    _gm(v)
    today = logic.now()[0]
    with db.lock:
        m = _map(map_id)
        d = next((x for x in m.get("deadlines", []) if x["id"] == deadline_id), None)
        if not d:
            bad("Срок не найден.", 404)
        if d["done"]:
            bad("Этот срок уже отмечен.", 409)
        o = next((x for x in m.get("objects", []) if x["id"] == d["obj"]), None) if d["obj"] else None
        did = []
        if apply:
            if o and d["status"] and d["status"] != o["status"]:
                prev = {"status": o["status"], "by": o.get("by", ""), "date": o.get("date", "")}
                o["status"] = d["status"]
                _transition(m, o, "gm", today)
                _log(map_id, "gm", "status", o["id"], f"Срок «{d['title']}»: «{o['name']}», {STATUSES[o['status']]}", prev)
                did.append(f"«{o['name']}»: {STATUSES[o['status']]}")
            if o and d["reveal"] and o["vis"] == "мастер":
                o["vis"], o["known"] = "стол", []
                _post_feed(map_id, f"Открыто на карте: «{o['name']}»", "стол", [], o["id"])
                _log(map_id, "gm", "reveal", o["id"], f"Срок «{d['title']}»: открыта метка «{o['name']}»")
                did.append(f"открыта «{o['name']}»")
            if d["delta"]:
                n = _add_count(m, [o] if o else m.get("objects", []), d["delta"])
                if n:
                    did.append(f"счётчик {d['delta']:+d} ({n})".replace("-", "−"))
        d["done"], d["done_date"] = True, today
        if d["vis"] != "мастер":
            _post_feed(map_id, f"Срок наступил: {d['title']}", d["vis"], d["known"], d["obj"])
        _log(map_id, "gm", "deadline", d["obj"], f"Срок «{d['title']}» " + ("применён" if apply else "отмечен без последствий"))
        _save_map(m)
        db.bump()
    return ("Срок применён" + (": " + "; ".join(did) if did else "")) if apply else "Срок отмечен выполненным"


def _deadlines_for(v, m):
    """Сроки для показа: мастеру все, игроку только открытые ему и не дальше границы «что видят игроки вперёд»."""
    out = []
    hz = logic.horizon(v)
    mine = set(v.chars)
    shown = {o["id"] for o in m.get("objects", []) if _obj_visible(o, v)}
    for d in m.get("deadlines", []):
        if v.gm:
            out.append(d)
            continue
        if d["vis"] == "мастер" or (d["vis"] == "знают" and not mine & set(d["known"])) or (hz and d["date"] > hz):
            continue
        out.append({"id": d["id"], "date": d["date"], "title": d["title"], "obj": d["obj"] if d["obj"] in shown else "", "done": d["done"]})
    return out


def notify_due(old_date, new_date):
    """Игровая дата сдвинулась: мастеру сообщение о сроках на картах, которые наступили за этот переход."""
    if not old_date or not new_date or new_date <= old_date:
        return
    lines = []
    for m in db.items("locmaps"):
        late = [d["title"] for d in m.get("deadlines", []) if not d["done"] and old_date < d["date"] <= new_date]
        if late:
            lines.append(f"«{m['name']}»: " + "; ".join(late[:5]))
    if lines:
        notify.to_gm("Наступили сроки на картах. " + " ".join(lines) + " Откройте раздел «Локации», вкладка «Сроки».", "maps", kind="map")


# ---------- счётчик мастера (фон и тому подобное) ----------

def bump_counter(v, map_id, delta):
    """Изменить счётчик у всех зон, где он задан (например, «полнолуние: фон +1 везде»)."""
    _gm(v)
    delta = logic.to_int(delta, "Изменение счётчика: целое число.")
    if not -99 <= delta <= 99 or delta == 0:
        bad("Изменение счётчика: от −99 до 99, не ноль.")
    with db.lock:
        m = _map(map_id)
        n = _add_count(m, m.get("objects", []), delta)
        if not n:
            bad("Ни у одной зоны нет счётчика: задайте его в карточке зоны.")
        _log(map_id, "gm", "counter", "", f"Мастер: счётчик «{m.get('counter') or 'счётчик'}» {delta:+d} везде ({n})".replace("-", "−"))
        _save_map(m)
        db.bump()
    return f"Счётчик изменён у зон: {n}"


# ---------- отмена ----------

def undo(v, map_id, log_id):
    """Вернуть прежнее состояние метки или саму удалённую метку. Игрокам об отмене сообщает запись в ленте (если метка им открыта)."""
    _gm(v)
    if isinstance(log_id, bool) or not isinstance(log_id, int):
        bad("Действие не найдено.", 404)
    with db.lock:
        m = _map(map_id)
        row = db.conn().execute("SELECT * FROM locmap_log WHERE id=? AND map_id=?", (log_id, map_id)).fetchone()
        if not row:
            bad("Действие не найдено.", 404)
        if row["undone"]:
            bad("Это действие уже отменено.", 409)
        if row["kind"] not in ("status", "delete"):
            bad("Это действие отменить нельзя.")
        prev = json.loads(row["prev"])
        objects = m.setdefault("objects", [])
        if row["kind"] == "status":
            o = next((x for x in objects if x["id"] == row["obj"]), None)
            if not o:
                bad("Метки уже нет: отменять нечего.", 404)
            o["status"], o["by"], o["date"] = prev.get("status", ""), prev.get("by", ""), prev.get("date", "")
            _fx_sync(m, o)
            now = STATUSES[o["status"]] or "отметка снята"
            text = f"Мастер вернул прежнее: «{o['name']}», {now}"
            if o["vis"] != "мастер":
                _post_feed(map_id, f"«{o['name']}»: {now} (мастер вернул прежнее)", o["vis"], o["known"], o["id"])
        else:
            if any(x["id"] == prev.get("id") for x in objects):
                bad("Эта метка уже на карте.", 409)
            if prev.get("key") and any(x["key"].lower() == prev["key"].lower() for x in objects):
                bad(f"Подпись «{prev['key']}» уже занята другой меткой.", 409)
            if len(objects) >= MAX_OBJECTS:
                bad(f"На карте не больше {MAX_OBJECTS} меток.", 409)
            objects.append(prev)
            text = f"Мастер вернул удалённую метку «{prev.get('name', '')}»"
        db.conn().execute("UPDATE locmap_log SET undone=1 WHERE id=?", (log_id,))
        _log(map_id, "gm", "undo", row["obj"], text)
        _save_map(m)
        db.bump()
    return "Отменено"


def _log_rows(map_id):
    with db.lock:
        rows = db.conn().execute("SELECT id,ts,gdate,who,kind,obj,text,undone FROM locmap_log WHERE map_id=? ORDER BY id DESC LIMIT 100", (map_id,)).fetchall()
    return [{"id": r["id"], "ts": int(r["ts"] * 1000), "date": r["gdate"], "who": r["who"], "kind": r["kind"], "obj": r["obj"], "text": r["text"],
             "undone": bool(r["undone"]), "undoable": r["kind"] in ("status", "delete") and not r["undone"]} for r in rows]


# ---------- значок «новое» ----------

def badge_info(v, maps):
    """Для списка карт: игроку номера свежих записей ленты (клиент сравнивает с тем, что он уже видел), мастеру число наступивших сроков
    и неотвеченных вопросов."""
    ids = [m["id"] for m in maps]
    info = {i: {"fresh": [], "due": 0, "open_q": 0} for i in ids}
    if not ids:
        return info
    if v.gm:
        today = logic.now()[0]
        for m in maps:
            info[m["id"]]["due"] = sum(1 for d in m.get("deadlines", []) if not d["done"] and d["date"] <= today)
        with db.lock:
            for r in db.conn().execute("SELECT map_id, COUNT(*) AS n FROM locmap_pins WHERE kind='question' AND answer='' GROUP BY map_id"):
                if r["map_id"] in info:
                    info[r["map_id"]]["open_q"] = r["n"]
        return info
    hz = logic.horizon(v)
    mine = set(v.chars)
    with db.lock:
        rows = db.conn().execute("SELECT id,map_id,gdate,vis,known FROM locmap_feed ORDER BY id DESC LIMIT 800").fetchall()
    for r in rows:
        if r["map_id"] not in info or len(info[r["map_id"]]["fresh"]) >= 30:
            continue
        if r["vis"] == "знают" and not mine & set(json.loads(r["known"])):
            continue
        if hz and r["gdate"] > hz:
            continue
        info[r["map_id"]]["fresh"].append(r["id"])
    return info


# ---------- карта целиком ----------

def detail(v, map_id):
    """Карта со всем, что видит этот человек: метки, лента, пометки, сроки. Игроку без заметок мастера, без счётчиков, без положения на рисунке
    мастера и без скрытых меток."""
    m = _visible_map(v, map_id)
    objects = []
    for o in m.get("objects", []):
        if not _obj_visible(o, v):
            continue
        if v.gm:
            objects.append(o)
        else:
            card = {k: o[k] for k in ("id", "key", "name", "kind", "status", "note")}
            card.update(play=o.get("play") is True, by=o.get("by", ""), date=o.get("date", ""), links=o.get("links", []))
            if "player" in o.get("at", {}):
                card["at"] = {"player": o["at"]["player"]}
            if "player" in o.get("shape", {}):
                card["shape"] = {"player": o["shape"]["player"]}
            objects.append(card)
    out = {"id": m["id"], "name": m["name"], "note": m.get("note", ""), "place": m.get("place", ""), "objects": objects,
           "dw": m.get("dw", {}) if v.gm else {k: x for k, x in m.get("dw", {}).items() if k == "player"},
           "feed": _feed(v, map_id), "pins": _pins(map_id), "deadlines": _deadlines_for(v, m), "party": m.get("party") or None,
           "kinds": OBJ_KINDS, "statuses": STATUSES, "pin_kinds": PIN_KINDS}
    if v.gm:
        out.update(gm_note=m.get("gm_note", ""), vis=m.get("vis", "мастер"), known=m.get("known", []), counter=m.get("counter", ""), log=_log_rows(map_id))
    elif m.get("place") and m["place"] not in {p["id"] for p in logic.places_for(v)}:
        out["place"] = ""
    return out
