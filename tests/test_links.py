"""Ссылки [[Имя]]: в сообщениях бота они становятся именем (Python и JS работают одинаково), в обсуждении не мешают уведомлениям."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import db, notify, outbox
from conftest import GATE
from helpers import create, ok, remove

CORPUS = [
    "Встреча с [[Ёжик Мак-Грегор]] у [[Бар «Мост»|моста]].", "[[А]][[Б]]", "[[]]", "[[ ]]", "[Имя]", "[[Имя]", "[[Имя\nс переносом]]",
    "[[[[вложенная]]]]x", "[[" + "я" * 61 + "]]", "[[" + "я" * 60 + "]]", "[[Имя|]]", "[[Имя| ]]", "[[ Имя | подпись ]]", "обычный текст", "",
]


def test_strip_links_examples():
    assert notify.strip_links("К [[Бар «Мост»]] и [[Ёжик|Ёжу]]!") == "К Бар «Мост» и Ёжу!"
    assert notify.strip_links("[[Имя| ]]") == "Имя" and notify.strip_links("[[ Имя | подпись ]]") == "подпись"
    assert notify.strip_links("[[Имя|]]") == "[[Имя|]]"                          # пустая подпись: это не ссылка, текст остаётся как есть
    assert notify.strip_links("[[Имя]") == "[[Имя]" and notify.strip_links("[Имя]") == "[Имя]"


@pytest.mark.skipif(not shutil.which("node"), reason="нужен Node.js")
def test_python_and_js_strip_links_agree():
    script = ("const l=require('./static/js/links.js');const c=JSON.parse(process.argv[1]);"
              "process.stdout.write(JSON.stringify(c.map(s=>l.stripLinks(s))))")
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run(["node", "-e", script, json.dumps(CORPUS)], cwd=root, capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(out.stdout) == [notify.strip_links(s) for s in CORPUS]


@pytest.fixture
def telegram_on(monkeypatch):
    monkeypatch.setattr(notify, "BOT_TOKEN", "123:ABC")
    monkeypatch.setattr(notify, "NOTIFY_DM", True)


def test_chat_preview_in_the_bot_shows_names_not_brackets(telegram_on, gate, rig, gm):
    e = create(gate, char="gate", title="Дело со ссылкой", who=["rig"])
    try:
        db.conn().execute("DELETE FROM outbox")
        ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "Спросим [[Ёжик Мак-Грегор|Ёжа]] про [[Бар «Мост»]]"}))
        (row,) = [r for r in outbox.pending(GATE) if r["kind"] == "chat"]
        assert json.loads(row["meta"])["last"] == "Риг: Спросим Ёжа про Бар «Мост»"
    finally:
        remove(gm, e["id"])
        db.conn().execute("DELETE FROM outbox")


def test_the_text_itself_is_stored_unchanged(gate, rig, gm):
    e = create(gate, char="gate", title="Дело с хранением", who=["rig"])
    try:
        text = "Нужна [[Карточка]] и [[Ещё|другая]]"
        data = ok(rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": text}))
        mine = next(x for x in data["state"]["entries"] if x["id"] == e["id"])
        assert mine["chat"][-1]["t"] == text                                    # сервер ссылки не трогает: разбирает их страница
    finally:
        remove(gm, e["id"])
