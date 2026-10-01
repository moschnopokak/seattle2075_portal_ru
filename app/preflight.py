"""Репетиция обновления и сверка баз. Ваша база при этом не меняется: репетиция работает с её КОПИЕЙ.

    python -m app.preflight --db ФАЙЛ.db            репетиция: копия базы проходит настоящий запуск этой версии портала,
                                                    потом проверяется, что всё цело и читается
    python -m app.preflight --compare СТАРАЯ НОВАЯ  убедиться, что в НОВОЙ базе есть всё, что было в СТАРОЙ

Репетиция проверяет: целостность базы; что миграция схемы проходит; что ни одна строка не пропала и не изменилась (допустимы
только счётчик версии данных, время последнего входа и добавленные строки); что мастер и каждый игрок получают своё состояние
без ошибок; что дневник каждого персонажа собирается; что картинки и раздатки, на которые ссылаются карточки, лежат в базе.
Код возврата: 0 всё хорошо, 1 есть проблемы.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

IGNORE_COLUMNS = {"logins": {"last_seen"}}          # меняются при каждом входе
IGNORE_META_KEYS = {"version"}                      # счётчик «данные изменились», растёт при запуске


class PreflightError(Exception):
    pass


def _hash(row):
    return hashlib.blake2b(json.dumps(row, ensure_ascii=False, default=lambda b: hashlib.sha256(bytes(b)).hexdigest()).encode(), digest_size=12).hexdigest()


def snapshot(path, columns=None):
    """Содержимое базы: по каждой таблице {ключ строки: хеш строки}. columns: какие столбцы брать (чтобы сравнивать со старой схемой)."""
    try:
        conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    except sqlite3.Error as ex:
        raise PreflightError(f"Файл {path} не открывается как база SQLite: {ex}") from None
    tables, cols_used = {}, {}
    for name in names:
        info = conn.execute(f"PRAGMA table_info({name})").fetchall()
        all_cols = [r["name"] for r in info]
        pk = [r["name"] for r in sorted(info, key=lambda r: r["pk"]) if r["pk"]] or ["rowid"]
        cols = [c for c in (columns or {}).get(name, all_cols) if c in all_cols]
        skip = IGNORE_COLUMNS.get(name, set())
        rows = {}
        select = ", ".join(["rowid AS _rowid"] + [f'"{c}"' for c in dict.fromkeys(cols + [c for c in pk if c != "rowid"])])
        for r in conn.execute(f'SELECT {select} FROM "{name}"'):
            key = json.dumps([r["_rowid"] if k == "rowid" else r[k] for k in pk], ensure_ascii=False)
            if name == "meta" and r["key"] in IGNORE_META_KEYS:
                continue
            rows[key] = _hash([r[c] for c in cols if c not in skip])
        tables[name], cols_used[name] = rows, cols
    conn.close()
    return {"integrity": integrity, "user_version": version, "tables": tables, "columns": cols_used,
            "size": Path(path).stat().st_size}


def compare(before, after):
    """Что пропало или изменилось: {'lost': {таблица: [ключи]}, 'changed': {...}}. Добавленное не считается проблемой."""
    lost, changed = {}, {}
    for name, rows in before["tables"].items():
        now = after["tables"].get(name)
        if now is None:
            lost[name] = ["вся таблица"]
            continue
        gone = [k for k in rows if k not in now]
        diff = [k for k, h in rows.items() if k in now and now[k] != h]
        if gone:
            lost[name] = gone
        if diff:
            changed[name] = diff
    return {"lost": lost, "changed": changed}


def _mb(n):
    return f"{n / 1048576:.1f}".replace(".", ",") + " МБ"


# ---------- проверки внутри копии: настоящий код портала на копии базы (отдельный процесс, DATA_DIR уже подменён) ----------

def child_checks():
    import logging
    from . import config, db, diary, handouts, logic, portraits, startup
    result = {"notes": [], "problems": [], "info": {}}
    result["notes"] = startup.prepare_data(logging.getLogger("preflight"))
    try:
        people = config.people()
    except Exception as ex:                                              # файла игроков нет или он с ошибкой
        result["problems"].append(f"список игроков не читается: {ex}")
        return result
    viewers = [("мастер", logic.Viewer("gm", people["gm"], 0, ""))]
    viewers += [(p["name"], logic.Viewer("player", p, 0, "")) for p in people["players"]]
    for label, v in viewers:
        try:
            json.dumps(logic.state_for(v), ensure_ascii=False)
        except Exception as ex:
            result["problems"].append(f"состояние для «{label}» не собирается: {type(ex).__name__}: {ex}")
    result["info"]["viewers"] = len(viewers)
    chars = [c["id"] for c in people["characters"]]
    built = 0
    gm = viewers[0][1]
    for char in chars:
        try:
            diary.to_markdown(diary.build(gm, char, list(diary.PARTS)))
            built += 1
        except Exception as ex:
            result["problems"].append(f"дневник персонажа «{char}» не собирается: {type(ex).__name__}: {ex}")
    result["info"]["diaries"] = built
    missing = []
    for card in db.items("dossier"):
        if card.get("img") and portraits.get(card["img"], "f") is None:
            missing.append(f"картинка карточки «{card.get('name')}»")
    for item in db.items("handouts"):
        if item.get("file") and handouts.get(item["file"]) is None:
            missing.append(f"файл раздатки «{item.get('title')}»")
    result["info"]["files_missing"] = missing
    for m in missing:
        result["problems"].append(f"{m} записана, а самого файла в базе нет")
    result["info"]["entries"] = len(db.entries())
    return result


def _finish_child():
    """В конце копия базы сливается в один файл, чтобы родительский процесс прочитал её целиком."""
    from . import db
    c = db.conn()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()


# ---------- репетиция ----------

def rehearse(db_file, out=print):
    """Репетиция на копии базы. Возвращает список проблем (пустой список: можно обновлять)."""
    db_file = Path(db_file)
    if not db_file.is_file():
        raise PreflightError(f"Файла {db_file} нет.")
    work = Path(tempfile.mkdtemp(prefix="portal-rehearsal-"))
    problems = []
    try:
        copy = work / "portal.db"
        try:                                                              # копия средствами SQLite: согласованная, даже если база сейчас используется
            src = sqlite3.connect(f"file:{quote(str(db_file))}?mode=ro", uri=True)
            dst = sqlite3.connect(copy)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
        except sqlite3.Error:
            shutil.copyfile(db_file, copy)                                # запасной путь: если файл не читается как база, проверка ниже это скажет
        before = snapshot(copy)
        out(f"База: {db_file} ({_mb(db_file.stat().st_size)}), версия схемы {before['user_version']}")
        ok_line = lambda text: out(f"  ✓ {text}")
        bad_line = lambda text: (out(f"  ✗ {text}"), problems.append(text))
        (ok_line if before["integrity"] == "ok" else bad_line)(f"Целостность базы: {before['integrity']}")
        if before["integrity"] != "ok":
            return problems
        env = dict(os.environ, DATA_DIR=str(work), PYTHONDONTWRITEBYTECODE="1")
        child = subprocess.run([sys.executable, "-m", "app.preflight", "--child"], env=env, capture_output=True, text=True, timeout=600)
        if child.returncode != 0:
            tail = (child.stderr or child.stdout).strip().splitlines()[-6:]
            bad_line("Запуск новой версии на копии базы завершился ошибкой:")
            for line in tail:
                out("      " + line)
            return problems
        try:
            report = json.loads(child.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            bad_line("Не удалось прочитать результат проверки: " + child.stdout[-200:])
            return problems
        after = snapshot(copy, before["columns"])
        full = snapshot(copy)
        ok_line(f"Миграция прошла: схема {before['user_version']} → {full['user_version']}" if full["user_version"] != before["user_version"]
                else f"Схема уже актуальна (версия {full['user_version']})")
        for note in report["notes"]:
            out(f"      • {note}")
        (ok_line if full["integrity"] == "ok" else bad_line)(f"Целостность после миграции: {full['integrity']}")
        diff = compare(before, after)
        for kind, label in (("lost", "пропали строки"), ("changed", "изменились строки")):
            for table, keys in diff[kind].items():
                bad_line(f"В таблице «{table}» {label}: {len(keys)} (например {keys[0][:80]})")
        if not diff["lost"] and not diff["changed"]:
            total = sum(len(r) for r in before["tables"].values())
            ok_line(f"Все данные на месте: {total} строк в {len(before['tables'])} таблицах не потеряно и не изменено")
        counts = ", ".join(f"{t} {len(r)}→{len(full['tables'].get(t, {}))}" for t, r in before["tables"].items() if r)
        out(f"      по таблицам: {counts}")
        for p in report["problems"]:
            bad_line(p)
        info = report["info"]
        if not report["problems"]:
            ok_line(f"Мастер и игроки ({info.get('viewers', 0) - 1}) получают своё состояние, дневников собрано {info.get('diaries', 0)}, записей {info.get('entries', 0)}")
            ok_line("Картинки и раздатки, на которые ссылаются карточки, на месте")
        return problems
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Репетиция обновления портала на копии базы.")
    parser.add_argument("--db", help="файл базы (лучше копия, сделанная python -m app.backup)")
    parser.add_argument("--compare", nargs=2, metavar=("СТАРАЯ", "НОВАЯ"), help="сверить две базы: в новой должно быть всё из старой")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        result = child_checks()
        _finish_child()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    try:
        if args.compare:
            old = snapshot(args.compare[0])
            new = snapshot(args.compare[1], old["columns"])
            diff = compare(old, new)
            bad = False
            for kind, label in (("lost", "пропали"), ("changed", "изменились")):
                for table, keys in diff[kind].items():
                    bad = True
                    print(f"  ✗ В таблице «{table}» {label} строки: {len(keys)} (например {keys[0][:80]})")
            if new["integrity"] != "ok":
                bad = True
                print(f"  ✗ Целостность новой базы: {new['integrity']}")
            if not bad:
                print(f"  ✓ В новой базе есть всё из старой ({sum(len(r) for r in old['tables'].values())} строк), целостность ok")
            return 1 if bad else 0
        if not args.db:
            parser.error("укажите --db ФАЙЛ или --compare СТАРАЯ НОВАЯ")
        problems = rehearse(args.db)
    except PreflightError as ex:
        print(f"  ✗ {ex}")
        return 1
    print("Итог: " + ("можно обновлять." if not problems else f"ЕСТЬ ПРОБЛЕМЫ ({len(problems)}): обновлять не нужно, ничего не изменено."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
