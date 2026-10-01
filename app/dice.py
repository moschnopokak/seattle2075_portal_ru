"""Бросок пула d6 по правилам Shadowrun 5 (2075 год).

Успех (попадание) это 5 или 6. Глитч: единиц больше половины исходного пула; критический глитч: глитч без единого успеха.
«Предел» урезает число засчитанных успехов. «Рискнуть» (Push the Limit, Edge): шестёрки взрываются (за каждую бросается ещё один куб,
пока выпадают шестёрки), предел не действует. «Порог»: сколько успехов нужно для успеха проверки.
Кубы бросает сервер (secrets), а не страница, поэтому результат нельзя подогнать.
"""
import secrets

MAX_POOL = 40
MAX_LIMIT = 99
MAX_EXTRA = 200           # страховка от бесконечного взрыва (на деле почти недостижима)
HIT_FROM = 5


def roll(pool, edge=False, limit=None, threshold=None, rng=None):
    rng = rng or secrets.SystemRandom()
    dice = [rng.randint(1, 6) for _ in range(pool)]
    extra = []
    if edge:
        waiting = sum(1 for d in dice if d == 6)
        while waiting and len(extra) < MAX_EXTRA:
            batch = [rng.randint(1, 6) for _ in range(min(waiting, MAX_EXTRA - len(extra)))]
            extra += batch
            waiting = sum(1 for d in batch if d == 6)
    hits = sum(1 for d in dice + extra if d >= HIT_FROM)
    ones = sum(1 for d in dice if d == 1)
    glitch = "" if ones * 2 <= pool else ("critical" if hits == 0 else "glitch")
    counted = hits if (edge or limit is None) else min(hits, limit)
    result = {"pool": pool, "dice": dice, "extra": extra, "hits": hits, "counted": counted, "ones": ones, "glitch": glitch,
              "edge": bool(edge), "limit": limit, "threshold": threshold, "success": None, "net": None}
    if threshold is not None:
        result["success"] = counted >= threshold
        result["net"] = counted - threshold
    return result


def describe(result, label=""):
    """Текст броска для обсуждения и уведомлений. Страница рисует то же самое кубиками, а это запасной вариант."""
    head = f"Бросок {result['pool']}d6" + (f" ({label})" if label else "") + (", с риском (шестёрки взрываются)" if result["edge"] else "")
    faces = " ".join(str(d) for d in result["dice"])
    if result["extra"]:
        faces += " + " + " ".join(str(d) for d in result["extra"])
    text = f"{head}: {faces}. Успехов: {result['hits']}"
    if result["limit"] is not None and not result["edge"] and result["counted"] != result["hits"]:
        text += f", с учётом предела {result['limit']}: {result['counted']}"
    elif result["limit"] is not None and result["edge"]:
        text += " (предел не действует)"
    if result["threshold"] is not None:
        text += f". Порог {result['threshold']}: " + ("успех" if result["success"] else "провал")
    if result["glitch"] == "critical":
        text += ". КРИТИЧЕСКИЙ ГЛИТЧ"
    elif result["glitch"]:
        text += ". Глитч"
    return text + "."
