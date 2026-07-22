from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    # 默认便宜模型；复杂通用题 / 细想 / 联网摘要可升到 llm_model_complex
    llm_model: str = "deepseek-v4-flash"
    llm_model_complex: str = "deepseek-v4-pro"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = ""  # comma-separated origins; empty means same-origin only
    mock_mode: str = "auto"  # auto | true | false
    database_url: str = ""
    # 公网访问口令；非空时启用站点门禁（cookie）。局域网调试可留空。
    atlas_public_password: str = ""
    # 多人账号隔离：开启后必须注册/登录，会话按用户隔离
    atlas_user_auth: bool = True
    # 注册邀请码；非空时注册必须填写该码（防止公网随便开号）
    atlas_register_secret: str = ""

    # Custom voice TTS: local XTTS (data/voice/clone_sample.wav) or ElevenLabs
    tts_provider: str = "auto"  # auto | local | elevenlabs | browser
    tts_voice_sample: str = ""  # optional path; default data/voice/clone_sample.wav
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"

    # MCP: export Atlas tools via scripts/mcp_server.py; optionally import external MCP tools
    mcp_enabled: bool = False
    # JSON list or Cursor-style map, e.g.
    # [{"name":"fs","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","."]}]
    mcp_servers: str = ""

    # ---------- RAG / 资源上限（P1 质量门禁，默认无高占用）----------
    upload_max_mb: int = 20  # 单文件上传上限（Office/PDF/图片）
    doc_max_chars: int = 200_000  # 单文档入库字符上限
    rag_scan_limit: int = 200  # 单次检索最多扫描文档数
    rag_top_k_max: int = 8  # 单次返回 Top-K 硬顶
    rag_max_chunks_per_doc: int = 48  # 单文档参与打分的块数上限
    rag_chunk_size: int = 280
    rag_chunk_overlap: int = 40
    agent_max_steps: int = 4  # ReAct 工具循环步数上限

    # ---------- 可观测与限流（P2）----------
    http_timeout_web: float = 12.0  # DuckDuckGo / 网页搜索超时（秒）
    http_timeout_research: float = 6.0  # Wiki / research HTTP 超时（秒）
    llm_timeout_seconds: float = 90.0  # LLM HTTP 超时（秒）
    max_concurrent_chats: int = 20  # 全站同时生成上限（多人共享）
    max_chats_per_user: int = 2  # 同一账号同时生成上限，避免一人占满
    chat_queue_wait_seconds: float = 45.0  # 满载时排队等待后再 429
    llm_http_max_connections: int = 24  # 出站 LLM 连接池上限
    web_circuit_fail_threshold: int = 2  # 本轮连续外网失败达 N 次后熔断，仅本地 L1
    trace_max_recent: int = 40  # 内存中保留的最近 Trace 条数

    # ---------- 可选向量检索（P3，默认关闭 → TF-IDF）----------
    rag_vector_enabled: bool = False  # true 时启用 embedding + 本地向量索引
    rag_embedding_provider: str = "hash"  # hash | fastembed（本地神经向量）| openai（远程 API）
    rag_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rag_embedding_dim: int = 512  # bge-small-zh=512；MiniLM=384；openai 以返回维为准
    rag_vector_index_dir: str = "data/vector_index"  # 相对仓库根目录
    rag_lexical_weight: float = 0.55  # 向量模式下 lexical 权重
    rag_vector_weight: float = 0.45  # 向量模式下 embedding 余弦权重

    # ---------- 可选 LLM Rerank（T8-2，默认关；评测保持快路径）----------
    rag_rerank_enabled: bool = False  # true 时对召回候选做 LLM 精排
    rag_rerank_candidates: int = 12  # 召回后再精排的候选数（≥ top_k）
    rag_rerank_model: str = "deepseek-v4-pro"  # 精排模型；空则回退 llm_model
    rag_rerank_timeout_seconds: float = 20.0

    # ---------- 入库自动抽 FAQ（T8-3，有 LLM 时默认开）----------
    rag_faq_extract_on_learn: bool = False
    rag_faq_model: str = "deepseek-v4-pro"
    rag_faq_max_pairs: int = 6

    # ---------- 可选知识图谱（P4，默认关闭；失败不影响文档 RAG）----------
    rag_graph_enabled: bool = False  # 总开关：关则不抽取、不查询
    rag_graph_extract_on_learn: bool = True  # 仅当 enabled 时：入库后规则抽取
    rag_graph_max_entities_per_doc: int = 32
    rag_graph_max_relations_per_doc: int = 48
    rag_graph_min_confidence: float = 0.5
    rag_graph_hops: int = 1  # 子图默认跳数
    rag_graph_schema_version: int = 1

    @property
    def db_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        db_path = (ROOT_DIR / "data" / "app.db").as_posix()
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def use_mock(self) -> bool:
        mode = self.mock_mode.strip().lower()
        if mode in {"true", "1", "yes"}:
            return True
        if mode in {"false", "0", "no"}:
            return False
        return not bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
