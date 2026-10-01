"""Запускается в отдельном процессе (DATA_DIR уже указывает на базу «как у вас на сервере»): новая версия портала поверх старой базы.

Печатает JSON-отчёт. Сравнивает то, что отдаёт новая версия, с тем, что отдавала старая (снимки в legacy_v1.json), и проверяет,
что запись тоже работает.
"""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
report = {"viewers": {}, "writes": {}, "files": {}}


def norm(x):
    return json.loads(json.dumps(x, ensure_ascii=False, sort_keys=True))


def client(token=None):
    c = TestClient(app, raise_server_exceptions=False)
    if token:
        c.cookies.set("session", token)
    return c


with TestClient(app, raise_server_exceptions=False) as boot:                         # настоящий запуск: миграции, начальные данные
    from app import db
    report["user_version"] = [db.schema_version(), db.LATEST]
    report["anonymous"] = client().get("/api/state").status_code
    clients = {who: client(token) for who, token in meta["cookies"].items()}
    for who, c in clients.items():
        r = c.get("/api/state")
        entry = {"status": r.status_code}
        if r.status_code == 200:
            new, old = norm(r.json()), norm(meta["state"][who])
            entry["missing"] = [k for k in old if k not in new]
            entry["changed"] = [k for k in old if k in new and new[k] != old[k] and k != "version"]
            entry["extra"] = sorted(k for k in new if k not in old)
        report["viewers"][who] = entry
    rig = clients["rig"]
    for name, info in meta["files"].items():
        headers = {"Accept-Encoding": "identity"} if name == "handout" else {}
        r = rig.get(info["url"], headers=headers)
        report["files"][name] = [r.status_code, len(r.content), info["bytes"]]
    # запись поверх старой базы: новые возможности работают с данными старой версии
    ids = meta["ids"]
    w = report["writes"]
    gate, gm = clients["gate"], clients["gm"]
    r = gate.post("/api/entries", json={"type": "meet", "title": "Новая запись после обновления", "from": "2075-08-20", "to": "2075-08-20", "tod": "вечер",
                                        "who": ["rig"], "open": False, "where": "", "cond": "", "goal": "Привет [[Фиксер Ли]]", "vis": "стол", "place": "", "char": "gate"})
    w["new_entry"] = r.status_code
    r = rig.post(f"/api/entries/{ids['e1']}/roll", json={"char": "rig", "dice": 5, "label": "Скрытность"})
    w["dice_in_old_entry"] = r.status_code
    r = rig.post(f"/api/entries/{ids['e1']}/messages", json={"char": "rig", "text": "Сообщение после обновления"})
    w["message_in_old_entry"] = r.status_code
    w["answer_old_invite"] = gate.post(f"/api/entries/{ids['e4']}/act", json={"act": "ans", "char": "gate", "v": "да"}).status_code   # приглашение, ждавшее ответа ещё в старой версии
    r = gm.post("/api/gm/items/money", json={"char": "rig", "delta": 1500, "note": "Награда"})
    w["money"] = r.status_code
    r = gm.post("/api/gm/items/past", json={"title": "Хроника после обновления", "from": "2075-08-01", "to": "2075-08-01", "note": "n"})
    w["past"] = r.status_code
    r = gm.post(f"/api/gm/handouts/{ids['handout']}/file", content=b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n", headers={"X-File-Name": "x"})
    w["replace_handout_with_pdf"] = r.status_code
    r = rig.get("/api/me/diary", params={"format": "pdf", "char": "rig"})
    w["diary_pdf"] = [r.status_code, r.content[:5].decode("latin-1")]
    r = gm.post(f"/api/gm/items/dossier/{ids['card']}/delete")
    w["delete_card_to_trash"] = r.status_code
    trash = gm.get("/api/gm/trash").json()["items"]
    w["trash_has_card"] = any(t["kind"] == "dossier" for t in trash)
    r = gm.post(f"/api/gm/trash/{[t['id'] for t in trash if t['kind'] == 'dossier'][0]}/restore") if trash else None
    w["restore_card"] = r.status_code if r is not None else None
    after = rig.get("/api/state").json()
    w["old_entry_chat"] = [len(e["chat"]) for e in after["entries"] if e["id"] == ids["e1"]]
    w["portrait_after_restore"] = any(c.get("img") for c in after["dossier"])
print(json.dumps(report, ensure_ascii=False))
