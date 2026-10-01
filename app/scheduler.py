"""Фоновый планировщик: раз в несколько секунд отправляет готовые уведомления из очереди и делает уборку.

Работает отдельным потоком внутри приложения (внешний cron не нужен). В тестах выключается (SCHEDULER=0), там
run_once вызывается вручную с подставным временем и подставной отправкой.
"""
import logging
import threading
import time

from . import audit, notify, outbox, recap, reminders, trash
from .config import SCHEDULER

log = logging.getLogger("portal.scheduler")
TICK = 20              # секунд между проходами
MAINTENANCE_EVERY = 3600
REMIND_EVERY = 600        # как часто смотреть, не пора ли напомнить о приглашениях

_thread = None
_stop = threading.Event()
_last_maintenance = 0.0
_last_remind = 0.0


def run_once(now=None, send=None) -> dict:
    """Один проход. send(tg_id, text, section, buttons) подменяется в тестах."""
    global _last_maintenance, _last_remind
    now = time.time() if now is None else now
    done = {"sent": 0, "maintenance": False, "reminded": 0}
    if now - _last_remind >= REMIND_EVERY:
        _last_remind = now
        done["reminded"] = reminders.run(now)
    if notify._enabled() or send is not None:
        done["sent"] = outbox.flush(send or notify.deliver, now)
    if now - _last_maintenance >= MAINTENANCE_EVERY:
        _last_maintenance = now
        trash.purge_expired()
        audit.purge_old()
        outbox.purge_stale(now=now)
        reminders.purge_orphans()
        recap.purge_old()
        done["maintenance"] = True
    return done


def _loop():
    while not _stop.wait(TICK):
        try:
            run_once()
        except Exception:  # noqa: BLE001 - планировщик не должен останавливаться из-за одной ошибки
            log.exception("Сбой в планировщике, продолжаю работу")


def start():
    global _thread
    if not SCHEDULER or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="portal-scheduler", daemon=True)
    _thread.start()
    return True


def stop():
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
        _thread = None
