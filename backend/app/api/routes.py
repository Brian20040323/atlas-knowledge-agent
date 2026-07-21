import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents import ChatAgent
from app.api import (
    ChatRequest,
    ConversationOut,
    DocumentCreate,
    DocumentOut,
    HealthResponse,
    KnowledgeLearnRequest,
    KnowledgeSearchResponse,
    MessageOut,
    TtsRequest,
)
from app.config import Settings, get_settings
from app.db import crud
from app.db.session import get_db, get_session_maker
from app.rag.ingest import (
    ALLOWED_EXT,
    IngestLimitError,
    detect_source_type,
    ensure_upload_dir,
    extract_text_from_bytes,
    safe_filename,
    validate_content_length,
    validate_upload_size,
)
from app.mcp import list_tools as mcp_list_tools
from app.mcp.client import load_mcp_into_tools, mcp_status
from app.observability import concurrency_stats, get_run, list_recent_runs
from app.observability.concurrency import acquire_chat_slot, release_chat_slot
from app.rag.knowledge import KnowledgeService
from app.stt import stt_status, transcribe_audio_bytes
from app.tools import run_tool
from app.tts import ingest_voice_sample, synthesize_speech, tts_status

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    tts = tts_status(settings)
    stt = stt_status(settings)
    mcp = mcp_status(settings)
    return HealthResponse(
        status="ok",
        mode="mock" if settings.use_mock else "llm",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        tts_provider=tts["provider"],
        tts_ready=bool(tts["ready"]),
        stt_provider=stt["provider"],
        stt_ready=bool(stt["ready"]),
        mcp_enabled=bool(mcp.get("enabled")),
        mcp_servers=int(mcp.get("server_count") or 0),
    )


@router.get("/tts/status")
async def get_tts_status(settings: Settings = Depends(get_settings)) -> dict:
    return tts_status(settings)


@router.get("/stt/status")
async def get_stt_status(settings: Settings = Depends(get_settings)) -> dict:
    return stt_status(settings)


@router.post("/stt")
async def create_stt(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    name = file.filename or "audio.webm"
    suffix = Path(name).suffix.lower() or ".webm"
    try:
        text = await transcribe_audio_bytes(data, suffix=suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"语音识别失败: {exc}") from exc
    return {"text": text, "provider": "whisper"}


@router.post("/voice/sample")
async def upload_voice_sample(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) < 1000:
        raise HTTPException(status_code=400, detail="文件太小，请上传至少 10 秒的清晰录音")
    try:
        ref = await ingest_voice_sample(data, file.filename or "sample.wav")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"音色样本处理失败: {exc}") from exc
    return {
        "ok": True,
        "ref": ref.name,
        "hint": "已更新克隆参考音，请刷新页面后用喇叭试听",
    }


@router.post("/tts")
async def create_tts(
    body: TtsRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        audio, media_type = await synthesize_speech(body.text, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS 服务异常: {exc}") from exc
    return Response(content=audio, media_type=media_type)


@router.get("/mcp/tools")
async def get_mcp_tools() -> dict:
    """List tools exposed by the Atlas MCP server (same set Cursor would see)."""
    return {"tools": mcp_list_tools(), "server": "atlas-mcp"}


@router.post("/mcp/call")
async def call_mcp_tool(body: dict) -> dict:
    """HTTP helper to call an Atlas tool (for debugging MCP without stdio)."""
    name = (body or {}).get("name") or ""
    arguments = (body or {}).get("arguments") or {}
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    try:
        result = await run_tool(name, arguments)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"name": name, "result": result}


@router.get("/mcp/status")
async def get_mcp_status(settings: Settings = Depends(get_settings)) -> dict:
    status = mcp_status(settings)
    if settings.mcp_enabled and not status.get("loaded"):
        status = load_mcp_into_tools(settings)
    return status


@router.get("/runs")
async def list_runs(limit: int = 20) -> dict:
    return {"runs": list_recent_runs(limit=min(limit, 40))}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str) -> dict:
    item = get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="run not found")
    return item


@router.get("/concurrency")
async def get_concurrency(settings: Settings = Depends(get_settings)) -> dict:
    """P2: inspect chat concurrency gate (active / limit / rejected)."""
    stats = concurrency_stats()
    return {
        **stats,
        "configured_limit": int(settings.max_concurrent_chats),
        "http_timeout_web": settings.http_timeout_web,
        "http_timeout_research": settings.http_timeout_research,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "web_circuit_fail_threshold": settings.web_circuit_fail_threshold,
        "rag_vector_enabled": bool(settings.rag_vector_enabled),
        "rag_embedding_provider": settings.rag_embedding_provider,
    }


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db)) -> list[ConversationOut]:
    conversations = await crud.list_conversations(db)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    ok = await crud.delete_conversation(db, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_conversation_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    conversation = await crud.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await crud.list_messages(db, conversation_id)
    return [MessageOut.model_validate(m) for m in messages]


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[DocumentOut]:
    documents = await crud.list_documents(db)
    return [DocumentOut.model_validate(d) for d in documents]


async def _maybe_graph_extract(doc_id: int, title: str, content: str, settings: Settings) -> None:
    """P4 hook: never raise into HTTP handlers."""
    try:
        from app.rag.graph_extract import maybe_extract_after_learn

        await maybe_extract_after_learn(doc_id, title, content, settings=settings)
    except Exception:  # noqa: BLE001
        return


async def _maybe_faq_extract(doc_id: int, title: str, content: str, settings: Settings) -> None:
    """T8-3 hook: auto FAQ companion doc; never raise into HTTP handlers."""
    try:
        from app.rag.faq_extract import maybe_extract_faq_after_learn

        await maybe_extract_faq_after_learn(doc_id, title, content, settings=settings)
    except Exception:  # noqa: BLE001
        return


@router.post("/documents", response_model=DocumentOut)
async def create_document(
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    try:
        validate_content_length(payload.content, settings.doc_max_chars)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    document = await crud.create_document(db, payload.title, payload.content)
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(document.id, document.title, document.content, settings)
    return DocumentOut.model_validate(document)


@router.post("/knowledge/learn", response_model=DocumentOut)
async def learn_knowledge(
    payload: KnowledgeLearnRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    try:
        validate_content_length(payload.content, settings.doc_max_chars)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    document = await crud.create_document(db, payload.title, payload.content)
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(document.id, document.title, document.content, settings)
    return DocumentOut.model_validate(document)


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(query: str, top_k: int = 3) -> KnowledgeSearchResponse:
    service = KnowledgeService()
    hits = await service.search(query, top_k=top_k)
    return KnowledgeSearchResponse(query=query, results=hits, count=len(hits))


@router.get("/knowledge/graph")
async def search_knowledge_graph(
    query: str,
    hops: int = 1,
    top_k: int = 6,
    settings: Settings = Depends(get_settings),
) -> dict:
    """P4: optional subgraph search; disabled → status=graph_disabled."""
    from app.rag.graph_query import search_subgraph

    return await search_subgraph(
        query,
        hops=hops,
        top_k=top_k,
        settings=settings,
    )


@router.post("/knowledge/upload", response_model=DocumentOut)
async def upload_knowledge(
    file: UploadFile = File(...),
    title: str = Form(""),
    caption: str = Form(""),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext}，支持：{', '.join(sorted(ALLOWED_EXT))}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        validate_upload_size(data, settings.upload_max_mb)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_dir = ensure_upload_dir()
    stored_name = f"{uuid4().hex}_{safe_filename(filename)}"
    stored_path = upload_dir / stored_name
    stored_path.write_bytes(data)

    extracted = extract_text_from_bytes(filename, data)
    if caption.strip():
        extracted = f"用户说明：{caption.strip()}\n\n{extracted}"
    try:
        validate_content_length(extracted, settings.doc_max_chars)
    except IngestLimitError as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_type = detect_source_type(filename)
    doc_title = (title.strip() or Path(filename).stem)[:200]
    document = await crud.create_document(
        db,
        doc_title,
        extracted,
        source_type=source_type,
        file_path=str(stored_path),
    )
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(document.id, document.title, document.content, settings)
    return DocumentOut.model_validate(document)


@router.post("/chat")
async def chat(req: ChatRequest, settings: Settings = Depends(get_settings)):
    # P2: 并发闸门 — 超额立即 429；槽位持有至 SSE 流结束
    if not await acquire_chat_slot(settings.max_concurrent_chats):
        raise HTTPException(
            status_code=429,
            detail=(
                f"并发对话已达上限（{settings.max_concurrent_chats}），"
                "请稍后重试，避免服务过载"
            ),
        )

    agent = ChatAgent(settings)
    messages = [m.model_dump() for m in req.messages]
    user_message = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    conversation_id = req.conversation_id

    async def event_generator():
        nonlocal conversation_id
        assistant_text = ""
        done_mode = "mock" if settings.use_mock else "llm"
        try:
            async for event in agent.stream_chat(
                messages,
                use_tools=req.use_tools,
                deep_think=req.deep_think,
            ):
                event_type = event.get("type", "message")
                if event_type == "token":
                    assistant_text += event.get("content", "")
                elif event_type == "done":
                    done_mode = event.get("mode", done_mode)
                    continue
                yield {
                    "event": event_type,
                    "data": json.dumps(event, ensure_ascii=False),
                }

            session_maker = get_session_maker()
            async with session_maker() as db:
                if conversation_id is None:
                    title = (user_message[:50] or "新对话").strip()
                    conversation = await crud.create_conversation(db, title)
                    conversation_id = conversation.id
                else:
                    conversation = await crud.get_conversation(db, conversation_id)
                    if conversation is None:
                        yield {
                            "event": "error",
                            "data": json.dumps(
                                {"type": "error", "content": "会话不存在"},
                                ensure_ascii=False,
                            ),
                        }
                        return

                await crud.add_message(db, conversation_id, "user", user_message)
                await crud.add_message(
                    db,
                    conversation_id,
                    "assistant",
                    assistant_text or "（无内容）",
                )
                await db.commit()

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "type": "done",
                        "mode": done_mode,
                        "conversation_id": conversation_id,
                        "answer": assistant_text,
                    },
                    ensure_ascii=False,
                ),
            }
        finally:
            release_chat_slot()

    return EventSourceResponse(event_generator())
