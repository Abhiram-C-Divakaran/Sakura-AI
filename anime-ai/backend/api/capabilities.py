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
from sqlalchemy import text

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

    # 2. Active LLM models with truthful configuration status
    available_providers = {}
    has_configured_provider = False
    if llm_router and hasattr(llm_router, "providers"):
        for name, provider in llm_router.providers.items():
            if name == "groq":
                configured = bool(groq_key)
            elif name == "openai":
                configured = bool(openai_key)
            elif name == "anthropic":
                configured = bool(anthropic_key)
            elif name == "ollama":
                configured = bool(os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_MODEL"))
            else:
                configured = False

            if configured:
                has_configured_provider = True

            telem = getattr(llm_router, "provider_telemetry", {}).get(name, {})
            last_verified = telem.get("last_verified_at")
            is_healthy = telem.get("healthy", None)

            if not configured:
                prov_status = "NOT_CONFIGURED"
            elif is_healthy is True:
                prov_status = "AVAILABLE"
            elif is_healthy is False:
                prov_status = "UNAVAILABLE"
            else:
                prov_status = "CONFIGURED"

            available_providers[name] = {
                "implemented": True,
                "active": configured,
                "configured": configured,
                "healthy": is_healthy,
                "status": prov_status,
                "model": getattr(provider, "model", "default"),
                "class": provider.__class__.__name__,
                "last_verified_at": last_verified
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
        "DISCONNECTED" if (github_client_id and github_client_secret) else "NOT_CONFIGURED"
    )

    # 4. Web search diagnostics
    search_info = get_web_search_status()

    # 5. Audio diagnostics
    audio_available = bool(groq_key or openai_key)

    # 6. Embeddings diagnostics
    embeddings_configured = bool(openai_key)
    rag_status = "AVAILABLE" if embeddings_configured else "DEGRADED"

    # 7. Image generation diagnostics (runtime source of truth from ImageGenerationEngine)
    from media.image_engine import ImageGenerationEngine
    img_status = ImageGenerationEngine.get_status()
    image_gen_status = img_status.get("status", "UNKNOWN")
    image_provider = img_status.get("provider", "pollinations")
    image_model = img_status.get("models", ["flux"])[0]

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
            "models": img_status.get("models", ["flux", "turbo"]),
            "text_to_image": True,
            "editing_available": False,
            "upscale_available": False,
            "image_conditioned_edit": False,
            "true_upscale": False,
            "variations": True
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

    # Derive overall system status truthfully
    db_healthy = False
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False

    if not db_healthy:
        system_status = "NOT_READY"
    elif environment in ("test", "testing"):
        system_status = "OPERATIONAL"
    elif is_production and (
        not has_configured_provider
        or sandbox_subsystem_status in ("DEGRADED", "UNAVAILABLE")
        or image_gen_status in ("DEGRADED", "UNAVAILABLE", "UNKNOWN")
        or search_info["status"] in ("DEGRADED", "UNAVAILABLE")
    ):
        system_status = "DEGRADED"
    else:
        system_status = "OPERATIONAL"

    return {
        "status": system_status.lower(),
        "system_status": system_status,
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
            "status": image_gen_status,
            "provider": image_provider,
            "model": image_model,
            "models": img_status.get("models", ["flux", "turbo"]),
            "text_to_image": True,
            "editing_available": False,
            "upscale_available": False,
            "image_conditioned_edit": False,
            "true_upscale": False,
            "variations": True,
            "health_verified_at": img_status.get("health_verified_at")
        },
        "realtime": await ws_manager.get_status(),
        "providers": available_providers,
        "subsystems": subsystems
    }
