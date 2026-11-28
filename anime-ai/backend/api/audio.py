import os
import io
import tempfile
import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

from database.db import get_db
from database.models import User
from auth.manager import AuthManager

router = APIRouter(prefix="/audio", tags=["audio"])

MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (Whisper upstream hard cap)
ALLOWED_AUDIO_EXTENSIONS = frozenset({
    ".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mp4", ".flac", ".mpeg", ".mpga"
})


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transcribes audio file to text using Groq Whisper (ultra low-latency) or OpenAI Whisper.
    Supports .webm, .wav, .mp3, .m4a, .ogg, .mp4, .flac, .mpeg, .mpga formats (max 25 MB).
    """
    if not file:
        raise HTTPException(status_code=400, detail="No audio file provided")

    # Sanitize filename strictly against path separators / traversal and allowlist extension
    raw_filename = (file.filename or "recording.webm").replace("\\", "/")
    safe_basename = os.path.basename(raw_filename.strip()) or "recording.webm"
    ext = (os.path.splitext(safe_basename)[1] or ".webm").lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio file extension '{ext}'.",
        )

    # Stream upload directly to a bounded temporary file (prevents unbounded RAM DoS)
    total_bytes = 0
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_AUDIO_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Audio file exceeds maximum allowed size of 25MB.",
                    )
                tmp.write(chunk)

        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Empty audio recording received")

        # Priority 1: Groq Whisper (super-fast)
        groq_key = os.getenv("GROQ_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        if groq_key:
            try:
                groq_client = AsyncOpenAI(
                    api_key=groq_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                with open(tmp_path, "rb") as audio_f:
                    transcription = await groq_client.audio.transcriptions.create(
                        file=audio_f,
                        model="whisper-large-v3",
                        response_format="json",
                        temperature=0.0
                    )
                text = transcription.text if hasattr(transcription, "text") else str(transcription)
                if text and text.strip():
                    return {
                        "status": "success",
                        "text": text.strip(),
                        "provider": "groq-whisper-large-v3",
                        "duration_bytes": total_bytes
                    }
            except Exception as e:
                print(f"Groq Whisper transcription error: {e}")

        # Priority 2: OpenAI Whisper
        if openai_key:
            try:
                openai_client = AsyncOpenAI(api_key=openai_key)
                with open(tmp_path, "rb") as audio_f:
                    transcription = await openai_client.audio.transcriptions.create(
                        file=audio_f,
                        model="whisper-1",
                        response_format="json",
                        temperature=0.0
                    )
                text = transcription.text if hasattr(transcription, "text") else str(transcription)
                if text and text.strip():
                    return {
                        "status": "success",
                        "text": text.strip(),
                        "provider": "openai-whisper-1",
                        "duration_bytes": total_bytes
                    }
            except Exception as e:
                print(f"OpenAI Whisper transcription error: {e}")

        # Honest failure if neither Whisper provider is configured or succeeded
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice transcription is unavailable because audio processing models are not configured on this server."
        )

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
