"""Что портал делает с данными при каждом запуске: схема базы, начальные данные, разовые поправки, уборка.

Это одно место и для сервера (lifespan в main.py), и для «репетиции обновления» (app/preflight.py): репетиция проходит ровно
те же шаги, что настоящий запуск, поэтому не может разойтись с ним.
"""
import logging

from . import audit, db, seed, trash


def prepare_data(log=None):
    """Привести базу в порядок. Возвращает список заметок о том, что сделано (для журнала и отчёта репетиции)."""
    log = log or logging.getLogger("portal")
    notes = []
    before = db.schema_version() if db.DB_PATH.exists() else None
    db.init()
    if before is not None and before != db.schema_version():
        notes.append(f"схема базы обновлена с версии {before} до {db.schema_version()}")
        log.info("Схема базы обновлена с версии %s до %s", before, db.schema_version())
    if seed.seed("auto"):
        notes.append("база заполнена из config/campaign.json")
        log.info("База заполнена из config/campaign.json")
    added = seed.ensure(("places", "dnotes", "dossier", "travel"))
    if added:
        notes.append("добавлены разделы: " + ", ".join(added))
        log.info("Добавлены разделы из config/campaign.json: %s", ", ".join(added))
    for note in seed.migrate():
        notes.append("обновление данных: " + note)
        log.info("Обновление данных: %s", note)
    gone = trash.purge_expired()
    audit.purge_old()
    if gone:
        notes.append(f"из корзины удалено окончательно: {gone}")
        log.info("Из корзины удалено окончательно (вышел срок хранения): %s", gone)
    return notes
