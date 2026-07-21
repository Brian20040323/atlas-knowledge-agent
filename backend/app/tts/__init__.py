"""Custom voice TTS — local XTTS clone (preferred) or ElevenLabs."""

from __future__ import annotations

import asyncio
import io
import os
import threading
from pathlib import Path
from typing import Any

import httpx

from app.config import ROOT_DIR, Settings

_xtts_lock = threading.Lock()
_xtts_model: Any = None
_xtts_error: str | None = None


def default_voice_sample() -> Path:
    return ROOT_DIR / "data" / "voice" / "clone_sample.wav"


def preferred_voice_ref() -> Path:
    return ROOT_DIR / "data" / "voice" / "clone_ref.wav"


def resolve_voice_sample(settings: Settings) -> Path | None:
    raw = (settings.tts_voice_sample or "").strip()
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        candidates.append(p if p.is_absolute() else ROOT_DIR / p)
    # Prefer trimmed/normalized ref for better clone quality
    candidates.append(preferred_voice_ref())
    candidates.append(default_voice_sample())
    for path in candidates:
        if path.is_file() and path.stat().st_size > 1000:
            return path
    return None


def prepare_voice_ref(source: Path | None = None) -> Path | None:
    """Build a cleaned ~8–12s reference clip for XTTS from the full sample."""
    try:
        import numpy as np
        import soundfile as sf
    except Exception:
        return None

    src = source or default_voice_sample()
    if not src.is_file():
        return None
    mono, sr = sf.read(str(src))
    if getattr(mono, "ndim", 1) > 1:
        mono = mono.mean(axis=1)
    mono = np.asarray(mono, dtype=np.float32)
    if len(mono) < int(0.8 * sr):
        return None

    # High-pass ~80Hz (simple first-order) to cut rumble
    rc = 1.0 / (2 * np.pi * 80.0)
    dt = 1.0 / float(sr)
    alpha = rc / (rc + dt)
    y = np.empty_like(mono)
    y[0] = mono[0]
    for i in range(1, len(mono)):
        y[i] = alpha * (y[i - 1] + mono[i] - mono[i - 1])
    mono = y

    # Soft noise gate on quiet frames
    frame = max(1, int(0.02 * sr))
    gated = mono.copy()
    for i in range(0, len(mono) - frame, frame):
        seg = mono[i : i + frame]
        rms = float(np.sqrt(np.mean(seg**2)))
        if rms < 0.008:
            gated[i : i + frame] *= 0.15
    mono = gated

    # Pick best ~10s by speech energy
    rms = np.array(
        [float(np.sqrt(np.mean(mono[i : i + frame] ** 2))) for i in range(0, len(mono) - frame, frame)]
    )
    thr = max(0.012, float(np.percentile(rms, 55))) if len(rms) else 0.012
    win = int(10 * sr)
    hop = int(0.4 * sr)
    best_score, best_i = -1.0, 0
    upper = max(1, len(mono) - win)
    for i in range(0, upper, hop):
        seg = mono[i : i + win]
        energy = float(np.mean(seg**2))
        fr = np.array(
            [
                float(np.sqrt(np.mean(seg[j : j + frame] ** 2)))
                for j in range(0, len(seg) - frame, frame)
            ]
        )
        ratio = float(np.mean(fr > thr)) if len(fr) else 0.0
        score = energy * (0.2 + 0.8 * ratio)
        if score > best_score:
            best_score, best_i = score, i
    seg = mono[best_i : best_i + min(win, len(mono) - best_i)]

    # Peak normalize + gentle soft clip
    peak = float(np.max(np.abs(seg))) + 1e-8
    seg = seg * (0.82 / peak)
    seg = np.tanh(seg * 1.15).astype(np.float32) * 0.9

    out = preferred_voice_ref()
    out.parent.mkdir(parents=True, exist_ok=True)
    # XTTS likes 22050
    if sr != 22050:
        # linear resample
        duration = len(seg) / float(sr)
        new_len = int(duration * 22050)
        x_old = np.linspace(0.0, 1.0, num=len(seg), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        seg = np.interp(x_new, x_old, seg).astype(np.float32)
        sr = 22050
    sf.write(str(out), seg, sr)
    return out


async def ingest_voice_sample(data: bytes, filename: str = "sample.wav") -> Path:
    """Save uploaded voice sample, convert to wav, rebuild clone_ref."""
    import asyncio

    voice_dir = ROOT_DIR / "data" / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".wav"
    raw_path = voice_dir / f"upload_raw{suffix}"
    raw_path.write_bytes(data)

    sample = default_voice_sample()

    def _convert() -> None:
        # Prefer soundfile; fall back to imageio-ffmpeg for m4a/mp3
        try:
            import soundfile as sf
            import numpy as np

            audio, sr = sf.read(str(raw_path))
            if getattr(audio, "ndim", 1) > 1:
                audio = audio.mean(axis=1)
            sf.write(str(sample), np.asarray(audio, dtype=np.float32), sr)
            return
        except Exception:
            pass
        try:
            import imageio_ffmpeg
            import subprocess

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [ffmpeg, "-y", "-i", str(raw_path), "-ac", "1", "-ar", "22050", str(sample)],
                check=True,
                capture_output=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"无法解析音频文件：{exc}") from exc

    await asyncio.to_thread(_convert)
    ref = await asyncio.to_thread(prepare_voice_ref, sample)
    if ref is None:
        raise ValueError("音频过短或无效，请录 10–30 秒清晰中文")
    return ref


def _coqui_available() -> bool:
    try:
        import TTS  # noqa: F401

        return True
    except Exception:
        return False


def tts_status(settings: Settings) -> dict[str, Any]:
    provider = (settings.tts_provider or "auto").strip().lower()
    sample = resolve_voice_sample(settings)
    has_local = sample is not None and _coqui_available() and provider in {"auto", "local"}
    has_eleven = (
        provider in {"elevenlabs", "auto"}
        and bool(settings.elevenlabs_api_key.strip())
        and bool(settings.elevenlabs_voice_id.strip())
    )

    if has_local:
        return {
            "provider": "local",
            "ready": True,
            "media_type": "audio/wav",
            "sample": str(sample),
            "hint": f"已启用本地音色克隆（XTTS）：{sample.name}",
        }
    if has_eleven:
        return {
            "provider": "elevenlabs",
            "ready": True,
            "media_type": "audio/mpeg",
            "sample": None,
            "hint": "已启用自定义音色（ElevenLabs）",
        }
    if sample is not None and not _coqui_available():
        hint = "已找到声音样本，但未安装本地 TTS（coqui-tts）。也可改用 ElevenLabs。"
    elif sample is None:
        hint = "未找到声音样本：请放入 data/voice/clone_sample.wav，或配置 ElevenLabs。"
    else:
        hint = "自定义音色未启用（TTS_PROVIDER=browser）"
    return {
        "provider": "browser",
        "ready": False,
        "media_type": None,
        "sample": str(sample) if sample else None,
        "hint": hint,
    }


def _get_xtts():
    global _xtts_model, _xtts_error
    if _xtts_model is not None:
        return _xtts_model
    with _xtts_lock:
        if _xtts_model is not None:
            return _xtts_model
        if _xtts_error:
            raise RuntimeError(_xtts_error)
        try:
            os.environ.setdefault("COQUI_TOS_AGREED", "1")
            from TTS.api import TTS

            _xtts_model = TTS(
                "tts_models/multilingual/multi-dataset/xtts_v2",
                gpu=False,
            )
        except Exception as exc:  # noqa: BLE001
            _xtts_error = f"本地 XTTS 加载失败: {exc}"
            raise RuntimeError(_xtts_error) from exc
        return _xtts_model


def _synthesize_local(text: str, sample: Path) -> bytes:
    tts = _get_xtts()
    # XTTS returns list[float] waveform at 24kHz
    wav = tts.tts(text=text, speaker_wav=str(sample), language="zh")
    import numpy as np
    import soundfile as sf

    arr = np.asarray(wav, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, arr, 24000, format="WAV")
    return buf.getvalue()


async def _synthesize_elevenlabs(text: str, settings: Settings) -> bytes:
    voice_id = settings.elevenlabs_voice_id.strip()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key.strip(),
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model or "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
        },
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ValueError(f"ElevenLabs TTS 失败 ({resp.status_code}): {resp.text[:300]}")
        return resp.content


async def synthesize_speech(text: str, settings: Settings) -> tuple[bytes, str]:
    """Return (audio_bytes, media_type). Raises ValueError if not configured."""
    status = tts_status(settings)
    if not status["ready"]:
        raise ValueError(status["hint"])

    clean = (text or "").strip()
    if not clean:
        raise ValueError("朗读文本为空")

    provider = status["provider"]
    if provider == "local":
        clean = clean[:600]
        sample = resolve_voice_sample(settings)
        if sample is None:
            raise ValueError("声音样本不存在")
        audio = await asyncio.to_thread(_synthesize_local, clean, sample)
        return audio, "audio/wav"

    clean = clean[:1200]
    audio = await _synthesize_elevenlabs(clean, settings)
    return audio, "audio/mpeg"
