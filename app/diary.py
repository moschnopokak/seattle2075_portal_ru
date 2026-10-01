"""«Мой дневник»: выгрузка всего, что знает и пережил персонаж, в Markdown или PDF.

Дневник собирается из того же состояния, которое портал отдаёт этому игроку (logic.state_for для зрителя с одним персонажем),
поэтому в него не может попасть то, чего игрок не видит: заметки мастера, скрытые карточки, чужие личные записи и данные чужих
персонажей. Из состояния строится одна структура документа, из неё получаются и Markdown, и PDF.
"""
import io
import re
from datetime import datetime
from pathlib import Path

from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from . import logic, notify, outbox

PARTS = ("chron", "entries", "chat", "dossier", "handouts", "sheet")
DEFAULT_PARTS = ("chron", "entries", "dossier", "handouts", "sheet")
PART_NAMES = {"chron": "Хроника", "entries": "Записи", "chat": "Обсуждения записей", "dossier": "Досье", "handouts": "Раздатки", "sheet": "Лист персонажа"}
FONT_DIR = Path(__file__).parent / "fonts"
FONT_REGULAR, FONT_BOLD = FONT_DIR / "DejaVuSerif.ttf", FONT_DIR / "DejaVuSerif-Bold.ttf"

TYPES = {"meet": "Встреча", "grow": "Развитие", "deal": "Дело", "vow": "Обещание"}
STATUS = {"gm": "на проверке у мастера", "reply": "ждёт ответа участников", "resched": "нужна другая дата", "ok": "подтверждено",
          "done": "состоялось", "failed": "сорвано", "rejected": "отклонено мастером"}
ANSWER = {"да": "участие подтверждено", "нет": "отказ, нужна другая дата", "ждёт": "ответа пока нет", "сам": "по открытому приглашению"}
STANCE = {"unknown": "Неясно", "contact": "Контакт", "ally": "Союзник", "neutral": "Нейтрален", "hostile": "Враг"}
DTYPE = {"person": "Человек", "org": "Организация"}
FACTION_KIND = {"corp": "Корпорация", "gang": "Банда", "gov": "Власть", "org": "Организация", "other": "Другое"}
HANDOUT_KIND = {"html": "страница", "image": "картинка", "pdf": "PDF", "audio": "аудио"}
STANDING = {-5: "Объявлена охота", -4: "Враг", -3: "Неприязнь", -2: "Недоверие", -1: "Настороженность", 0: "Нейтрально",
            1: "Знакомы", 2: "Доверие", 3: "Уважение", 4: "Друг", 5: "Свой"}
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DiaryError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def parse_parts(value):
    """Список частей из запроса («chron,entries,…»). Пусто: всё по умолчанию. Незнакомое название: ошибка."""
    wanted = [p.strip() for p in str(value or "").split(",") if p.strip()]
    if not wanted:
        return list(DEFAULT_PARTS)
    unknown = [p for p in wanted if p not in PARTS]
    if unknown:
        raise DiaryError("Неизвестная часть дневника: " + ", ".join(unknown[:3]))
    return [p for p in PARTS if p in wanted]


def character_view(v, char):
    """Как портал выглядит для этого персонажа. Игрок выбирает только своего, мастер любого (проверить, что увидит игрок)."""
    chars = logic.char_map()
    if v.gm:
        if char not in chars:
            raise DiaryError("Выберите персонажа.")
    else:
        char = char or (v.chars[0] if v.chars else "")
        if char not in v.chars:
            raise DiaryError("Это не ваш персонаж.", 403)
    return char, logic.Viewer("player", {"name": v.name, "chars": [char]}, v.tg_id, v.username)


# ---------- структура документа ----------
# раздел: {"title", "blocks": [("p", текст) | ("h3", текст) | ("item", заголовок, [строки])]}

def _span(a, b):
    return logic.ffull(a) if not b or a == b else f"{logic.ffull(a)} – {logic.ffull(b)}"


def _names(ids, names):
    return ", ".join(names.get(c, c) for c in ids)


def _when(ts_ms, zone):
    return datetime.fromtimestamp(ts_ms / 1000, zone).strftime("%d.%m.%Y %H:%M")


def build(v, char, parts):
    char, vv = character_view(v, char)
    state = logic.state_for(vv)
    names = {c["id"]: c["name"] for c in state["characters"]}
    names["gm"] = "Мастер"
    me = names.get(char, char)
    zone = outbox.zone(outbox.prefs(v.tg_id)["tz"])
    places = {p["id"]: p["name"] for p in state["places"]}
    factions = {f["id"]: f for f in state["factions"]}
    sections = []

    if "chron" in parts:
        past = sorted(state["past"], key=lambda p: (p["from"], p.get("to", "")))
        blocks = []
        for p in past:
            lines = ([f"Сессия: {p['session']}"] if p.get("session") else []) + ([p["note"]] if p.get("note") else [])
            blocks.append(("item", f"{_span(p['from'], p.get('to'))}. {p['title']}", lines))
        sections.append({"title": PART_NAMES["chron"], "blocks": blocks or [("p", "Пока ничего.")]})

    if "entries" in parts or "chat" in parts:
        mine = sorted((e for e in state["entries"] if char in e["who"] or e["author"] == char), key=lambda e: (e["from"], e.get("created", 0)))
        if "entries" in parts:
            blocks = []
            for e in mine:
                lines = [f"Тип: {TYPES.get(e['type'], e['type'])}. Статус: {STATUS.get(e['status'], e['status'])}"]
                lines.append("Участники: " + ", ".join(f"{names.get(c, c)}" + (f" ({ANSWER[e['answers'][c]]})" if e.get("answers", {}).get(c) in ANSWER else "")
                                                       for c in e["who"]) + (", место для желающих" if e.get("open") else ""))
                for label, key in (("Где", "where"), ("Условие", "cond"), ("Цель", "goal")):
                    if e.get(key):
                        lines.append(f"{label}: {e[key]}")
                if e.get("place") in places:
                    lines.append(f"Место на карте: {places[e['place']]}")
                if e["type"] == "grow" and e.get("effect"):
                    lines.append(f"Действует с: {logic.ffull(e['effect'])}")
                blocks.append(("item", f"{_span(e['from'], e.get('to'))}{', ' + e['tod'] if e.get('tod') else ''}. {e['title']}", lines))
            sections.append({"title": PART_NAMES["entries"], "blocks": blocks or [("p", "Пока ничего.")]})
        if "chat" in parts:
            blocks = []
            for e in mine:
                if e.get("chat"):
                    blocks.append(("item", f"{e['title']} ({_span(e['from'], e.get('to'))})",
                                   [f"{names.get(m['a'], m['a'])}, {_when(m['ts'], zone)}: {m['t']}" for m in e["chat"]]))
            sections.append({"title": PART_NAMES["chat"], "blocks": blocks or [("p", "Обсуждений пока нет.")]})

    if "dossier" in parts:
        blocks = []
        for c in sorted(state["dossier"], key=lambda c: c["name"].lower()):
            lines = []
            kind = DTYPE.get(c.get("type"), "")
            if c.get("role"):
                lines.append(c["role"])
            lines.append(f"{kind + '. ' if kind else ''}Отношение: {STANCE.get(c.get('stance'), STANCE['unknown'])}")
            if c.get("org"):
                lines.append(f"Организация: {c['org']}")
            if c.get("met"):
                lines.append("Лично знакомы: " + _names(c["met"], names))
            seen = ", ".join(x for x in (logic.ffull(c["last_date"]) if c.get("last_date") else "", places.get(c.get("last_place"), ""), c.get("last_note", "")) if x)
            if seen:
                lines.append("Последняя встреча: " + seen)
            lines += [("Известно" + (f" ({logic.ffull(f['date'])})" if f.get("date") else "") + f": {f['text']}") for f in c.get("facts", [])]
            blocks.append(("item", c["name"] + (f" («{c['alias']}»)" if c.get("alias") else ""), lines))
        sections.append({"title": PART_NAMES["dossier"], "blocks": blocks or [("p", "Пока ничего.")]})

    if "handouts" in parts:
        blocks = []
        for h in sorted(state["handouts"], key=lambda h: (h["date"], h.get("uploaded", 0))):
            lines = [f"Вид: {HANDOUT_KIND.get(h.get('kind', 'html'), 'страница')}"]
            if h.get("place") in places:
                lines.append(f"Где получена: {places[h['place']]}")
            if h.get("note"):
                lines.append(h["note"])
            blocks.append(("item", f"{logic.ffull(h['date'])}. {h['title']}", lines))
        sections.append({"title": PART_NAMES["handouts"], "blocks": blocks or [("p", "Пока ничего.")]})

    if "sheet" in parts:
        money = [m for m in state["money"] if m["char"] == char]
        balance = sum(m["delta"] for m in money)
        blocks = [("h3", "Нуйены"), ("p", f"Баланс: {_nuyen(balance, plain=True)}")]
        if money:
            blocks.append(("item", "Проводки", [f"{logic.ffull(m['date'])}: {_nuyen(m['delta'])}" + (f", {m['note']}" if m.get("note") else "")
                                                for m in sorted(money, key=lambda m: m["date"])]))
        blocks.append(("h3", "Репутация"))
        standing = [s for s in state["standing"] if s["char"] == char and s["faction"] in factions]
        if standing:
            for s in standing:
                f = factions[s["faction"]]
                blocks.append(("item", f"{f['name']} ({FACTION_KIND.get(f.get('kind'), 'Другое')}): {_signed(s['value'])}, {STANDING.get(s['value'], '')}",
                               [x for x in (s.get("note"), f.get("note")) if x]))
        else:
            blocks.append(("p", "Пока ничего."))
        blocks.append(("h3", "Контакты"))
        contacts = [c for c in state["contacts"] if c["char"] == char]
        if contacts:
            for c in contacts:
                lines = [f"Связи {c['connection']}, лояльность {c['loyalty']}"] + [x for x in (c.get("services"), c.get("note")) if x]
                blocks.append(("item", c["name"], lines))
        else:
            blocks.append(("p", "Пока ничего."))
        sections.append({"title": PART_NAMES["sheet"], "blocks": blocks})

    today, tod = state["now"]["date"], state["now"]["tod"]
    return {"title": f"Дневник: {me}", "character": me, "char": char, "date": today, "tod": tod, "parts": list(parts),
            "subtitle": f"Сиэтл, 2075. Состояние на {logic.ffull(today)}, {tod}. Игрок: {v.name if not v.gm else 'предпросмотр мастера'}.",
            "sections": sections}


def _signed(n):
    return ("+" if n > 0 else "−" if n < 0 else "") + str(abs(n))


def _nuyen(n, plain=False):
    text = f"{abs(n):,}".replace(",", " ") + " ¥"
    return ("−" if n < 0 else "" if plain else "+") + text


# ---------- Markdown ----------

def _md_line(text):
    return CTRL.sub("", str(text)).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\n    ")


def to_markdown(doc):
    out = ["---", "tags: [дневник]", f"персонаж: {doc['character']}", f"игровая_дата: {doc['date']}", "---", "", f"# {doc['title']}", "", doc["subtitle"], ""]
    for sec in doc["sections"]:
        out += [f"## {sec['title']}", ""]
        for block in sec["blocks"]:
            if block[0] == "h3":
                out += [f"### {block[1]}", ""]
            elif block[0] == "p":
                out += [_md_line(block[1]), ""]
            else:
                out.append(f"- **{_md_line(block[1])}**")
                out += [f"  - {_md_line(line)}" for line in block[2]]
        out.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n"


# ---------- PDF ----------

_GLYPHS = None


def _supported():
    global _GLYPHS
    if _GLYPHS is None:
        font = TTFont(str(FONT_REGULAR), lazy=True)
        _GLYPHS = set(font.getBestCmap())
        font.close()
    return _GLYPHS


def _printable(text):
    """Текст для PDF: без служебных знаков и ссылок [[…]], знаки, которых нет в шрифте, заменяются на «?»."""
    text = notify.strip_links(CTRL.sub("", str(text)).replace("\r\n", "\n").replace("\r", "\n"))
    ok = _supported()
    return "".join(ch if (ch in "\n\t" or ord(ch) in ok) else "?" for ch in text).replace("\t", " ")


class _Pdf(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("serif", size=8)
        self.cell(0, 6, f"Сиэтл 2075 · {self.page_no()}", align="C")


def to_pdf(doc):
    pdf = _Pdf(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("serif", "", str(FONT_REGULAR))
    pdf.add_font("serif", "B", str(FONT_BOLD))
    pdf.set_title(_printable(doc["title"]))
    pdf.set_author("Портал «Сиэтл 2075»")
    pdf.set_creator("Портал «Сиэтл 2075»")
    pdf.add_page()

    def para(text, size=10.5, style="", height=5.6, indent=0.0, space=1.0):
        pdf.set_font("serif", style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(pdf.w - pdf.r_margin - pdf.get_x(), height, _printable(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(space)

    para(doc["title"], 20, "B", 9, space=2)
    para(doc["subtitle"], 10, "", 5.2, space=4)
    for sec in doc["sections"]:
        pdf.ln(2)
        para(sec["title"], 14, "B", 7, space=1.5)
        for block in sec["blocks"]:
            if block[0] == "h3":
                para(block[1], 11.5, "B", 6, space=0.5)
            elif block[0] == "p":
                para(block[1])
            else:
                if pdf.get_y() > pdf.h - 40:
                    pdf.add_page()
                para(block[1], 10.5, "B", 5.6, space=0.4)
                for line in block[2]:
                    para("– " + line, 10, "", 5.2, indent=4, space=0.2)
                pdf.ln(1.5)
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def filename(doc, ext):
    """Имя файла: «Дневник-Риг-2075-08-05.md». Всё лишнее из имени персонажа убрано."""
    name = re.sub(r"[^\w\-]+", "-", doc["character"], flags=re.UNICODE).strip("-") or "персонаж"
    return f"Дневник-{name}-{doc['date']}.{ext}"
