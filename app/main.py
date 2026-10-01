"""Портал кампании «Сиэтл 2075». Запуск: uvicorn app.main:app"""
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from . import audit, auth, config, db, handouts, logic, notify, outbox, portraits, scheduler, seed, telegram_bot, trash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("portal")


@asynccontextmanager
async def lifespan(_app):
    log.info("Портал, версия %s", config.VERSION)
    db.init()
    if seed.seed("auto"):
        log.info("База заполнена из config/campaign.json")
    added = seed.ensure(("places", "dnotes", "dossier", "travel"))
    if added:
        log.info("Добавлены разделы из config/campaign.json: %s", ", ".join(added))
    for note in seed.migrate():
        log.info("Обновление данных: %s", note)
    gone = trash.purge_expired()
    audit.purge_old()
    if gone:
        log.info("Из корзины удалено окончательно (вышел срок хранения): %s", gone)
    try:
        config.people()  # ошибка в players.toml видна сразу при запуске
    except FileNotFoundError as ex:
        log.error("%s", ex)
        raise
    if not config.BOT_TOKEN:
        log.warning("BOT_TOKEN не задан: вход через Telegram работать не будет")
    if config.DEV_LOGIN_REQUESTED and not config.DEV_LOGIN:
        log.error("DEV_LOGIN=1 проигнорирован: задан BOT_TOKEN, это рабочий сервер. Уберите DEV_LOGIN из .env")
    if config.DEV_LOGIN:
        log.warning("DEV_LOGIN включён: вход без Telegram. На рабочем сервере выключите")
    if scheduler.start():
        log.info("Планировщик запущен: уведомления, напоминания, уборка")
    if config.TG_WEBHOOK:
        if notify.webhook_on():
            notify._background(telegram_bot.register)       # в фоне: если Telegram недоступен, портал всё равно стартует
            log.info("Кнопки в сообщениях бота включены: webhook %s", telegram_bot.webhook_url())
        else:
            log.error("TG_WEBHOOK=1 не работает: нужны BOT_TOKEN и SITE_URL с https://")
    yield
    scheduler.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Непредвиденный сбой: в журнал с подробностями, наружу короткий JSON (без внутренностей)."""
    log.error("Необработанная ошибка: %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": "Внутренняя ошибка сервера. Попробуйте ещё раз."}, status_code=500)


# Кто может встраивать страницу портала: сам портал и веб-версии Telegram (там Mini App открывается во фрейме).
# Приложения Telegram на телефоне и компьютере открывают её не во фрейме, их это не касается.
FRAME_POLICY = "frame-ancestors 'self' https://telegram.org https://*.telegram.org"


def csp_policy() -> str:
    """Что странице разрешено загружать и исполнять. Скрипты только с нашего сервера и из telegram.org,
    inline-скриптов нет. 'unsafe-eval' нужен лишь старому способу входа (data-onauth) и включается вместе с ним."""
    scripts = "'self' https://telegram.org" + (" 'unsafe-eval'" if config.TG_WIDGET_MODE == "callback" else "")
    return "; ".join([
        "default-src 'self'",
        f"script-src {scripts}",
        "style-src 'self'",
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data: blob: https://telegram.org https://*.telegram.org https://t.me https://*.t.me",
        "font-src 'self'",
        "connect-src 'self'",
        "media-src 'self'",
        "frame-src 'self' https://oauth.telegram.org",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "report-uri /api/csp-report",
    ])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path == "/":
        mode = config.CSP_MODE
        if mode == "enforce":
            response.headers.setdefault("Content-Security-Policy", csp_policy() + "; " + FRAME_POLICY)
        else:
            # frame-ancestors в режиме «только сообщать» не работает, поэтому он всегда отдельным настоящим заголовком
            response.headers.setdefault("Content-Security-Policy", FRAME_POLICY)
            if mode == "report-only":
                response.headers.setdefault("Content-Security-Policy-Report-Only", csp_policy())
    if request.url.path.startswith("/api/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/static/vendor/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"  # шрифты не меняются, страница грузится быстрее
    elif request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- кто пришёл ----------

def viewer(request: Request) -> logic.Viewer:
    token = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        token = request.cookies.get("session")
    ident = auth.read_token(token) if token else None
    if not ident:
        raise HTTPException(401, "Нужно войти через Telegram.")
    role = config.resolve(*ident)
    if not role:
        raise HTTPException(403, {"code": "not_listed", "tg_id": ident[0],
                                  "message": "Вашего Telegram нет в списке игроков."})
    return logic.Viewer(role[0], role[1], *ident)


def _set_session(response, token):
    response.set_cookie("session", token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return response


def _login(user):
    db.remember_login(user["id"], user.get("username", ""), user.get("first_name", ""))
    token = auth.make_token(user["id"], user.get("username", ""))
    listed = config.resolve(user["id"], user.get("username", "")) is not None
    return _set_session(JSONResponse({"token": token, "listed": listed, "tg_id": user["id"]}), token)


# ---------- страницы и настройки ----------

@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": config.VERSION}


@app.get("/api/config")
def public_config():
    return {"bot_username": config.BOT_USERNAME, "dev_login": config.DEV_LOGIN, "widget_mode": config.TG_WIDGET_MODE}


# ---------- отчёты о нарушениях CSP ----------

_csp_seen = {"minute": 0, "count": 0}


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """Сюда Telegram присылает нажатия на кнопки в сообщениях бота. Подлинность по секретному заголовку."""
    if not notify.webhook_on():
        raise HTTPException(404, "Не найдено.")
    if not telegram_bot.check_secret(request.headers.get("x-telegram-bot-api-secret-token")):
        raise HTTPException(403, "Неверный секрет.")
    if len(await request.body()) > 65536:
        raise HTTPException(413, "Слишком большой запрос.")
    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(400, "Нужен JSON.")
    await run_in_threadpool(telegram_bot.handle_update, update)
    return {"ok": True}


@app.post("/api/csp-report", status_code=204)
async def csp_report(request: Request):
    """Браузер сообщает, что заблокировал (или заблокировал бы) что-то на странице. Пишем в журнал, не больше 20 в минуту."""
    import json
    import time
    body = await request.body()
    minute = int(time.time() // 60)
    if _csp_seen["minute"] != minute:
        _csp_seen.update(minute=minute, count=0)
    _csp_seen["count"] += 1
    if _csp_seen["count"] > 20 or len(body) > 8192:
        return Response(status_code=204)
    try:
        data = json.loads(body).get("csp-report", {})
        log.warning("CSP: %s заблокировано %s (страница %s, режим %s)", data.get("violated-directive", "?"),
                    str(data.get("blocked-uri", "?"))[:120], str(data.get("document-uri", "?"))[:120], config.CSP_MODE)
    except (ValueError, AttributeError):
        pass
    return Response(status_code=204)


# ---------- вход ----------

@app.post("/api/auth/widget")
def auth_widget(data: dict = Body(...)):
    try:
        return _login(auth.check_widget(data))
    except auth.AuthError as ex:
        raise HTTPException(401, str(ex))


@app.get("/auth/telegram")
def auth_telegram_redirect(request: Request):
    """Вход через кнопку Telegram в режиме редиректа: Telegram переводит браузер сюда с подписанными данными в адресе."""
    try:
        user = auth.check_widget(dict(request.query_params))
    except auth.AuthError as ex:
        log.info("Вход через виджет не удался: %s", ex)
        return RedirectResponse("/?auth=failed", status_code=303)
    db.remember_login(user["id"], user.get("username", ""), user.get("first_name", ""))
    return _set_session(RedirectResponse("/", status_code=303), auth.make_token(user["id"], user.get("username", "")))


@app.post("/api/auth/webapp")
def auth_webapp(data: dict = Body(...)):
    try:
        return _login(auth.check_webapp(str(data.get("init_data", ""))))
    except auth.AuthError as ex:
        raise HTTPException(401, str(ex))


@app.post("/api/auth/dev")
def auth_dev(data: dict = Body(...)):
    if not config.DEV_LOGIN:
        raise HTTPException(404, "Не найдено.")
    try:
        tg_id = int(data.get("tg_id", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Нужен числовой Telegram ID.")
    return _login({"id": tg_id, "username": str(data.get("username", "")), "first_name": "dev"})


@app.post("/api/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("session", path="/")
    return response


# ---------- данные ----------

@app.get("/api/state")
def get_state(request: Request, since: int = -1):
    v = viewer(request)
    if since >= 0 and int(db.meta_get("version", "0")) == since:
        return {"unchanged": True}
    return logic.state_for(v)


def _answer(v, msg):
    return {"msg": msg, "state": logic.state_for(v)}


@app.post("/api/entries")
def create_entry(request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.create_entry(v, data))


@app.post("/api/entries/{entry_id}/act")
def entry_action(entry_id: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.entry_action(v, entry_id, data))


@app.post("/api/entries/{entry_id}/edit")
def edit_entry(entry_id: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.edit_entry(v, entry_id, data))


@app.post("/api/entries/{entry_id}/messages")
def add_message(entry_id: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.add_message(v, entry_id, data))


@app.post("/api/entries/{entry_id}/roll")
def roll_dice(entry_id: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.roll_dice(v, entry_id, data))


@app.post("/api/gm/time")
def gm_time(request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.gm_time(v, data))


@app.post("/api/gm/plan/{plan_id}/played")
def plan_played(plan_id: str, request: Request):
    v = viewer(request)
    return _answer(v, logic.plan_played(v, plan_id))


@app.post("/api/gm/items/{kind}")
def save_item(kind: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.save_item(v, kind, data))


@app.post("/api/gm/items/{kind}/{item_id}/delete")
def delete_item(kind: str, item_id: str, request: Request):
    v = viewer(request)
    return _answer(v, logic.delete_item(v, kind, item_id))


@app.post("/api/gm/district/{slug}")
def save_dnote(slug: str, request: Request, data: dict = Body(...)):
    v = viewer(request)
    return _answer(v, logic.save_dnote(v, slug, data))


@app.get("/api/me/prefs")
def get_prefs(request: Request):
    v = viewer(request)
    return {"prefs": outbox.prefs(v.tg_id), "dm": bool(config.BOT_TOKEN and config.NOTIFY_DM),
            "chat_minutes": max(1, round(config.CHAT_NOTIFY_DELAY / 60)),
            "remind_days": config.REMIND_DAYS, "remind_max": config.REMIND_MAX}


@app.post("/api/me/prefs")
def set_prefs(request: Request, data: dict = Body(...)):
    v = viewer(request)
    try:
        return {"prefs": outbox.save_prefs(v.tg_id, data)}
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@app.post("/api/me/prefs/test")
def test_notification(request: Request):
    """Пробное личное сообщение: сразу, без очереди и тихих часов, чтобы человек увидел, работает ли связь."""
    v = viewer(request)
    if not (config.BOT_TOKEN and config.NOTIFY_DM):
        raise HTTPException(400, "Личные уведомления на этом портале выключены.")
    try:
        notify.deliver(v.tg_id, "Проверка связи: если вы видите это сообщение, личные уведомления от портала работают.", "now")
    except notify.TelegramError as ex:
        hint = " Откройте бота в Telegram и нажмите «Запустить», затем повторите." if ex.code in (400, 403) else ""
        raise HTTPException(502, f"Telegram не принял сообщение (код {ex.code}).{hint}")
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(502, f"Не удалось связаться с Telegram: {type(ex).__name__}")
    return {"ok": True}


def _gm_only(request: Request):
    v = viewer(request)
    if not v.gm:
        raise HTTPException(403, "Только для мастера.")
    return v


@app.get("/api/gm/history")
def gm_history(request: Request, limit: int = 50, before: int = 0, kind: str = "", item: str = "", q: str = ""):
    _gm_only(request)
    return {"items": audit.listing(limit, before or None, kind[:20], item[:40], q[:60])}


@app.get("/api/gm/trash")
def gm_trash(request: Request):
    _gm_only(request)
    return {"items": trash.listing(), "days": config.TRASH_DAYS}


@app.post("/api/gm/trash/empty")
def gm_trash_empty(request: Request):
    v = _gm_only(request)
    return _answer(v, logic.empty_trash(v))


@app.post("/api/gm/trash/{trash_id}/restore")
def gm_trash_restore(trash_id: int, request: Request):
    v = _gm_only(request)
    return _answer(v, logic.restore_trash(v, trash_id))


@app.post("/api/gm/trash/{trash_id}/purge")
def gm_trash_purge(trash_id: int, request: Request):
    v = _gm_only(request)
    return _answer(v, logic.purge_trash(v, trash_id))


@app.post("/api/gm/history/{audit_id}/revert")
def gm_history_revert(audit_id: int, request: Request):
    v = _gm_only(request)
    return _answer(v, logic.revert_change(v, audit_id))


@app.post("/api/gm/dossier/{card_id}/portrait")
async def upload_portrait(card_id: str, request: Request):
    """Тело запроса: сама картинка. Размер проверяется до и во время чтения."""
    v = viewer(request)
    if not v.gm:
        raise HTTPException(403, "Только для мастера.")
    limit = portraits.upload_limit_bytes()
    too_big = f"Файл больше {portraits.mb(limit)} МБ. Уменьшите картинку и попробуйте снова."
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, too_big)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, too_big)
    msg = await run_in_threadpool(logic.save_portrait, v, card_id, bytes(buf))
    return _answer(v, msg)


@app.post("/api/gm/dossier/{card_id}/portrait/delete")
def delete_portrait(card_id: str, request: Request):
    v = viewer(request)
    return _answer(v, logic.delete_portrait(v, card_id))


@app.get("/portrait/{token}/{name}")
def get_portrait(token: str, name: str):
    """Картинка по секретному токену: он приходит только тем, кому открыта карточка, и меняется при замене."""
    if not re.fullmatch(r"[0-9a-f]{32}", token) or name not in ("f.webp", "t.webp"):
        raise HTTPException(404)
    data = portraits.get(token, name[0])
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.post("/api/gm/handouts/{item_id}/file")
async def upload_handout(item_id: str, request: Request):
    """Тело запроса: сам HTML-файл. Имя файла приходит в заголовке X-File-Name (в URL-кодировке)."""
    v = viewer(request)
    if not v.gm:
        raise HTTPException(403, "Только для мастера.")
    limit = handouts.upload_limit_bytes()
    too_big = f"Файл больше {portraits.mb(limit)} МБ. Уменьшите его (например, сожмите картинки внутри) и попробуйте снова."
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, too_big)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, too_big)
    from urllib.parse import unquote
    fname = unquote(request.headers.get("x-file-name", ""))[:200]
    msg = await run_in_threadpool(logic.save_handout_file, v, item_id, bytes(buf), fname)
    return _answer(v, msg)


def _ranged(data: bytes, mime: str, header: str, headers: dict) -> Response:
    """Ответ на запрос части файла (Range: bytes=…). Без заголовка или с непонятным значением отдаётся весь файл."""
    size = len(data)
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m or not (m.group(1) or m.group(2)):
        return Response(data, media_type=mime, headers=headers)
    if m.group(1):
        start, end = int(m.group(1)), min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
    else:                                                  # «последние N байт»
        n = int(m.group(2))
        start, end = max(size - n, 0), size - 1
    if size == 0 or start >= size or start > end:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    return Response(data[start:end + 1], status_code=206, media_type=mime,
                    headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"})


@app.get("/handout/{token}/view")
def view_handout(token: str, request: Request):
    """Раздатка по секретному токену. Заголовок sandbox изолирует её от портала даже при прямом открытии."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(404)
    found = handouts.get(token)
    if found is None:
        raise HTTPException(404)
    headers = {"Cache-Control": "private, max-age=31536000, immutable", "Referrer-Policy": "no-referrer"}
    if found["encoding"] == "gzip":                       # HTML: в песочнице, сжатым, если браузер умеет
        headers.update({"Content-Security-Policy": handouts.SANDBOX, "Vary": "Accept-Encoding"})
        if "gzip" in request.headers.get("accept-encoding", "").lower():
            headers["Content-Encoding"] = "gzip"
            return Response(found["data"], media_type="text/html; charset=utf-8", headers=headers)
        import gzip as _gzip
        return Response(_gzip.decompress(found["data"]), media_type="text/html; charset=utf-8", headers=headers)
    # картинки, PDF, звук: точный тип без угадывания, с поддержкой Range (иначе звук нельзя перематывать)
    headers.update({"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline", "Accept-Ranges": "bytes",
                    "Cross-Origin-Resource-Policy": "same-origin"})
    return _ranged(found["data"], found["mime"], request.headers.get("range", ""), headers)

