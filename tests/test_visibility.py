"""Главная гарантия портала: секреты мастера не доходят до игроков."""
import pytest

from helpers import secrets_in, walk

OWNERS = {"max": {"alice", "karu"}, "gate": {"gate"}, "rig": {"rig"}, "hag": {"hagane"}, "eli": {"elijah"}}
GM_ONLY_KEYS = {"gm_note", "gm_text", "truth", "plan_id", "gm"}


def test_fixture_really_contains_secrets(gm):
    """Страховка от пустого теста: у мастера секретов много и они разных видов."""
    found = secrets_in(gm.get("/api/state").json())
    assert len(found) >= 15, found


@pytest.mark.parametrize("who", list(OWNERS))
def test_no_secret_text_reaches_player(gm, players, who):
    state = players[who].get("/api/state").json()
    assert secrets_in(state) == []


@pytest.mark.parametrize("who", list(OWNERS))
def test_no_gm_only_keys_reach_player(players, who):
    state = players[who].get("/api/state").json()
    keys = {path for path, _ in walk(state) if path.rsplit(".", 1)[-1] in GM_ONLY_KEYS and path != ".me.gm"}
    assert not keys, sorted(keys)
    assert state["plan"] == [] and state["clocks"] == []
    assert state["handout_usage"] is None and state["portraits"] is None


def test_hidden_items_absent_for_players(gm, players):
    g = gm.get("/api/state").json()
    hidden_cards = {c["name"] for c in g["dossier"] if c["vis"] == "мастер"}
    hidden_places = {p["name"] for p in g["places"] if p["vis"] == "мастер"}
    assert hidden_cards and hidden_places
    for name, c in players.items():
        s = c.get("/api/state").json()
        assert not hidden_cards & {c_["name"] for c_ in s["dossier"]}, name
        assert not hidden_places & {p["name"] for p in s["places"]}, name
        assert all(r["vis"] != "мастер" for r in s["rhythm"])


def test_player_payloads_contain_only_whitelisted_fields(players):
    for name, c in players.items():
        s = c.get("/api/state").json()
        for card in s["dossier"]:
            assert "known" not in card and "vis" not in card
            for f in card["facts"]:
                assert set(f) <= {"id", "text", "date"}, f
        for p in s["places"]:
            assert set(p) <= {"id", "name", "type", "x", "y", "note"}, p
        assert all(set(d) <= {"id", "text"} for d in s["dnotes"])
        assert all(set(p) <= {"id", "from", "to", "title", "note", "session"} for p in s["past"])
        assert all(set(w) <= {"id", "from", "to", "name", "inter"} for w in s["windows"])


def test_future_stages_hidden(players):
    for c in players.values():
        s = c.get("/api/state").json()
        assert all(w["from"] <= s["now"]["date"] for w in s["windows"])
        assert "Арка 1" in {w["name"] for w in s["windows"]}


def test_known_only_items_follow_characters(gm, players):
    """«Только знающие»: карточки, места и сведения видят только нужные персонажи."""
    g = gm.get("/api/state").json()
    for name, c in players.items():
        s = c.get("/api/state").json()
        cards = {x["id"] for x in s["dossier"]}
        places = {x["id"] for x in s["places"]}
        mine = OWNERS[name]
        assert ("n2" in cards) == ("gate" in mine), name            # карточка для Гейта
        assert ("m2" in places) == ("rig" in mine), name            # место для Рига
        facts = {f["id"] for card in s["dossier"] for f in card["facts"]}
        assert ("f2" in facts) == ("rig" in mine), name             # сведение для Рига
        assert "f3" not in facts                                    # сведение только мастера
    assert {c["id"] for c in g["dossier"]} == {"n1", "n2", "n3"}


def test_last_place_hidden_when_place_unknown(players):
    """Карточка n2 ссылается на скрытое место m3: игроку эта ссылка не отдаётся."""
    s = players["gate"].get("/api/state").json()
    card = next(c for c in s["dossier"] if c["id"] == "n2")
    assert "last_place" not in card


def test_cover_block_shows_mask_only(gm, players):
    rig_state = players["rig"].get("/api/state").json()
    titles = {b["title"] for b in rig_state["blocks"]}
    assert "Общий выходной" in titles
    assert "Общий выходной" not in {b["title"] for b in players["hag"].get("/api/state").json()["blocks"]}
    assert all("СЕКРЕТ" not in str(b) for b in rig_state["blocks"])


def test_personal_entries_private(gm, players):
    from helpers import create, find, remove
    e = create(players["gate"], char="gate", title="Личное", who=["gate"], vis="лично")
    try:
        assert find(players["hag"].get("/api/state").json(), e["id"]) is None
        assert find(players["rig"].get("/api/state").json(), e["id"]) is None
        assert find(gm.get("/api/state").json(), e["id"]) is not None
        hag = players["hag"]
        assert hag.post(f"/api/entries/{e['id']}/act", json={"act": "star", "char": "hagane"}).status_code == 404
        assert hag.post(f"/api/entries/{e['id']}/messages", json={"char": "hagane", "text": "x"}).status_code == 404
        assert hag.post(f"/api/entries/{e['id']}/edit", json={"char": "hagane"}).status_code == 404
    finally:
        remove(gm, e["id"])


def test_public_static_files_have_no_gm_notes():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "static"
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".html", ".js", ".css") and "vendor" not in path.parts:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "СЕКРЕТ" not in text, path
