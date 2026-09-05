"""
Sakura AI — System Capabilities & Live Telemetry Endpoint
Exposes truthful live operational status across sandbox isolation, embeddings,
audio transcription, GitHub integrations, web search, image generation, and configured LLM providers.
Never returns hard-coded fake "Active" statuses.
"""
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User, UserIntegration
from auth.manager import AuthManager
from coding.sandbox import SandboxManager
from services.web_search import get_web_search_status

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=Dict[str, Any])
@router.get("/", response_model=Dict[str, Any])
async def get_system_capabilities(
    current_user: Optional[User] = Depends(AuthManager.get_optional_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns live system capabilities and operational flags.
    Allows frontend clients to accurately render capabilities, active badges, and fallbacks.
    """
    from api.routes import llm_router
    from realtime.manager import ws_manager

    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")
    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    environment = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()

    # 1. Sandbox diagnostics
    sandbox_status = SandboxManager.get_status()
    is_production = environment in ["production", "prod"]
    if sandbox_status.get("production_safe"):
        sandbox_subsystem_status = "AVAILABLE"
    elif not is_production:
        sandbox_subsystem_status = "DEGRADED"  # Local restricted sandbox in dev/test
    else:
        sandbox_subsystem_status = "UNAVAILABLE"

    # 2. Active LLM models
    available_providers = {}
    if llm_router and hasattr(llm_router, "providers"):
        for name, provider in llm_router.providers.items():
            available_providers[name] = {
                "active": True,
                "model": getattr(provider, "model", "default"),
                "class": provider.__class__.__name__
            }

    # 3. GitHub connectivity
    github_connected = False
    github_username = None
    if current_user:
        gh_integration = db.query(UserIntegration).filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == "github",
            UserIntegration.connected == True
        ).first()
        if gh_integration:
            github_connected = True
            github_username = gh_integration.account_name

    github_state = "CONNECTED" if github_connected else (
        "DISCONNECTED" if (github_client_id and github_client_secret) or os.getenv("GITHUB_TOKEN") else "NOT_CONFIGURED"
    )

    # 4. Web search diagnostics
    search_info = get_web_search_status()

    # 5. Audio diagnostics
    audio_available = bool(groq_key or openai_key)

    # 6. Embeddings diagnostics
    embeddings_configured = bool(openai_key)
    rag_status = "AVAILABLE" if embeddings_configured else "DEGRADED"

    # 7. Image generation diagnostics
    if openai_key:
        image_gen_status = "AVAILABLE"
        image_provider = "openai"
        image_model = "dall-e-3"
    elif not is_production:
        image_gen_status = "DEGRADED"
        image_provider = "pollinations-flux"
        image_model = "flux-schnell"
    else:
        image_gen_status = "NOT_CONFIGURED"
        image_provider = None
        image_model = None

    # 8. Subsystems map for PluginsView
    subsystems = {
        "sakura_code": {
            "status": sandbox_subsystem_status,
            "isolation_level": sandbox_status.get("isolation_level"),
            "production_safe": sandbox_status.get("production_safe"),
            "verified_sandbox": bool(sandbox_status.get("production_safe"))
        },
        "image_gen": {
            "status": image_gen_status,
            "provider": image_provider,
            "model": image_model,
            "editing_available": False,
            "upscale_available": False
        },
        "rag_engine": {
            "status": rag_status,
            "dense_embeddings": embeddings_configured,
            "lexical_bm25": True,
            "retrieval_mode": "hybrid_rrf" if embeddings_configured else "okapi_bm25_lexical"
        },
        "web_search": {
            "status": search_info["status"],
            "provider": search_info["provider"],
            "has_api_key": search_info["has_api_key"]
        },
        "audio_tts": {
            "status": "AVAILABLE" if audio_available else "UNAVAILABLE",
            "whisper_provider": "groq" if groq_key else ("openai" if openai_key else None)
        }
    }

    return {
        "status": "operational",
        "environment": environment,
        "sandbox": sandbox_status,
        "embeddings": {
            "configured": embeddings_configured,
            "model": "text-embedding-3-small",
            "provider": "openai" if openai_key else None,
            "hybrid_search_fallback": "keyword_bm25"
        },
        "audio": {
            "whisper_available": audio_available,
            "groq_whisper": bool(groq_key),
            "openai_whisper": bool(openai_key),
            "status": "AVAILABLE" if audio_available else "UNAVAILABLE"
        },
        "github": {
            "state": github_state,
            "oauth_configured": bool(github_client_id and github_client_secret),
            "user_connected": github_connected,
            "username": github_username
        },
        "web_search": search_info,
        "image_generation": {
            "available": image_gen_status in ("AVAILABLE", "DEGRADED"),
            "provider": image_provider,
            "model": image_model,
            "editing_available": False,
            "upscale_available": False,
            "status": image_gen_status
        },
        "realtime": await ws_manager.get_status(),
        "providers": available_providers,
        "subsystems": subsystems
    }
