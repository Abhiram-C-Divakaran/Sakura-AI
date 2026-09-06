"""
Sakura AI — Unified Integrations API & Real GitHub Connection Architecture
Enforces real credential validation, independent secret encryption at rest, and canonical typed schemas.
Never marks integrations CONNECTED unless verified with a genuine third-party provider API.
Unsupported connectors explicitly return 501 Not Implemented and report NOT_CONFIGURED.
"""
from abc import ABC, abstractmethod
import os
import json
import uuid
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database.db import get_db
from database.models import User, UserIntegration, utc_now
from auth.manager import AuthManager
from auth.crypto import encrypt_secret, decrypt_secret, decrypt_and_upgrade_secret

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ─── Canonical Provider Adapter Architecture ─────────────────────────────────

class BaseIntegrationProvider(ABC):
    """Abstract interface for third-party service integration providers."""
    id: str
    name: str
    category: str
    description: str
    capabilities: List[str]
    is_implemented: bool = False

    @abstractmethod
    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Validates credentials against third-party API or raises HTTPException."""
        pass

    @abstractmethod
    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        """Extracts username / account name from third-party validation result."""
        pass

    @abstractmethod
    def health_check(self, credentials: Dict[str, Any]) -> bool:
        """Returns True if the integration can currently communicate with the upstream service."""
        pass


class GitHubIntegrationProvider(BaseIntegrationProvider):
    id = "github"
    name = "GitHub"
    category = "Development"
    description = "Sync repositories, inspect pull requests, and commit code directly."
    capabilities = ["repo:read", "repo:write", "pull_requests", "code_search"]
    is_implemented = True

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        token_str = (credentials.get("access_token") or "").strip()
        if not token_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid GitHub personal access token or OAuth access_token is required."
            )
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token_str}",
                    "User-Agent": "Sakura-AI-Platform",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("login"):
                    raise HTTPException(status_code=400, detail="Invalid GitHub account data returned.")
                return data
        except urllib.error.HTTPError as he:
            if he.code in [401, 403]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="GitHub authentication failed: Token is invalid, expired, or has insufficient permissions."
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API error: HTTP {he.code}"
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to connect to GitHub API: {str(e)}"
            )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return validation_data.get("login") or "GitHub User"

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        try:
            self.validate_credentials(credentials)
            return True
        except Exception:
            return False


class GoogleDriveIntegrationProvider(BaseIntegrationProvider):
    id = "google_drive"
    name = "Google Drive"
    category = "Productivity"
    description = "Access Docs, Sheets, Presentations, and cloud storage files."
    capabilities = ["files:read", "docs:read"]
    is_implemented = False

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google Drive integration is not implemented yet."
        )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return ""

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        return False


class NotionIntegrationProvider(BaseIntegrationProvider):
    id = "notion"
    name = "Notion"
    category = "Knowledge"
    description = "Search pages, retrieve database rows, and sync meeting notes."
    capabilities = ["pages:read", "databases:read"]
    is_implemented = False

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Notion integration is not implemented yet."
        )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return ""

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        return False


class SlackIntegrationProvider(BaseIntegrationProvider):
    id = "slack"
    name = "Slack"
    category = "Communication"
    description = "Read channels, synthesize threads, and post automated digests."
    capabilities = ["channels:read", "chat:write"]
    is_implemented = False

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Slack integration is not implemented yet."
        )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return ""

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        return False


class PostgresIntegrationProvider(BaseIntegrationProvider):
    id = "postgres"
    name = "PostgreSQL"
    category = "Database"
    description = "Execute analytical read queries and inspect table schemas live."
    capabilities = ["query:read", "schema:inspect"]
    is_implemented = False

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PostgreSQL direct user integration is not implemented yet."
        )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return ""

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        return False


class JiraIntegrationProvider(BaseIntegrationProvider):
    id = "jira"
    name = "Jira / Linear"
    category = "Project Tracking"
    description = "Track roadmap tickets, backlog tasks, and sprint statuses."
    capabilities = ["issues:read", "issues:write"]
    is_implemented = False

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Jira / Linear integration is not implemented yet."
        )

    def get_account_identity(self, credentials: Dict[str, Any], validation_data: Dict[str, Any]) -> str:
        return ""

    def health_check(self, credentials: Dict[str, Any]) -> bool:
        return False


INTEGRATION_PROVIDERS: Dict[str, BaseIntegrationProvider] = {
    "github": GitHubIntegrationProvider(),
    "google_drive": GoogleDriveIntegrationProvider(),
    "notion": NotionIntegrationProvider(),
    "slack": SlackIntegrationProvider(),
    "postgres": PostgresIntegrationProvider(),
    "jira": JiraIntegrationProvider(),
}

SUPPORTED_PROVIDERS = [
    {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "capabilities": p.capabilities,
        "is_implemented": p.is_implemented
    }
    for p in INTEGRATION_PROVIDERS.values()
]


# ─── Canonical Typed Schema ───────────────────────────────────────────────────

class IntegrationResponse(BaseModel):
    id: str
    name: str
    category: str
    description: str
    state: str = Field(description="Operational state: NOT_CONFIGURED, DISCONNECTED, AUTHORIZING, CONNECTED, ERROR")
    connected: bool
    account_name: Optional[str] = None
    connected_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    health_status: Optional[str] = None
    capabilities: List[str] = []
    is_implemented: bool = False


class ConnectIntegrationRequest(BaseModel):
    account_name: Optional[str] = None
    access_token: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


# ─── Serialization Helper ─────────────────────────────────────────────────────

def _serialize_integration(
    provider: BaseIntegrationProvider,
    record: Optional[UserIntegration]
) -> IntegrationResponse:
    prov_id = provider.id
    # Only implemented providers with genuine verification can be CONNECTED
    is_connected = bool(provider.is_implemented and record and record.connected)
    cfg = (record.config_json or {}) if record else {}
    last_verified_at = cfg.get("last_verified_at")
    health_status = cfg.get("health_status")

    if is_connected:
        state = "CONNECTED"
        if not health_status:
            health_status = "HEALTHY"
    elif record and cfg.get("health_status") == "ERROR":
        state = "ERROR"
    elif provider.is_implemented:
        if prov_id == "github":
            has_client = bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))
            state = "DISCONNECTED" if has_client else "NOT_CONFIGURED"
        else:
            state = "NOT_CONFIGURED"
    else:
        state = "NOT_CONFIGURED"

    connected_at = record.created_at.isoformat() if (record and is_connected and record.created_at) else None
    updated_at = record.updated_at.isoformat() if (record and record.updated_at) else None

    return IntegrationResponse(
        id=prov_id,
        name=provider.name,
        category=provider.category,
        description=provider.description,
        state=state,
        connected=is_connected,
        account_name=record.account_name if (record and is_connected) else None,
        connected_at=connected_at,
        updated_at=updated_at,
        last_verified_at=last_verified_at,
        health_status=health_status,
        capabilities=provider.capabilities,
        is_implemented=provider.is_implemented
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[IntegrationResponse])
@router.get("/", response_model=List[IntegrationResponse])
def get_integrations_status(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns actual connection state for all third-party integrations
    backed by real database state. Never returns hard-coded fake connections.
    """
    user_integrations = {
        i.provider: i
        for i in db.query(UserIntegration).filter(
            UserIntegration.user_id == current_user.id
        ).all()
    }

    results = []
    for prov_id, provider in INTEGRATION_PROVIDERS.items():
        rec = user_integrations.get(prov_id)
        results.append(_serialize_integration(provider, rec))
    return results


@router.post("/{provider}/connect", response_model=IntegrationResponse)
def connect_integration(
    provider: str,
    req: ConnectIntegrationRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Connects or updates an integration after verifying credentials with the provider API.
    Never marks an integration CONNECTED unless credentials are valid.
    Unsupported connectors return 501 Not Implemented.
    Encrypts sensitive tokens at rest using dedicated integration encryption key.
    """
    adapter = INTEGRATION_PROVIDERS.get(provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported integration provider '{provider}'")

    if not adapter.is_implemented:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Integration provider '{provider}' is not implemented yet. Unverified connections are prohibited."
        )

    raw_token = (req.access_token or (req.config or {}).get("access_token") or "").strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An explicit user access token or PAT is required to connect {provider}."
        )

    credentials = {"access_token": raw_token}
    validation_data = adapter.validate_credentials(credentials)
    verified_account = adapter.get_account_identity(credentials, validation_data)
    encrypted_token = encrypt_secret(raw_token)

    integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == provider
    ).first()

    config_payload = dict(req.config or {})
    config_payload["encrypted_token"] = encrypted_token
    config_payload["last_verified_at"] = utc_now().isoformat()
    config_payload["health_status"] = "HEALTHY"
    config_payload.pop("access_token", None)

    if not integration:
        integration = UserIntegration(
            id=uuid.uuid4(),
            user_id=current_user.id,
            provider=provider,
            account_name=verified_account or f"{adapter.name} Account",
            connected=True,
            config_json=config_payload,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(integration)
    else:
        integration.account_name = verified_account or integration.account_name
        integration.connected = True
        integration.config_json = config_payload
        integration.updated_at = utc_now()

    db.commit()
    db.refresh(integration)
    return _serialize_integration(adapter, integration)


@router.post("/{provider}/disconnect", response_model=IntegrationResponse)
def disconnect_integration(
    provider: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Disconnects and revokes integration, clearing stored credentials."""
    adapter = INTEGRATION_PROVIDERS.get(provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported integration provider '{provider}'")

    integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == provider
    ).first()

    if integration:
        integration.connected = False
        integration.config_json = {}
        integration.updated_at = utc_now()
        db.commit()
        db.refresh(integration)

    return _serialize_integration(adapter, integration)


@router.post("/{provider}/revalidate", response_model=IntegrationResponse)
def revalidate_integration(
    provider: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Revalidates credential health against upstream provider.
    Transitions state to ERROR/DISCONNECTED if revoked or expired.
    Upgrades legacy encryption envelopes transparently.
    """
    adapter = INTEGRATION_PROVIDERS.get(provider)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unsupported integration provider '{provider}'")

    if not adapter.is_implemented:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Integration provider '{provider}' is not implemented yet."
        )

    integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == provider
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found.")

    cfg = dict(integration.config_json or {})
    enc_token = cfg.get("encrypted_token")

    from auth.crypto import decrypt_and_upgrade_secret
    raw_token, upgraded_envelope = decrypt_and_upgrade_secret(enc_token)
    if upgraded_envelope:
        cfg["encrypted_token"] = upgraded_envelope

    now_iso = utc_now().isoformat()
    cfg["last_verified_at"] = now_iso

    try:
        credentials = {"access_token": raw_token}
        validation_data = adapter.validate_credentials(credentials)
        integration.account_name = adapter.get_account_identity(credentials, validation_data) or integration.account_name
        integration.connected = True
        cfg["health_status"] = "HEALTHY"
    except Exception as e:
        integration.connected = False
        cfg["health_status"] = "ERROR"

    integration.config_json = cfg
    integration.updated_at = utc_now()
    db.commit()
    db.refresh(integration)
    return _serialize_integration(adapter, integration)


import urllib.error

@router.get("/github/repos")
async def list_github_repositories(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Lists repositories accessible to user's connected GitHub integration."""
    gh_integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == "github",
        UserIntegration.connected == True
    ).first()

    if not gh_integration:
        return {"connected": False, "repositories": []}

    cfg = dict(gh_integration.config_json or {})
    enc_token = cfg.get("encrypted_token")
    if not enc_token:
        return {
            "connected": False,
            "account": gh_integration.account_name,
            "repositories": [],
            "error": "No authenticated GitHub access token stored for this account."
        }

    raw_token, upgraded_envelope = decrypt_and_upgrade_secret(enc_token)
    if upgraded_envelope:
        cfg["encrypted_token"] = upgraded_envelope
        gh_integration.config_json = cfg
        db.commit()

    if not raw_token:
        gh_integration.connected = False
        cfg["health_status"] = "ERROR"
        gh_integration.config_json = cfg
        db.commit()
        return {
            "connected": False,
            "account": gh_integration.account_name,
            "repositories": [],
            "error": "Failed to decrypt GitHub credentials. Please reconnect."
        }

    try:
        req = urllib.request.Request(
            "https://api.github.com/user/repos?sort=updated&per_page=30",
            headers={
                "Authorization": f"Bearer {raw_token}",
                "User-Agent": "Sakura-AI-Platform",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            repos = [
                {
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "default_branch": r.get("default_branch", "main"),
                    "clone_url": r.get("clone_url"),
                    "private": r.get("private", False)
                }
                for r in data if isinstance(r, dict)
            ]
            cfg["health_status"] = "HEALTHY"
            cfg["last_verified_at"] = utc_now().isoformat()
            gh_integration.config_json = cfg
            db.commit()
            return {
                "connected": True,
                "account": gh_integration.account_name,
                "repositories": repos
            }
    except urllib.error.HTTPError as he:
        if he.code in (401, 403):
            gh_integration.connected = False
            cfg["health_status"] = "ERROR"
            cfg["last_verified_at"] = utc_now().isoformat()
            gh_integration.config_json = cfg
            db.commit()
            return {
                "connected": False,
                "account": gh_integration.account_name,
                "repositories": [],
                "error": "GitHub credentials expired or revoked. Please reconnect."
            }
        elif he.code == 429:
            cfg["health_status"] = "DEGRADED"
            gh_integration.config_json = cfg
            db.commit()
            return {
                "connected": True,
                "account": gh_integration.account_name,
                "repositories": [],
                "error": "GitHub API rate limit reached. Please try again later."
            }
        else:
            cfg["health_status"] = "DEGRADED"
            gh_integration.config_json = cfg
            db.commit()
            return {
                "connected": True,
                "account": gh_integration.account_name,
                "repositories": [],
                "error": f"Upstream GitHub service error ({he.code})."
            }
    except Exception:
        cfg["health_status"] = "DEGRADED"
        gh_integration.config_json = cfg
        db.commit()
        return {
            "connected": True,
            "account": gh_integration.account_name,
            "repositories": [],
            "error": "Network timeout or error communicating with GitHub."
        }

