"""Начальная структура кампании из config/campaign.json.

Файл загружается один раз, при первом запуске. Дальше этапы, регулярные события,
скрытые таймеры, план мастера и хроника редактируются в панели мастера на сайте.

Команда
    python -m app.seed --structure
заново загружает из файла этапы, регулярные события, таймеры и план, стирая правки,
сделанные на сайте. Записи игроков, хроника и текущая дата не трогаются.
С --all перезаписываются ещё хроника и текущая дата. Обе команды спрашивают подтверждение,
ключ --yes его пропускает.
"""
import re
import uuid
import argparse
import json

from . import db
from .config import CONFIG_DIR

STRUCTURE = ("windows", "rhythm", "clocks")


def load_campaign():
    return json.loads((CONFIG_DIR / "campaign.json").read_text(encoding="utf-8"))


def seed(mode="auto"):
    data = load_campaign()
    with db.lock:
        first = db.meta_get("seeded") is None
        if mode == "auto" and not first:
            return False
        cal = data.get("calendar", {})
        db.meta_set("cal_start", cal.get("start", "2075-07-01"))
        db.meta_set("cal_end", cal.get("end", "2075-12-31"))
        for kind in STRUCTURE:
            db.set_items(kind, data.get(kind, []))
        if first or mode == "all":
            db.set_items("past", data.get("past", []))
        played = {p.get("plan_id") for p in db.items("past")}
        db.set_items("plan", [p for p in data.get("plan", []) if p["id"] not in played])
        if first or mode == "all":
            now = data.get("now", {})
            db.meta_set("now_date", now.get("date", cal.get("start", "2075-07-01")))
            db.meta_set("now_tod", now.get("tod", "вечер"))
            db.meta_set("quiet_until", data.get("quietUntil", ""))
        db.meta_set("seeded", "1")
        db.bump()
    return True


def ensure(kinds):
    """Один раз добавить разделы из campaign.json в уже работающий портал (места, описания районов, досье).
    Загруженный раздел помечается в базе, поэтому удалённое мастером потом не возвращается."""
    data = load_campaign()
    added = []
    with db.lock:
        for kind in kinds:
            flag = "seeded:" + kind
            if db.meta_get(flag):
                continue
            if not db.items(kind) and data.get(kind):
                db.set_items(kind, data[kind])
                added.append(kind)
            db.meta_set(flag, "1")
        if added:
            db.bump()
    return added


def migrate():
    """Разовые поправки данных в уже работающем портале. Каждая выполняется один раз."""
    done = []
    with db.lock:
        if not db.meta_get("migr:dossier-1"):
            cards, changed = db.items("dossier"), False
            out = []
            for c in cards:
                m = re.fullmatch(r"(\S+) «([^»]+)» (\S.*)", c.get("name", ""))
                if m and not c.get("alias"):
                    c["name"], c["alias"], changed = f"{m.group(1)} {m.group(3)}", m.group(2), True
                if c.get("name") == "Виништа / Эцуко" and not c.get("alias"):
                    c["name"], c["alias"], changed = "Виништа", "Эцуко", True
                untouched = (not c.get("facts") and not c.get("img") and c.get("vis") == "мастер"
                             and not c.get("role") and c.get("gm_note", "").startswith("Байбл, 9.2."))
                if c.get("name") == "Хельга Ранке, Томас Бёль" and untouched:
                    for name, extra in (("Хельга Ранке", "Работает в паре с Томасом Бёлем."),
                                        ("Томас Бёль", "Маг, читает ауры. Работает в паре с Хельгой Ранке.")):
                        out.append(dict(c, id="n" + uuid.uuid4().hex[:8], name=name, gm_note=c["gm_note"] + "\n" + extra))
                    changed = True
                    continue
                out.append(c)
            if changed:
                db.set_items("dossier", out)
                db.bump()
                done.append("досье: позывные вынесены в отдельное поле")
            db.meta_set("migr:dossier-1", "1")
    return done


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Загрузить структуру кампании из config/campaign.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--structure", action="store_true", help="этапы, регулярные события, таймеры, план, границы")
    group.add_argument("--all", action="store_true", help="плюс хроника и текущая дата (перезапись)")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    args = parser.parse_args()
    if not args.yes:
        print("Этапы, регулярные события, таймеры и план будут заново загружены из config/campaign.json.")
        print("Правки этих разделов, сделанные в панели мастера, пропадут." + (" Хроника и текущая дата тоже." if args.all else ""))
        if input("Продолжить? [y/N] ").strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено.")
            raise SystemExit(1)
    db.init()
    seed("all" if args.all else "structure")
    print("Готово.")
