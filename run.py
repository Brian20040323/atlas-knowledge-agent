"""One-command launcher: python run.py"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Ensure cwd-independent imports
os.chdir(ROOT)
# Coqui XTTS license acceptance for local voice clone
os.environ.setdefault("COQUI_TOS_AGREED", "1")


def main() -> None:
    import uvicorn
    from app.config import get_settings
    from app.tts import tts_status

    settings = get_settings()
    tts = tts_status(settings)
    print("=" * 56)
    print(" AI Fullstack Starter")
    print(f" mode : {'MOCK' if settings.use_mock else 'LLM'}")
    print(f" model: {settings.llm_model}")
    print(f" tts  : {tts['provider']} ready={tts['ready']}")
    print(f" url  : http://{settings.host}:{settings.port}")
    print("=" * 56)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        app_dir=str(BACKEND),
    )


if __name__ == "__main__":
    main()
