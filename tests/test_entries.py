"""Записи календаря: приглашения, ответы, звёзды, обсуждения, развитие."""
from helpers import create, entry, find, ok, remove


def test_invite_answer_star_chat_edit_delete(gm, gate, rig, hag):
    e = create(gate, char="gate", title="Встреча с Ригом", who=["rig"])
    eid = e["id"]
    assert e["status"] == "reply" and e["answers"] == {"rig": "ждёт"}
    assert rig.post(f"/api/entries/{eid}/act", json={"act": "ans", "v": "да", "char": "rig"}).status_code == 200
    assert find(rig.get("/api/state").json(), eid)["status"] == "ok"
    assert rig.post(f"/api/entries/{eid}/act", json={"act": "ans", "v": "да", "char": "rig"}).status_code == 400
    state = ok(gate.post(f"/api/entries/{eid}/act", json={"act": "star", "char": "gate"}))["state"]
    assert "gate" in find(state, eid)["stars"]
    # посторонний не пишет в обсуждение, участники и мастер пишут
    assert hag.post(f"/api/entries/{eid}/messages", json={"char": "hagane", "text": "привет"}).status_code == 403
    assert rig.post(f"/api/entries/{eid}/messages", json={"char": "rig", "text": "привет"}).status_code == 200
    assert gm.post(f"/api/entries/{eid}/messages", json={"text": "мастер тут"}).status_code == 200
    chat = find(gate.get("/api/state").json(), eid)["chat"]
    assert [m["a"] for m in chat] == ["rig", "gm"]
    # перенос даты автором сбрасывает подтверждение
    moved = entry(char="gate", title="Встреча с Ригом", who=["rig"], **{"from": "2075-08-06", "to": "2075-08-06"})
    state = ok(gate.post(f"/api/entries/{eid}/edit", json=moved))["state"]
    assert find(state, eid)["answers"]["rig"] == "ждёт"
    # участник чужую запись не правит
    assert rig.post(f"/api/entries/{eid}/edit", json=entry(char="rig", who=["gate"])).status_code == 403
    state = ok(gate.post(f"/api/entries/{eid}/act", json={"act": "del", "char": "gate"}))["state"]
    assert find(state, eid) is None


def test_second_character_of_same_player_is_auto_confirmed(gm, players):
    e = create(players["max"], char="alice", title="Сама с собой", who=["karu"])
    try:
        assert e["answers"]["karu"] == "да" and e["status"] == "ok"
    finally:
        remove(gm, e["id"])


def test_open_entry_join_kick(gm, gate, hag):
    e = create(gate, char="gate", title="Нужен кто-то", who=["gate"], open=True)
    eid = e["id"]
    try:
        state = ok(hag.post(f"/api/entries/{eid}/act", json={"act": "join", "char": "hagane"}))["state"]
        assert "hagane" in find(state, eid)["who"]
        assert hag.post(f"/api/entries/{eid}/act", json={"act": "join", "char": "hagane"}).status_code == 400
        state = ok(gate.post(f"/api/entries/{eid}/act", json={"act": "kick", "v": "hagane", "char": "gate"}))["state"]
        assert "hagane" not in find(state, eid)["who"]
        # автора убрать нельзя
        assert gate.post(f"/api/entries/{eid}/act", json={"act": "kick", "v": "gate", "char": "gate"}).status_code == 400
    finally:
        remove(gm, eid)


def test_star_moves_between_entries(gm, gate):
    a = create(gate, char="gate", title="Дело А", who=["gate"])
    b = create(gate, char="gate", title="Дело Б", who=["gate"])
    try:
        ok(gate.post(f"/api/entries/{a['id']}/act", json={"act": "star", "char": "gate"}))
        state = ok(gate.post(f"/api/entries/{b['id']}/act", json={"act": "star", "char": "gate"}))["state"]
        assert find(state, a["id"])["stars"] == [] and find(state, b["id"])["stars"] == ["gate"]
    finally:
        remove(gm, a["id"])
        remove(gm, b["id"])


def test_growth_needs_gm_approval(gm, rig):
    body = entry(type="grow", char="rig", title="Навык", who=["rig"], goal="Учусь", effect="2075-08-05")
    data = ok(rig.post("/api/entries", json=body))
    g = next(e for e in data["state"]["entries"] if e["title"] == "Навык")
    try:
        assert g["status"] == "gm"
        r = rig.post(f"/api/entries/{g['id']}/act", json={"act": "approve", "char": "rig"})
        assert r.status_code == 403 and "мастер" in r.text
        state = ok(gm.post(f"/api/entries/{g['id']}/act", json={"act": "approve"}))["state"]
        assert find(state, g["id"])["status"] == "ok"
        assert gm.post(f"/api/entries/{g['id']}/act", json={"act": "approve"}).status_code == 400  # уже рассмотрена
    finally:
        remove(gm, g["id"])


def test_outcome_only_for_finished_entries(gm, gate):
    e = create(gate, char="gate", title="Прошлое", who=["gate"], **{"from": "2075-07-10", "to": "2075-07-10"})
    try:
        state = ok(gm.post(f"/api/entries/{e['id']}/act", json={"act": "outcome", "v": "done"}))["state"]
        assert find(state, e["id"])["status"] == "done"
        assert gate.post(f"/api/entries/{e['id']}/act", json={"act": "del", "char": "gate"}).status_code == 403  # закрытую не удалить
    finally:
        remove(gm, e["id"])


def test_talk_can_be_closed(gm, gate, rig):
    e = create(gate, char="gate", title="Обсуждение", who=["rig"])
    try:
        ok(gate.post(f"/api/entries/{e['id']}/act", json={"act": "talk", "char": "gate"}))
        r = rig.post(f"/api/entries/{e['id']}/messages", json={"char": "rig", "text": "поздно"})
        assert r.status_code == 400
        assert rig.post(f"/api/entries/{e['id']}/act", json={"act": "talk", "char": "rig"}).status_code == 403
    finally:
        remove(gm, e["id"])


def test_validation_errors(gm, gate):
    bad = [
        entry(char="gate", title="", who=["gate"]),
        entry(char="gate", who=["gate"], **{"from": "2075-08-05", "to": "2075-08-01"}),
        entry(char="gate", who=["gate"], **{"from": "2074-01-01", "to": "2074-01-01"}),
        entry(char="gate", who=["gate"], **{"from": "2075-02-30", "to": "2075-02-30"}),
        entry(char="gate", who=["gate"], tod="полночь"),
        entry(char="gate", who=["gate"], place="нет-такого"),
        entry(type="zzz", char="gate", who=["gate"]),
        entry(type="grow", char="gate", who=["gate"]),   # нет цели
    ]
    for body in bad:
        r = gate.post("/api/entries", json=body)
        assert r.status_code == 400, (body, r.status_code, r.text[:100])
    # автор-игрок всегда входит в участники, а у записи мастера без участников и без «+» смысла нет
    assert gm.post("/api/entries", json=entry(who=[], open=False)).status_code == 400


def test_entry_text_is_cleaned(gm, gate):
    data = ok(gate.post("/api/entries", json=entry(char="gate", title="  Заг\x00оловок\nдва  ", who=["gate"], goal="a\r\nb\x07")))
    created = next(x for x in data["state"]["entries"] if x["title"].startswith("Заг"))
    try:
        assert created["title"] == "Заголовок два"
        assert created["goal"] == "a\nb"
    finally:
        remove(gm, created["id"])
