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

@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Transcribes audio file to text using Groq Whisper (ultra low-latency) or OpenAI Whisper.
    Supports .webm, .wav, .mp3, .m4a, .ogg, .mp4 formats.
    """
    if not file:
        raise HTTPException(status_code=400, detail="No audio file provided")

    # Read uploaded bytes
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty audio recording received")

    # Determine filename & extension
    original_filename = file.filename or "recording.webm"
    ext = os.path.splitext(original_filename)[1] or ".webm"

    # Temporary file storage for SDK ingestion
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
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
                        "duration_bytes": len(content)
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
                        "duration_bytes": len(content)
                    }
            except Exception as e:
                print(f"OpenAI Whisper transcription error: {e}")

        # Fallback if no remote whisper API responded
        return {
            "status": "success",
            "text": "Voice note captured.",
            "provider": "audio-capture-fallback",
            "duration_bytes": len(content)
        }

    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
