"""Портал кампании «Сиэтл 2075». Запуск: uvicorn app.main:app"""
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from . import auth, config, db, handouts, logic, portraits, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("portal")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if seed.seed("auto"):
        log.info("База заполнена из config/campaign.json")
    added = seed.ensure(("places", "dnotes", "dossier"))
    if added:
        log.info("Добавлены разделы из config/campaign.json: %s", ", ".join(added))
    for note in seed.migrate():
        log.info("Обновление данных: %s", note)
    config.people()  # ошибка в players.toml видна сразу при запуске
    if not config.BOT_TOKEN:
        log.warning("BOT_TOKEN не задан: вход через Telegram работать не будет")
    if config.DEV_LOGIN:
        log.warning("DEV_LOGIN включён: вход без Telegram. На рабочем сервере выключите")
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
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


def _login(user):
    db.remember_login(user["id"], user.get("username", ""), user.get("first_name", ""))
    token = auth.make_token(user["id"], user.get("username", ""))
    listed = config.resolve(user["id"], user.get("username", "")) is not None
    response = JSONResponse({"token": token, "listed": listed, "tg_id": user["id"]})
    response.set_cookie("session", token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return response


# ---------- страницы и настройки ----------

@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/config")
def public_config():
    return {"bot_username": config.BOT_USERNAME, "dev_login": config.DEV_LOGIN}


# ---------- вход ----------

@app.post("/api/auth/widget")
def auth_widget(data: dict = Body(...)):
    try:
        return _login(auth.check_widget(data))
    except auth.AuthError as ex:
        raise HTTPException(401, str(ex))


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


@app.get("/handout/{token}/view")
def view_handout(token: str, request: Request):
    """Раздатка по секретному токену. Заголовок sandbox изолирует её от портала даже при прямом открытии."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(404)
    data = handouts.get(token)
    if data is None:
        raise HTTPException(404)
    headers = {"Content-Security-Policy": handouts.SANDBOX, "Cache-Control": "private, max-age=31536000, immutable",
               "Referrer-Policy": "no-referrer", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        headers["Content-Encoding"] = "gzip"
        return Response(data, media_type="text/html; charset=utf-8", headers=headers)
    import gzip as _gzip
    return Response(_gzip.decompress(data), media_type="text/html; charset=utf-8", headers=headers)

