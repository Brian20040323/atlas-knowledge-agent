from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents import ChatAgent
from app.agents.reasoning import looks_like_tool_leak, sanitize_assistant_text
from app.api import (
    AuthLoginRequest,
    AuthMeResponse,
    AuthRegisterRequest,
    ChatRequest,
    ConversationOut,
    DocumentCreate,
    DocumentOut,
    HealthResponse,
    KnowledgeLearnRequest,
    KnowledgeSearchResponse,
    MessageOut,
    TtsRequest,
    UserOut,
)
from app.auth.deps import get_current_user, get_optional_user
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import (
    SESSION_COOKIE,
    SESSION_DAYS,
    create_session_token,
    delete_session,
)
from app.config import Settings, get_settings
from app.db import crud
from app.db.models import User
from app.db.session import get_db, get_session_maker
from app.rag.ingest import (
    ALLOWED_EXT,
    IngestLimitError,
    detect_source_type,
    ensure_upload_dir,
    extract_text_from_bytes,
    extract_zip_members,
    is_weak_extraction,
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


def _cookie_secure(request: Request) -> bool:
    forwarded = (request.headers.get("x-forwarded-proto") or "").lower()
    return forwarded == "https" or request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=60 * 60 * 24 * SESSION_DAYS,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _user_scope(user: Optional[User], settings: Settings) -> Optional[int]:
    """When user-auth is on, scope by user.id; otherwise no filter (legacy)."""
    if not settings.atlas_user_auth:
        return None
    if user is None:
        return -1  # unreachable if Depends raised
    return int(user.id)


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me(
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_optional_user),
) -> AuthMeResponse:
    return AuthMeResponse(
        auth_required=bool(settings.atlas_user_auth),
        user=UserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name or user.username,
        )
        if user
        else None,
        register_open=True,
    )


@router.post("/auth/register", response_model=UserOut)
async def auth_register(
    payload: AuthRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.atlas_user_auth:
        raise HTTPException(status_code=400, detail="当前未开启账号登录")
    secret = (settings.atlas_register_secret or "").strip()
    if secret and (payload.invite_code or "").strip() != secret:
        raise HTTPException(status_code=403, detail="邀请码无效")
    username = payload.username.strip().lower()
    if not username.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="用户名仅支持字母、数字、下划线")
    existing = await crud.get_user_by_username(db, username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    user = await crud.create_user(
        db,
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or username,
    )
    token = await create_session_token(db, user.id)
    await db.commit()
    from fastapi.responses import JSONResponse

    body = UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
    )
    resp = JSONResponse(body.model_dump())
    _set_session_cookie(resp, request, token)
    return resp


@router.post("/auth/login", response_model=UserOut)
async def auth_login(
    payload: AuthLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.atlas_user_auth:
        raise HTTPException(status_code=400, detail="当前未开启账号登录")
    user = await crud.get_user_by_username(db, payload.username.strip().lower())
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    token = await create_session_token(db, user.id)
    await db.commit()
    from fastapi.responses import JSONResponse

    body = UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
    )
    resp = JSONResponse(body.model_dump())
    _set_session_cookie(resp, request, token)
    return resp


@router.post("/auth/logout")
async def auth_logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE) or ""
    await delete_session(db, token)
    await db.commit()
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    tts = tts_status(settings)
    stt = stt_status(settings)
    mcp = mcp_status(settings)
    return HealthResponse(
        status="ok",
        mode="mock" if settings.use_mock else "llm",
        model=settings.llm_model,
        model_complex=settings.llm_model_complex,
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
async def call_mcp_tool(
    body: dict,
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    """HTTP helper to call an Atlas tool (for debugging MCP without stdio)."""
    name = (body or {}).get("name") or ""
    arguments = (body or {}).get("arguments") or {}
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if name not in {"web_search", "get_current_time", "calculator"}:
        raise HTTPException(status_code=403, detail="该调试接口不允许调用此工具")
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
async def list_runs(
    limit: int = 20,
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    uid = _user_scope(user, settings)
    return {"runs": list_recent_runs(limit=min(limit, 40), user_id=uid)}


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: str,
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    uid = _user_scope(user, settings)
    item = get_run(run_id, user_id=uid)
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
        "per_user_limit": int(settings.max_chats_per_user),
        "queue_wait_seconds": float(settings.chat_queue_wait_seconds),
        "http_timeout_web": settings.http_timeout_web,
        "http_timeout_research": settings.http_timeout_research,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "web_circuit_fail_threshold": settings.web_circuit_fail_threshold,
        "rag_vector_enabled": bool(settings.rag_vector_enabled),
        "rag_embedding_provider": settings.rag_embedding_provider,
        "llm_http_max_connections": int(settings.llm_http_max_connections),
    }


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> list[ConversationOut]:
    uid = _user_scope(user, settings)
    conversations = await crud.list_conversations(db, user_id=uid)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict[str, bool]:
    uid = _user_scope(user, settings)
    ok = await crud.delete_conversation(db, conversation_id, user_id=uid)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_conversation_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> list[MessageOut]:
    uid = _user_scope(user, settings)
    conversation = await crud.get_conversation(db, conversation_id, user_id=uid)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await crud.list_messages(db, conversation_id)
    return [MessageOut.model_validate(m) for m in messages]


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> list[DocumentOut]:
    documents = await crud.list_documents(
        db, user_id=_user_scope(user, settings)
    )
    return [DocumentOut.model_validate(d) for d in documents]


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict[str, bool]:
    document = await crud.delete_document(
        db, document_id, user_id=_user_scope(user, settings)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在或无权访问")
    await db.commit()
    return {"ok": True}


async def _maybe_graph_extract(doc_id: int, title: str, content: str, settings: Settings) -> None:
    """P4 hook: never raise into HTTP handlers."""
    try:
        from app.rag.graph_extract import maybe_extract_after_learn

        await maybe_extract_after_learn(doc_id, title, content, settings=settings)
    except Exception:  # noqa: BLE001
        return


async def _maybe_faq_extract(
    doc_id: int,
    title: str,
    content: str,
    settings: Settings,
    user_id: int | None = None,
) -> None:
    """T8-3 hook: auto FAQ companion doc; never raise into HTTP handlers."""
    try:
        from app.rag.faq_extract import maybe_extract_faq_after_learn

        await maybe_extract_faq_after_learn(
            doc_id, title, content, settings=settings, user_id=user_id
        )
    except Exception:  # noqa: BLE001
        return


@router.post("/documents", response_model=DocumentOut)
async def create_document(
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> DocumentOut:
    try:
        validate_content_length(payload.content, settings.doc_max_chars)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    uid = _user_scope(user, settings)
    document = await crud.create_document(
        db, payload.title, payload.content, user_id=uid
    )
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(
        document.id, document.title, document.content, settings, user_id=uid
    )
    return DocumentOut.model_validate(document)


@router.post("/knowledge/learn", response_model=DocumentOut)
async def learn_knowledge(
    payload: KnowledgeLearnRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> DocumentOut:
    try:
        validate_content_length(payload.content, settings.doc_max_chars)
    except IngestLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    uid = _user_scope(user, settings)
    document = await crud.create_document(
        db, payload.title, payload.content, user_id=uid
    )
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(
        document.id, document.title, document.content, settings, user_id=uid
    )
    return DocumentOut.model_validate(document)


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    query: str,
    top_k: int = 3,
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> KnowledgeSearchResponse:
    service = KnowledgeService()
    hits = await service.search(query, top_k=top_k, user_id=_user_scope(user, settings))
    return KnowledgeSearchResponse(query=query, results=hits, count=len(hits))


@router.post("/knowledge/reindex")
async def reindex_knowledge(
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    """Rebuild local dense vector index (no-op path if vector retrieval disabled)."""
    import asyncio
    import logging

    from app.db import crud
    from app.db.session import get_session_maker
    from app.rag.vector_index import (
        build_index_from_settings,
        index_scope_key,
        mark_vector_index_dirty,
    )

    if not bool(getattr(settings, "rag_vector_enabled", False)):
        return {
            "ok": False,
            "reason": "rag_vector_enabled=false",
            "hint": "Set RAG_VECTOR_ENABLED=true then retry",
        }

    uid = _user_scope(user, settings)
    # Defensive: treat sentinel / invalid ids as shared (auth-off path).
    index_uid = uid if (uid is not None and int(uid) > 0) else None
    scope = index_scope_key(index_uid)
    mark_vector_index_dirty(user_id=index_uid)
    session_maker = get_session_maker()
    async with session_maker() as db:
        documents = await crud.list_documents(
            db,
            limit=int(settings.rag_scan_limit),
            user_id=uid,
        )
    index = build_index_from_settings(settings, user_id=index_uid)
    try:
        # Embedding + JSON I/O are synchronous; keep them off the event loop.
        await asyncio.to_thread(
            index.ensure,
            documents,
            chunk_size=int(settings.rag_chunk_size),
            overlap=int(settings.rag_chunk_overlap),
            max_chunks=int(settings.rag_max_chunks_per_doc),
            force=True,
        )
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "vector reindex failed scope=%s docs=%s", scope, len(documents)
        )
        raise HTTPException(
            status_code=503,
            detail="Vector index rebuild unavailable; retry later or check server logs",
        ) from exc
    return {
        "ok": True,
        "documents": len(documents),
        "scope": scope,
        "retrieval": "dense+sparse-hybrid",
        "embedding": getattr(settings, "rag_embedding_provider", "hash"),
        "vector_backend": "local-vector-index",
    }


@router.get("/knowledge/retrieval-meta")
async def retrieval_meta(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "retrieval": (
            "dense+sparse-hybrid"
            if bool(getattr(settings, "rag_vector_enabled", False))
            else "sparse-tfidf-hybrid"
        ),
        "fusion": "weighted-dense+lexical",
        "sparse": "lexical+TF-IDF",
        "dense": getattr(settings, "rag_embedding_provider", "hash"),
        "vector_enabled": bool(getattr(settings, "rag_vector_enabled", False)),
        "graph_enabled": bool(getattr(settings, "rag_graph_enabled", False)),
        "rerank_enabled": bool(getattr(settings, "rag_rerank_enabled", False)),
        "vector_backend": "local-vector-index",
    }


@router.get("/knowledge/graph")
async def search_knowledge_graph(
    query: str,
    hops: int = 1,
    top_k: int = 6,
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    """P4: optional subgraph search; disabled → status=graph_disabled."""
    if settings.atlas_user_auth:
        return {
            "status": "graph_disabled",
            "reason": "graph_not_scoped_for_private_knowledge",
        }
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
    user: Optional[User] = Depends(get_current_user),
) -> DocumentOut:
    uid = _user_scope(user, settings)
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

    # zip：展开为多份知识文档，并返回汇总条目
    if ext == ".zip":
        try:
            members = extract_zip_members(data)
        except IngestLimitError as exc:
            stored_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not members:
            stored_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail="zip 内没有可解析文件（支持 PDF/Word/txt/md/图片等）",
            )
        created = []
        index_lines = [f"来自压缩包《{Path(filename).stem}》，共 {len(members)} 个文件："]
        for member_name, payload in members:
            body = extract_text_from_bytes(member_name, payload)
            if caption.strip():
                body = f"用户说明：{caption.strip()}\n\n{body}"
            if is_weak_extraction(body) and not caption.strip():
                index_lines.append(f"- {member_name}（跳过：未能提取有效文字）")
                continue
            try:
                validate_content_length(body, settings.doc_max_chars)
            except IngestLimitError:
                index_lines.append(f"- {member_name}（跳过：过长）")
                continue
            member_path = upload_dir / f"{uuid4().hex}_{safe_filename(member_name)}"
            member_path.write_bytes(payload)
            child = await crud.create_document(
                db,
                (Path(member_name).stem)[:200],
                body,
                source_type=detect_source_type(member_name),
                file_path=str(member_path),
                user_id=uid,
            )
            created.append(child)
            index_lines.append(f"- {member_name} → document_id={child.id}")
            await _maybe_graph_extract(child.id, child.title, child.content, settings)
            await _maybe_faq_extract(
                child.id, child.title, child.content, settings, user_id=uid
            )

        if not created:
            stored_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail="zip 内文件均未能提取有效文字，请检查内容后重试。",
            )

        summary = "\n".join(index_lines)
        doc_title = (title.strip() or f"压缩包：{Path(filename).stem}")[:200]
        document = await crud.create_document(
            db,
            doc_title,
            summary,
            source_type="zip",
            file_path=str(stored_path),
            user_id=uid,
        )
        await db.commit()
        await db.refresh(document)
        return DocumentOut.model_validate(document)

    extracted = extract_text_from_bytes(filename, data)
    if caption.strip():
        extracted = f"用户说明：{caption.strip()}\n\n{extracted}"
    # 解析失败/扫描件无字：直接报错，避免「导入成功但答不上」
    if is_weak_extraction(extracted) and not caption.strip():
        stored_path.unlink(missing_ok=True)
        hint = (extracted or "").strip() or "未能从文件中提取有效文字"
        raise HTTPException(
            status_code=422,
            detail=(
                f"{hint}\n"
                "建议：① 使用可复制文本的 PDF/Word(.docx)；"
                "② 图片/扫描件请确保本机 Tesseract 中文包可用；"
                "③ 或在「说明」里粘贴正文后再导入。"
            ),
        )
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
        user_id=uid,
    )
    await db.commit()
    await db.refresh(document)
    await _maybe_graph_extract(document.id, document.title, document.content, settings)
    await _maybe_faq_extract(
        document.id, document.title, document.content, settings, user_id=uid
    )
    return DocumentOut.model_validate(document)


@router.post("/chat")
async def chat(
    req: ChatRequest,
    settings: Settings = Depends(get_settings),
    user: Optional[User] = Depends(get_current_user),
):
    # Must resolve user scope before concurrency key (was NameError → HTTP 500)
    uid = _user_scope(user, settings)
    user_key = (
        str(uid)
        if uid is not None
        else (f"anon:{id(req)}" if not settings.atlas_user_auth else "anon")
    )
    # P2: 公平并发 — 全站上限 + 每用户上限；超额排队；槽位持有至 SSE 结束
    if not await acquire_chat_slot(
        settings.max_concurrent_chats,
        wait_seconds=float(settings.chat_queue_wait_seconds),
        user_key=user_key,
        per_user_limit=int(settings.max_chats_per_user),
    ):
        raise HTTPException(
            status_code=429,
            detail=(
                f"当前使用人数较多（全站≤{settings.max_concurrent_chats}路，"
                f"每账号≤{settings.max_chats_per_user}路），请稍后再试"
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
                user_id=uid,
                document_ids=req.document_ids,
            ):
                event_type = event.get("type", "message")
                if event_type == "token":
                    piece = sanitize_assistant_text(event.get("content", "") or "")
                    if not piece and looks_like_tool_leak(event.get("content", "") or ""):
                        continue
                    if piece != (event.get("content") or ""):
                        event = {**event, "content": piece}
                    if piece:
                        assistant_text += piece
                    else:
                        continue
                elif event_type == "done":
                    done_mode = event.get("mode", done_mode)
                    # Prefer sanitized final answer from agent when provided
                    if event.get("answer"):
                        cleaned = sanitize_assistant_text(str(event.get("answer") or ""))
                        if cleaned:
                            assistant_text = cleaned
                    continue
                yield {
                    "event": event_type,
                    "data": json.dumps(event, ensure_ascii=False),
                }

            assistant_text = sanitize_assistant_text(assistant_text) or assistant_text
            if looks_like_tool_leak(assistant_text):
                assistant_text = sanitize_assistant_text(assistant_text) or (
                    "当前无法基于知识库可靠作答，请换个问法或补充相关文档后再试。"
                )

            session_maker = get_session_maker()
            async with session_maker() as db:
                if conversation_id is None:
                    title = (user_message[:50] or "新对话").strip()
                    conversation = await crud.create_conversation(
                        db, title, user_id=uid
                    )
                    conversation_id = conversation.id
                else:
                    conversation = await crud.get_conversation(
                        db, conversation_id, user_id=uid
                    )
                    if conversation is None:
                        yield {
                            "event": "error",
                            "data": json.dumps(
                                {"type": "error", "content": "会话不存在或无权访问"},
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
