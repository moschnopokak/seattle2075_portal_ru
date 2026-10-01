"""Строит «базу как на вашем сервере»: настоящим кодом ПЕРВОЙ версии портала (коммит f9785e9) и с живыми данными.

Нужен один раз, чтобы получить tests/fixtures/legacy_v1.sql и снимки состояния; в тестах он не запускается.
Запуск (из корня репозитория):
    git archive f9785e9 | tar -x -C /tmp/orig
    DATA_DIR=/tmp/origdata CONFIG_DIR=/tmp/origcfg PYTHONPATH=/tmp/orig DEV_LOGIN=1 COOKIE_SECURE=0 python tests/tools/make_legacy_db.py /tmp/legacy_out
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app            # это код первой версии: PYTHONPATH указывает на распакованный коммит f9785e9

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
GM, MAX, GATE, RIG, HAG, ELI = 1, 101, 102, 103, 104, 105


def login(tg):
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/auth/dev", json={"tg_id": tg})
    assert r.status_code == 200, r.text
    return c


def ok(r, what=""):
    assert r.status_code == 200, (what, r.status_code, r.text[:300])
    return r.json()


def entry(**kw):
    body = {"type": "meet", "title": "Тест", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер", "who": [], "open": False,
            "where": "", "cond": "", "goal": "", "vis": "стол", "place": ""}
    body.update(kw)
    return body


def make(client, **kw):
    data = ok(client.post("/api/entries", json=entry(**kw)), kw.get("title"))
    return next(e["id"] for e in data["state"]["entries"] if e["title"] == kw["title"])


def png():
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (300, 400), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


def main():
    with TestClient(app, raise_server_exceptions=False) as boot:
        assert boot.get("/healthz").status_code == 200
    gm, gate, rig, hag = login(GM), login(GATE), login(RIG), login(HAG)
    login(ELI)                                                                      # Илайджа тоже входит (строка в logins), но сам ничего не делает
    max_ = login(MAX)

    # --- записи игроков
    e1 = make(gate, char="gate", title="Встреча у моста", who=["rig"], where="Мост", cond="Без оружия", goal="Договориться об оплате")
    ok(rig.post(f"/api/entries/{e1}/act", json={"act": "ans", "char": "rig", "v": "да"}))
    ok(rig.post(f"/api/entries/{e1}/messages", json={"char": "rig", "text": "Приду с Хаганэ, если не против 👍"}))
    ok(gate.post(f"/api/entries/{e1}/messages", json={"char": "gate", "text": "Договорились.\nВстречаемся в восемь."}))
    ok(gate.post(f"/api/entries/{e1}/act", json={"act": "star", "char": "gate"}))
    e2 = make(gate, char="gate", title="Дело с отказом", who=["rig", "hagane"], **{"from": "2075-08-06", "to": "2075-08-07"})
    ok(rig.post(f"/api/entries/{e2}/act", json={"act": "ans", "char": "rig", "v": "нет"}))
    e3 = make(hag, char="hagane", title="Личное дело Хаганэ", who=["elijah"], vis="лично", goal="Никому не рассказывать")
    e4 = make(rig, char="rig", title="Открытая запись", who=["gate"], open=True, **{"from": "2075-08-10", "to": "2075-08-12"})
    ok(hag.post(f"/api/entries/{e4}/act", json={"act": "join", "char": "hagane"}))
    ok(rig.post(f"/api/entries/{e4}/messages", json={"char": "rig", "text": "Заходи"}))
    grow = make(rig, char="rig", title="Навык взлома", type="grow", who=["rig"], goal="Повысить Hacking на 1", effect="2075-08-10")
    ok(gm.post(f"/api/entries/{grow}/act", json={"act": "approve"}))
    grow2 = make(gate, char="gate", title="Развитие на проверке", type="grow", who=["gate"], goal="Новая киберруки", effect="2075-08-12")
    e5 = make(max_, char="alice", title="Покупки Элис", type="deal", who=["karu"], where="Любой магазин", cond="1000¥")
    e6 = make(gate, char="gate", title="Давняя встреча", who=["rig"], **{"from": "2075-07-22", "to": "2075-07-22"})
    ok(rig.post(f"/api/entries/{e6}/act", json={"act": "ans", "char": "rig", "v": "да"}))
    gm_entry = make(gm, char="gm", title="Задание от мастера", who=["rig", "gate"], goal="Общая цель")
    ok(gm.post(f"/api/entries/{e6}/act", json={"act": "outcome", "v": "done"}))
    deleted = make(gate, char="gate", title="Удалённая запись", who=["rig"])
    ok(gate.post(f"/api/entries/{deleted}/act", json={"act": "del", "char": "gate"}))

    # --- панель мастера
    ok(gm.post("/api/gm/items/windows", json={"name": "Арка 2", "gm": "Арка 2: Крысы", "from": "2075-11-01", "to": "2075-11-30"}))
    ok(gm.post("/api/gm/items/rhythm", json={"title": "Пересменка", "wd": [0, 3], "vis": "стол", "from": "2075-08-01", "to": "2075-12-31"}))
    ok(gm.post("/api/gm/items/rhythm", json={"title": "Привычка Рига", "mode": "monthly", "monthDay": 15, "who": "rig", "vis": "стол"}))
    ok(gm.post("/api/gm/items/clocks", json={"title": "Скрытый таймер", "note": "СЕКРЕТ: облава", "when": "2075-09-15"}))
    plan = ok(gm.post("/api/gm/items/plan", json={"title": "План налёта", "from": "2075-09-01", "to": "2075-09-02", "note": "СЕКРЕТ: детали",
                                                  "cover": {"title": "Общее событие", "note": "Город закрыт", "who": ["rig"]}}))
    plan_id = next(p["id"] for p in plan["state"]["plan"] if p["title"] == "План налёта")
    ok(gm.post("/api/gm/items/past", json={"title": "Хроника вручную", "from": "2075-07-15", "to": "2075-07-16", "note": "Публично", "gm_note": "СЕКРЕТ", "session": "Сессия 1"}))
    plan2 = ok(gm.post("/api/gm/items/plan", json={"title": "Сыгранный план", "from": "2075-07-20", "to": "2075-07-20", "note": "К переносу"}))
    ok(gm.post(f"/api/gm/plan/{next(p['id'] for p in plan2['state']['plan'] if p['title'] == 'Сыгранный план')}/played", json={}))
    place = ok(gm.post("/api/gm/items/places", json={"name": "Бар «Тузы»", "type": "business", "x": 4100, "y": 5200, "vis": "знают", "known": ["rig"], "note": "ВидноРигу", "gm_note": "СЕКРЕТ"}))
    place_id = next(p["id"] for p in place["state"]["places"] if p["name"] == "Бар «Тузы»")
    card = ok(gm.post("/api/gm/items/dossier", json={"name": "Фиксер Ли", "alias": "Ли", "type": "person", "role": "Достаёт железо", "stance": "contact", "org": "Кенран-кай",
                                                     "vis": "стол", "known": [], "met": ["rig"], "last_date": "2075-07-20", "last_place": place_id, "last_note": "Встретились в баре",
                                                     "facts": [{"id": "f1", "text": "Знает ход через канализацию", "vis": "стол", "known": [], "truth": "СЕКРЕТ", "date": "2075-07-20"}],
                                                     "gm_note": "СЕКРЕТ: двойной агент"}))
    card_id = next(c["id"] for c in card["state"]["dossier"] if c["name"] == "Фиксер Ли")
    ok(gm.post(f"/api/gm/dossier/{card_id}/portrait", content=png()))
    h = ok(gm.post("/api/gm/items/handouts", json={"title": "Письмо Танаки", "date": "2075-07-30", "vis": "знают", "known": ["rig"], "note": "Нашли в сейфе", "gm_note": "СЕКРЕТ", "place": place_id}))
    hid = next(x["id"] for x in h["state"]["handouts"] if x["title"] == "Письмо Танаки")
    ok(gm.post(f"/api/gm/handouts/{hid}/file", content="<!doctype html><html><body><h1>Письмо</h1><p>Привет, Рига</p></body></html>".encode(), headers={"X-File-Name": "%D0%BF.html"}))
    ok(gm.post("/api/gm/district/downtown", json={"text": "Центр города", "gm_text": "СЕКРЕТ: патрули"}))
    ok(gm.post("/api/gm/time", json={"date": "2075-08-02", "tod": "день"}))
    ok(gm.post("/api/gm/time", json={"quiet": "2075-08-08"}))

    # --- снимки состояния до обновления: то, с чем потом сравнивается новая версия
    snap = {"gm": ok(gm.get("/api/state")), "rig": ok(rig.get("/api/state")), "gate": ok(gate.get("/api/state")),
            "hag": ok(hag.get("/api/state")), "max": ok(max_.get("/api/state"))}
    token = lambda c: c.cookies["session"]
    cookies = {"gm": token(gm), "rig": token(rig), "gate": token(gate), "hag": token(hag), "max": token(max_)}
    files = {}
    for c in snap["rig"]["dossier"]:
        if c.get("img"):
            files["portrait_full"] = {"url": f"/portrait/{c['img']}/f.webp", "bytes": len(rig.get(f"/portrait/{c['img']}/f.webp").content)}
    for x in snap["rig"]["handouts"]:
        if x.get("file"):
            files["handout"] = {"url": f"/handout/{x['file']}/view", "bytes": len(rig.get(f"/handout/{x['file']}/view", headers={"Accept-Encoding": "identity"}).content)}
    ids = dict(e1=e1, e2=e2, e3=e3, e4=e4, e5=e5, e6=e6, grow=grow, grow2=grow2, gm_entry=gm_entry, plan=plan_id, place=place_id, card=card_id, handout=hid)

    from app import db
    db.conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    path = Path(os.environ["DATA_DIR"]) / "portal.db"
    src = sqlite3.connect(path)
    (OUT / "legacy_v1.sql").write_text("\n".join(src.iterdump()) + "\n", encoding="utf-8")
    counts = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    version = src.execute("PRAGMA user_version").fetchone()[0]
    src.close()
    (OUT / "legacy_v1.json").write_text(json.dumps({"counts": counts, "user_version": version, "ids": ids, "cookies": cookies, "files": files,
                                                    "secret_key": (Path(os.environ["DATA_DIR"]) / "secret.key").read_text().strip(), "state": snap},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("готово", counts, "user_version", version)


main()
