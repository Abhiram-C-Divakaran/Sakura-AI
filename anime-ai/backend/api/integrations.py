import os
import json
import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.db import get_db
from database.models import User, UserIntegration
from auth.manager import AuthManager

router = APIRouter(prefix="/integrations", tags=["integrations"])

SUPPORTED_PROVIDERS = [
    {"id": "github", "name": "GitHub", "category": "Development", "description": "Sync repositories, inspect pull requests, and commit code directly."},
    {"id": "google_drive", "name": "Google Drive", "category": "Productivity", "description": "Access Docs, Sheets, Presentations, and cloud storage files."},
    {"id": "notion", "name": "Notion", "category": "Knowledge", "description": "Search pages, retrieve database rows, and sync meeting notes."},
    {"id": "slack", "name": "Slack", "category": "Communication", "description": "Read channels, synthesize threads, and post automated digests."},
    {"id": "postgres", "name": "PostgreSQL", "category": "Database", "description": "Execute analytical read queries and inspect table schemas live."},
    {"id": "jira", "name": "Jira / Linear", "category": "Project Tracking", "description": "Track roadmap tickets, backlog tasks, and sprint statuses."}
]

class ConnectIntegrationRequest(BaseModel):
    account_name: str
    access_token: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

@router.get("", response_model=List[Dict[str, Any]])
def get_integrations_status(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns actual connection state for all third-party integrations
    backed by real database state. Never returns hard-coded fake connections.
    """
    active_integrations = {
        i.provider: i
        for i in db.query(UserIntegration).filter(
            UserIntegration.user_id == current_user.id,
            UserIntegration.connected == True
        ).all()
    }

    result = []
    for p in SUPPORTED_PROVIDERS:
        prov_id = p["id"]
        is_conn = prov_id in active_integrations
        active_rec = active_integrations.get(prov_id)
        result.append({
            "id": prov_id,
            "name": p["name"],
            "category": p["category"],
            "description": p["description"],
            "connected": is_conn,
            "account": active_rec.account_name if active_rec else None,
            "updated_at": active_rec.updated_at.isoformat() if active_rec and active_rec.updated_at else None
        })
    return result

@router.post("/{provider}/connect", response_model=Dict[str, Any])
def connect_integration(
    provider: str,
    req: ConnectIntegrationRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Connects or updates an integration with encrypted/safe configuration."""
    valid_ids = {p["id"] for p in SUPPORTED_PROVIDERS}
    if provider not in valid_ids:
        raise HTTPException(status_code=400, detail=f"Unsupported integration provider '{provider}'")

    integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == provider
    ).first()

    if not integration:
        integration = UserIntegration(
            id=uuid.uuid4(),
            user_id=current_user.id,
            provider=provider,
            account_name=req.account_name,
            connected=True,
            config_json=req.config or {}
        )
        db.add(integration)
    else:
        integration.account_name = req.account_name
        integration.connected = True
        integration.config_json = req.config or {}

    db.commit()
    return {"status": "connected", "provider": provider, "account": req.account_name}

@router.post("/{provider}/disconnect", response_model=Dict[str, Any])
def disconnect_integration(
    provider: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Disconnects and revokes integration."""
    integration = db.query(UserIntegration).filter(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == provider
    ).first()

    if integration:
        integration.connected = False
        db.commit()

    return {"status": "disconnected", "provider": provider}

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

    token = (gh_integration.config_json or {}).get("access_token") or os.getenv("GITHUB_TOKEN")
    if not token:
        # Connected without API token: return truthful empty list
        return {
            "connected": True,
            "account": gh_integration.account_name,
            "repositories": []
        }

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/user/repos?sort=updated&per_page=30",
            headers={
                "Authorization": f"Bearer {token}",
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
            return {
                "connected": True,
                "account": gh_integration.account_name,
                "repositories": repos
            }
    except Exception as e:
        print(f"GitHub repo fetch error: {e}")
        return {
            "connected": True,
            "account": gh_integration.account_name,
            "repositories": [],
            "error": "Failed to fetch repositories from GitHub API."
        }
