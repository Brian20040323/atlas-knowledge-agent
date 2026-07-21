# Atlas Knowledge Agent 鈥?lightweight deployment image
# Full-featured: pass BUILD_VARIANT=full for TTS/STT support
ARG BUILD_VARIANT=lite
FROM python:3.11-slim

WORKDIR /app

# System deps for document parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Backend dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: full variant with TTS/STT (needs 2GB+ RAM)
# RUN if [ "$BUILD_VARIANT" = "full" ]; then \
#     pip install --no-cache-dir faster-whisper coqui-tts pypinyin soundfile; \
#     fi

# Application
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY run.py .
COPY .env.example .

# Data directory (mounted as volume in production)
RUN mkdir -p data/uploads data/voice data/vector_index

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["python", "run.py"]
