from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import ROOT_DIR, get_settings
from app.db.seed import ensure_agent_seed, seed_knowledge_if_empty
from app.db.session import init_db
from app.rag.ingest import ensure_upload_dir
from app.tts import tts_status

FRONTEND_DIR = ROOT_DIR / "frontend"


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    ensure_upload_dir()
    await seed_knowledge_if_empty()
    await ensure_agent_seed()
    asyncio.create_task(_warmup_local_tts())
    asyncio.create_task(_warmup_local_stt())
    asyncio.create_task(_warmup_mcp())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Fullstack Starter",
        description="可运行的 AI Agent + LLM 应用脚手架",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def ensure_utf8_json(request, call_next):
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if ctype.startswith("application/json") and "charset" not in ctype.lower():
            response.headers["content-type"] = "application/json; charset=utf-8"
        # 开发期避免侧栏样式/脚本被浏览器强缓存
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

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
        }

    return app


app = create_app()
