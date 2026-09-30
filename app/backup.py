"""Резервная копия базы: python -m app.backup [сколько копий хранить, по умолчанию 14]."""
import sqlite3
import sys
import time

from .config import DATA_DIR
from .db import DB_PATH


def backup(keep=14):
    folder = DATA_DIR / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"portal-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    copies = sorted(folder.glob("portal-*.db"))
    for old in copies[:-keep]:
        old.unlink()
    return target


if __name__ == "__main__":
    keep = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(backup(keep))
