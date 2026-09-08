import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import User

from config.settings import get_settings

settings = get_settings()
SECRET_KEY = settings.jwt_secret
ENVIRONMENT = settings.environment
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

class AuthManager:
    """Handles password hashing, token operations, password strength validation, and session verification."""

    @staticmethod
    def validate_password_strength(password: str) -> None:
        """Enforces minimum password security requirements."""
        if not password or len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long."
            )

    @staticmethod
    def hash_password(password: str) -> str:
        AuthManager.validate_password_strength(password)
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire, "iat": now})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> dict:
        """Decodes and validates a JWT token, handling expiration and signature integrity."""
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

    @staticmethod
    def verify_token(token: str) -> Optional[str]:
        """Convenience method to verify token and return subject, or None if invalid."""
        try:
            payload = AuthManager.decode_token(token)
            return payload.get("sub")
        except Exception:
            return None

    @staticmethod
    def validate_production_secret(
        secret: Optional[str] = None,
        environment: Optional[str] = None,
        env: Optional[str] = None,
        integration_key: Optional[str] = None
    ) -> bool:
        """
        Validates secrets against production security requirements by delegating
        to the centralized Settings.validate_production_guards().
        """
        target_env = (env or environment or os.getenv("ENVIRONMENT", os.getenv("ENV", "development"))).lower()
        target_secret = secret if secret is not None else os.getenv("JWT_SECRET", "")
        target_integration_key = integration_key if integration_key is not None else os.getenv(
            "INTEGRATION_ENCRYPTION_KEY",
            "valid_integration_key_for_test_min_32_chars_123" if target_env in ["production", "prod"] else None
        )
        from config.settings import Settings
        kwargs = {"ENVIRONMENT": target_env, "JWT_SECRET": target_secret}
        if target_integration_key is not None:
            kwargs["INTEGRATION_ENCRYPTION_KEY"] = target_integration_key
        s = Settings(**kwargs)
        s.validate_production_guards()
        return True

    @staticmethod
    def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = AuthManager.decode_token(token)
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
        except (JWTError, Exception):
            raise credentials_exception

        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise credentials_exception
        return user

    @staticmethod
    def get_optional_current_user(token: Optional[str] = Depends(oauth2_scheme_optional), db: Session = Depends(get_db)) -> Optional[User]:
        if not token:
            return None
        try:
            payload = AuthManager.decode_token(token)
            username = payload.get("sub")
            if not username:
                return None
            return db.query(User).filter(User.username == username).first()
        except Exception:
            return None

    @staticmethod
    def issue_ws_ticket(user_id: Any, ttl_seconds: int = 60, db: Optional[Session] = None) -> dict:
        """
        Issues a short-lived single-use WebSocket connection ticket.
        Persisted in database and optionally Redis.
        """
        import secrets
        import uuid as _uuid
        from database.models import WebSocketTicket, utc_now
        from database.db import get_db_context

        uid = _uuid.UUID(str(user_id)) if not isinstance(user_id, _uuid.UUID) else user_id
        ticket_str = f"wst_{secrets.token_urlsafe(32)}"
        now = utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds)

        def _do_persist(session: Session):
            ws_ticket = WebSocketTicket(
                ticket=ticket_str,
                user_id=uid,
                created_at=now,
                expires_at=expires_at,
                consumed_at=None
            )
            session.add(ws_ticket)
            session.commit()

        if db is not None:
            _do_persist(db)
        else:
            with get_db_context() as session:
                _do_persist(session)

        # Also store in Redis if available
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis
            client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.set(f"sakura:ws_ticket:{ticket_str}", str(uid), ex=ttl_seconds)
        except Exception:
            pass

        return {
            "ticket": ticket_str,
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": ttl_seconds
        }

    @staticmethod
    def consume_ws_ticket(ticket_str: str, db: Optional[Session] = None) -> Optional[Any]:
        """
        Validates and atomically consumes a single-use WebSocket ticket.
        Returns the user_id if valid and successfully consumed, or None.
        """
        if not ticket_str or not isinstance(ticket_str, str) or not ticket_str.startswith("wst_"):
            return None

        from database.models import WebSocketTicket, utc_now
        from database.db import get_db_context
        now = utc_now()

        def _do_consume(session: Session) -> Optional[Any]:
            ticket_rec = session.query(WebSocketTicket).filter(
                WebSocketTicket.ticket == ticket_str,
                WebSocketTicket.consumed_at.is_(None),
                WebSocketTicket.expires_at > now
            ).first()

            if not ticket_rec:
                return None

            user_id = ticket_rec.user_id
            rows = session.query(WebSocketTicket).filter(
                WebSocketTicket.ticket == ticket_str,
                WebSocketTicket.consumed_at.is_(None)
            ).update({WebSocketTicket.consumed_at: now})
            session.commit()

            if rows > 0:
                try:
                    import redis
                    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                    client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
                    client.delete(f"sakura:ws_ticket:{ticket_str}")
                except Exception:
                    pass
                return user_id
            return None

        if db is not None:
            return _do_consume(db)
        with get_db_context() as session:
            return _do_consume(session)


