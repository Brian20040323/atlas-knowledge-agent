from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import hashlib
import hmac
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import ROOT_DIR, get_settings
from app.db.seed import ensure_agent_seed, seed_knowledge_if_empty
from app.db.session import init_db
from app.rag.ingest import ensure_upload_dir
from app.tts import tts_status

FRONTEND_DIR = ROOT_DIR / "frontend"
AUTH_COOKIE = "atlas_gate"
_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Atlas 访问验证</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;font-family:"Microsoft YaHei",sans-serif;
background:#ececee;color:#111}}
form{{width:min(92vw,360px);padding:1.5rem;background:#f6f6f7;border:1px solid #d8d8db;border-radius:12px}}
h1{{margin:0 0 .35rem;font-size:1.15rem;letter-spacing:.12em}}p{{margin:0 0 1rem;color:#6b6b6b;font-size:.9rem}}
input{{width:100%;box-sizing:border-box;padding:.7rem .8rem;border:1px solid #c4c4c8;border-radius:8px;margin-bottom:.8rem}}
button{{width:100%;padding:.7rem;border:0;border-radius:8px;background:#1a1a1a;color:#f5f5f5;font-weight:600;cursor:pointer}}
.err{{color:#b91c1c;font-size:.85rem;margin:0 0 .7rem}}
</style></head><body>
<form method="post" action="/__gate">
<h1>ATLAS</h1><p>公网访问已开启口令保护</p>
{err}
<input type="password" name="password" placeholder="访问口令" required autofocus/>
<input type="hidden" name="next" value="{next}"/>
<button type="submit">进入</button>
</form></body></html>"""


def _gate_token(password: str) -> str:
    return hashlib.sha256(f"atlas-gate::{password}".encode("utf-8")).hexdigest()


def _authorized(request: Request, password: str) -> bool:
    if not password:
        return True
    expected = _gate_token(password)
    cookie = request.cookies.get(AUTH_COOKIE) or ""
    header = request.headers.get("x-atlas-password") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        header = auth[7:].strip()
    return hmac.compare_digest(cookie, expected) or hmac.compare_digest(header, password)


async def _warmup_local_tts() -> None:
    settings = get_settings()
    status = tts_status(settings)
    if status.get("provider") != "local" or not status.get("ready"):
        return
    try:
        from app.tts import _get_xtts, prepare_voice_ref, preferred_voice_ref

        ref = preferred_voice_ref()
        prepare_voice_ref()  # refresh cleaned ref from latest sample
        if not preferred_voice_ref().is_file() and ref.is_file():
            pass
        await asyncio.to_thread(_get_xtts)
        print("TTS: local XTTS model ready")
    except Exception as exc:  # noqa: BLE001
        print(f"TTS warmup skipped: {exc}")


async def _warmup_local_stt() -> None:
    try:
        from app.stt import stt_status, _get_model

        if not stt_status().get("ready"):
            return
        await asyncio.to_thread(_get_model)
        print("STT: local Whisper model ready")
    except Exception as exc:  # noqa: BLE001
        print(f"STT warmup skipped: {exc}")


async def _warmup_mcp() -> None:
    try:
        from app.config import get_settings
        from app.mcp.client import load_mcp_into_tools

        settings = get_settings()
        status = load_mcp_into_tools(settings)
        if status.get("enabled"):
            print(
                f"MCP: loaded {status.get('tools', 0)} tools "
                f"from {status.get('servers') or []}"
            )
            if status.get("errors"):
                print(f"MCP errors: {status['errors']}")
    except Exception as exc:  # noqa: BLE001
        print(f"MCP warmup skipped: {exc}")


async def _warmup_retrieval() -> None:
    try:
        from app.config import get_settings
        from app.db import crud
        from app.db.session import get_session_maker
        from app.rag.vector_index import mark_vector_index_dirty, build_index_from_settings

        settings = get_settings()
        if not bool(getattr(settings, "rag_vector_enabled", False)):
            print("RAG: vector hybrid disabled (set RAG_VECTOR_ENABLED=true)")
            return
        mark_vector_index_dirty()
        session_maker = get_session_maker()
        async with session_maker() as db:
            documents = await crud.list_documents(db, limit=int(settings.rag_scan_limit))
        index = build_index_from_settings(settings)
        index.ensure(
            documents,
            chunk_size=int(settings.rag_chunk_size),
            overlap=int(settings.rag_chunk_overlap),
            max_chunks=int(settings.rag_max_chunks_per_doc),
        )
        print(
            f"RAG: dense+sparse ready docs={len(documents)} "
            f"provider={getattr(settings, 'rag_embedding_provider', 'hash')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"RAG warmup skipped: {exc}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    ensure_upload_dir()
    await seed_knowledge_if_empty()
    await ensure_agent_seed()
    asyncio.create_task(_warmup_retrieval())
    asyncio.create_task(_warmup_local_tts())
    asyncio.create_task(_warmup_local_stt())
    asyncio.create_task(_warmup_mcp())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    cors_origins = [
        origin.strip()
        for origin in (settings.cors_origins or "").split(",")
        if origin.strip()
    ]
    app = FastAPI(
        title="AI Fullstack Starter",
        description="可运行的 AI Agent + LLM 应用脚手架",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def public_gate(request: Request, call_next):
        password = (settings.atlas_public_password or "").strip()
        path = request.url.path
        if not password or path in {"/__gate", "/api/health"}:
            return await call_next(request)
        if _authorized(request, password):
            return await call_next(request)
        if request.method == "GET" and (
            path == "/" or path.startswith("/static/") or not path.startswith("/api/")
        ):
            # 用 200 返回登录页：公网隧道下 401 易被重试/卡住
            html = _LOGIN_HTML.format(err="", next=quote(path or "/"))
            return HTMLResponse(html, status_code=200)
        return Response("Unauthorized", status_code=401)

    @app.middleware("http")
    async def ensure_utf8_json(request, call_next):
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if ctype.startswith("application/json") and "charset" not in ctype.lower():
            response.headers["content-type"] = "application/json; charset=utf-8"
        # 静态资源：图片可缓存，减轻公网隧道反复拉取
        path = request.url.path
        if path.startswith("/static/") and path.endswith((".jpg", ".jpeg", ".png", ".webp", ".svg")):
            response.headers["Cache-Control"] = "public, max-age=86400"
        elif path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.post("/__gate")
    async def gate_login(
        request: Request,
        password: str = Form(...),
        next: str = Form("/"),
    ):
        expected = (settings.atlas_public_password or "").strip()
        dest = next if next.startswith("/") else "/"
        if not expected or not hmac.compare_digest(password, expected):
            html = _LOGIN_HTML.format(
                err='<p class="err">口令错误</p>',
                next=quote(dest),
            )
            return HTMLResponse(html, status_code=401)
        resp = RedirectResponse(dest, status_code=303)
        # Cloudflare HTTPS 隧道必须 Secure，否则 cookie 可能丢，表现为登不进去
        forwarded = (request.headers.get("x-forwarded-proto") or "").lower()
        secure = forwarded == "https" or (request.url.scheme == "https")
        resp.set_cookie(
            AUTH_COOKIE,
            _gate_token(expected),
            httponly=True,
            samesite="lax",
            secure=secure,
            max_age=60 * 60 * 24 * 7,
            path="/",
        )
        return resp

    app.include_router(router, prefix="/api")

    static_dir = FRONTEND_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(
            FRONTEND_DIR / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/api/meta")
    async def meta():
        return {
            "name": "AI Fullstack Starter",
            "mode": "mock" if settings.use_mock else "llm",
            "model": settings.llm_model,
            "model_complex": settings.llm_model_complex,
        }

    return app


app = create_app()
