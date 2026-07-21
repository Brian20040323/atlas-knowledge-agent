"""Local speech-to-text via faster-whisper (no Google cloud dependency)."""

from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR, Settings

_model_lock = threading.Lock()
_model: Any = None
_model_error: str | None = None


def _whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def stt_status(settings: Settings | None = None) -> dict[str, Any]:
    ready = _whisper_available()
    return {
        "provider": "whisper" if ready else "none",
        "ready": ready,
        "hint": (
            "已启用本地语音识别（Whisper）"
            if ready
            else "未安装 faster-whisper，麦克风将无法本地识别"
        ),
    }


def _get_model():
    global _model, _model_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        if _model_error:
            raise RuntimeError(_model_error)
        try:
            from faster_whisper import WhisperModel

            # base + int8: decent Chinese accuracy on CPU without huge RAM
            _model = WhisperModel("base", device="cpu", compute_type="int8")
        except Exception as exc:  # noqa: BLE001
            _model_error = f"Whisper 加载失败: {exc}"
            raise RuntimeError(_model_error) from exc
        return _model


def _ensure_ffmpeg_on_path() -> None:
    try:
        import imageio_ffmpeg
        import os

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        bin_dir = str(Path(ffmpeg).parent)
        path = os.environ.get("PATH", "")
        if bin_dir not in path:
            os.environ["PATH"] = bin_dir + os.pathsep + path
    except Exception:
        pass


def _transcribe_file(path: Path) -> str:
    _ensure_ffmpeg_on_path()
    model = _get_model()
    segments, _info = model.transcribe(
        str(path),
        language="zh",
        vad_filter=True,
        beam_size=1,
        best_of=1,
    )
    parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    text = "".join(parts).strip()
    # Whisper sometimes inserts spaces between Chinese chars
    text = text.replace(" ", "")
    return text


async def transcribe_audio_bytes(data: bytes, suffix: str = ".webm") -> str:
    if not data or len(data) < 200:
        raise ValueError("录音太短，请多说一两秒再松手")
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    tmp_dir = ROOT_DIR / "data" / "voice" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(tmp_dir)) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        text = await asyncio.to_thread(_transcribe_file, path)
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    if not text:
        raise ValueError("没有识别到有效语音，请靠近麦克风再说一次")
    return text
