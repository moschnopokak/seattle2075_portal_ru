"""Мелкие помощники для тестов."""
import io


def entry(**kw):
    """Тело запроса на создание записи с разумными значениями по умолчанию."""
    body = {"type": "meet", "title": "Тест", "from": "2075-08-05", "to": "2075-08-05", "tod": "вечер",
            "who": [], "open": False, "where": "", "cond": "", "goal": "", "vis": "стол", "place": ""}
    body.update(kw)
    return body


def ok(response, what=""):
    assert response.status_code == 200, (what, response.status_code, response.text[:300])
    return response.json()


def find(state, entry_id):
    return next((e for e in state["entries"] if e["id"] == entry_id), None)


def create(client, **kw):
    """Создаёт запись и возвращает её из ответа."""
    data = ok(client.post("/api/entries", json=entry(**kw)), "create_entry")
    return next(e for e in data["state"]["entries"] if e["title"] == kw.get("title", "Тест"))


def remove(client, entry_id, char=None):
    client.post(f"/api/entries/{entry_id}/act", json={"act": "del", "char": char})


def walk(obj, path=""):
    """Все пары (путь, значение) во вложенном JSON."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
            yield f"{path}.{k}", v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def secrets_in(state):
    """Все строки со словом «СЕКРЕТ» (маркер вымышленных секретов мастера) во вложенном JSON: список (путь, текст)."""
    found = []
    for path, v in walk(state):
        if isinstance(v, str) and "СЕКРЕТ" in v:
            found.append((path, v))
    return found


def png(w=300, h=400, color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()
