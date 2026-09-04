"""
Sakura AI — System Capabilities & Telemetry Endpoint

Exposes live operational status across sandbox isolation, embeddings,
audio transcription, GitHub integrations, web search, and configured LLM providers.
Truthful reporting: no fake active states.
"""
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User
from auth.manager import AuthManager
from coding.sandbox import SandboxManager

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


def _get_optional_user(
    token_user: Optional[User] = Depends(AuthManager.get_optional_current_user)
) -> Optional[User]:
    return token_user


@router.get("", response_model=Dict[str, Any])
@router.get("/", response_model=Dict[str, Any])
def get_system_capabilities(
    current_user: Optional[User] = Depends(AuthManager.get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns live system capabilities and operational flags.
    Allows frontend clients to accurately render capabilities, active badges, and fallbacks.
    """
    from api.routes import llm_router

    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")
    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")

    # Sandbox diagnostics
    sandbox_info = SandboxManager.get_status()

    # Active LLM models
    available_providers = {}
    if llm_router and hasattr(llm_router, "providers"):
        for name, provider in llm_router.providers.items():
            available_providers[name] = {
                "active": True,
                "model": getattr(provider, "model", "default"),
                "class": provider.__class__.__name__
            }

    # GitHub connectivity
    github_connected = False
    github_username = None
    if current_user and getattr(current_user, "github_token", None):
        github_connected = True
        github_username = getattr(current_user, "github_username", None)

    return {
        "status": "operational",
        "sandbox": sandbox_info,
        "embeddings": {
            "configured": bool(openai_key),
            "model": "text-embedding-3-small",
            "provider": "openai" if openai_key else None,
            "hybrid_search_fallback": "keyword_bm25"
        },
        "audio": {
            "whisper_available": bool(groq_key or openai_key),
            "groq_whisper": bool(groq_key),
            "openai_whisper": bool(openai_key)
        },
        "github": {
            "oauth_configured": bool(github_client_id and github_client_secret),
            "user_connected": github_connected,
            "username": github_username
        },
        "web_search": {
            "tavily_configured": bool(tavily_key),
            "engine": "tavily" if tavily_key else "duckduckgo_fallback"
        },
        "image_generation": {
            "available": bool(openai_key),
            "provider": "openai-dall-e-3" if openai_key else None
        },
        "providers": available_providers
    }
