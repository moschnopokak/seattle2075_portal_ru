"""Словарь интерфейса: в видимых текстах не должно быть жаргона и внутренних названий.

Портал читают игроки и мастер, а не разработчики. Слова из этого списка уже вызывали вопросы («Добавить проводку» у нуйенов никто не понял),
поэтому у каждого есть замена. Проверяются все строки, которые видит человек: тексты в static/js и static/index.html и сообщения,
которые сервер отдаёт на экран и в Telegram. Комментарии, документация и записи в журнале сервера не проверяются.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# корень слова (регистр не важен) -> чем заменить
BANNED = {
    "проводк": "«запись о деньгах», «доход или расход»",
    "откат": "«вернуть как было»",
    "напрос": "«попроситься»",
    "маск": "«что видят игроки», «общее событие»",
    "сервер": "«портал»",
    "токен": "«ключ входа» или без подробностей: «сообщите мастеру»",
    "элемент": "«запись»",
}
SETTING_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")                  # BOT_TOKEN, DEV_LOGIN, NOTIFY_DM: имена настроек для игроков бессмысленны

CYR = re.compile(r"[А-Яа-яЁё]")


def scan_js(src):
    """Все строки JS: в кавычках и в шаблонах (в том числе вложенных в ${...}). Комментарии и регулярные выражения пропускаются."""
    out, n = [], len(src)

    def template(i):
        """i указывает на символ после открывающей обратной кавычки; возвращает индекс после закрывающей."""
        buf = []
        while i < n:
            c = src[i]
            if c == "\\":
                buf.append(src[i + 1:i + 2]); i += 2; continue
            if c == "`":
                out.append("".join(buf)); return i + 1
            if c == "$" and src[i + 1:i + 2] == "{":
                out.append("".join(buf)); buf = []
                i = code(i + 2, braces=True)
                continue
            buf.append(c); i += 1
        return i

    def quoted(i, q):
        buf = []
        while i < n:
            c = src[i]
            if c == "\\":
                buf.append(src[i + 1:i + 2]); i += 2; continue
            if c == q:
                out.append("".join(buf)); return i + 1
            buf.append(c); i += 1
        return i

    def code(i, braces=False):
        depth, prev = 0, ""
        while i < n:
            c = src[i]
            if c in "'\"":
                i = quoted(i + 1, c); prev = "x"; continue
            if c == "`":
                i = template(i + 1); prev = "x"; continue
            if c == "/" and src[i + 1:i + 2] == "*":
                j = src.find("*/", i + 2); i = n if j < 0 else j + 2; continue
            if c == "/" and src[i + 1:i + 2] == "/":
                j = src.find("\n", i); i = n if j < 0 else j; continue
            if c == "/" and (prev == "" or prev in "(,=:[!&|?{};"):          # регулярное выражение: пропускаем до закрывающей косой черты
                j = i + 1
                while j < n and src[j] != "/" and src[j] != "\n":
                    j += 2 if src[j] == "\\" else 1
                i = j + 1; prev = "x"; continue
            if braces:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        return i + 1
                    depth -= 1
            if not c.isspace():
                prev = c
            i += 1
        return i

    code(0)
    return out


def js_texts(path):
    texts = []
    for chunk in scan_js(path.read_text(encoding="utf-8")):
        for part in re.split(r"<[^>]+>", chunk):
            if CYR.search(part):
                texts.append(part.strip())
    return texts


def py_texts(path):
    """Строки Python, которые доходят до человека: без docstring, записей в журнал сервера (log.info и подобные) и print() в консоли администратора."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("debug", "info", "warning", "error", "exception", "critical"):
            for sub in ast.walk(node):
                skip.add(id(sub))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":          # вывод в консоль администратора
            for sub in ast.walk(node):
                skip.add(id(sub))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip and CYR.search(node.value):
            out.append(node.value.strip())
    return out


def collect():
    items = []
    for p in sorted((ROOT / "static" / "js").glob("*.js")):
        items += [(f"static/js/{p.name}", t) for t in js_texts(p)]
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", (ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    items += [("static/index.html", t.strip()) for t in re.split(r"\s{2,}", html) if CYR.search(t)]
    for p in sorted((ROOT / "app").glob("*.py")):
        if p.name in ("preflight.py", "startup.py", "backup.py", "seed.py"):                 # служебное: запуск, копии, начальные данные
            continue
        items += [(f"app/{p.name}", t) for t in py_texts(p)]
    return items


TEXTS = collect()


def test_the_scan_really_sees_the_interface():
    files = {f for f, _ in TEXTS}
    assert {"static/js/sheet.js", "static/js/app.js", "app/logic.py", "app/auth.py"} <= files
    assert any("Записать доход или расход" in t for _, t in TEXTS)                      # замена слова «проводка» на месте
    assert len(TEXTS) > 1200


@pytest.mark.parametrize("stem", sorted(BANNED))
def test_no_jargon_in_visible_texts(stem):
    found = [(f, t[:90]) for f, t in TEXTS if stem in t.lower()]
    assert not found, f"слово «{stem}…» не для интерфейса, заменить на {BANNED[stem]}: {found[:6]}"


def test_no_setting_names_in_visible_texts():
    found = [(f, t[:90]) for f, t in TEXTS if SETTING_NAME.search(t)]
    assert not found, f"имена настроек в тексте для людей: {found[:6]}"


def test_money_screen_speaks_plainly(tmp_path):
    sheet = (ROOT / "static" / "js" / "sheet.js").read_text(encoding="utf-8")
    for phrase in ("Записать доход или расход", "Деньги пришли (доход)", "Деньги ушли (расход)", "Записей о деньгах пока нет.", "Репутации пока нет.", "Контактов пока нет."):
        assert phrase in sheet, phrase
