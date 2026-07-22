from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    use_tools: bool = True
    deep_think: bool = False
    conversation_id: Optional[int] = None
    # Composer 附件：优先从这些知识库文档取证（不改变全局库，仅本轮加权）
    document_ids: Optional[List[int]] = None


class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=100)
    invite_code: str = Field(default="", max_length=64)


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str


class AuthMeResponse(BaseModel):
    auth_required: bool
    user: Optional[UserOut] = None
    register_open: bool = True



class HealthResponse(BaseModel):
    status: str
    mode: str
    model: str
    model_complex: str = ""
    tts_provider: str = "browser"
    tts_ready: bool = False
    stt_provider: str = "none"
    stt_ready: bool = False
    mcp_enabled: bool = False
    mcp_servers: int = 0


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    created_at: datetime
    source_type: Optional[str] = "text"
    file_path: Optional[str] = ""


class KnowledgeLearnRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)


class KnowledgeHit(BaseModel):
    id: int
    title: str
    excerpt: str
    score: float
    content: Optional[str] = None


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: List[KnowledgeHit]
    count: int
