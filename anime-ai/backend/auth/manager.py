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

# Configuration & Security Guard
DEFAULT_INSECURE_KEY = "supersecret_vintage_anime_key_replace_in_production"
SECRET_KEY = os.getenv("JWT_SECRET", DEFAULT_INSECURE_KEY)
ENVIRONMENT = os.getenv("ENV", os.getenv("ENVIRONMENT", "development")).lower()

if ENVIRONMENT == "production" and (not SECRET_KEY or SECRET_KEY == DEFAULT_INSECURE_KEY):
    raise RuntimeError(
        "Production startup failed: JWT_SECRET must be explicitly configured and cannot use the default insecure key."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

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
    def validate_production_secret(env: Optional[str] = None, secret: Optional[str] = None) -> None:
        target_env = (env or os.getenv("ENV", os.getenv("ENVIRONMENT", "development"))).lower()
        target_secret = secret if secret is not None else os.getenv("JWT_SECRET", DEFAULT_INSECURE_KEY)
        if target_env == "production" and (not target_secret or target_secret == DEFAULT_INSECURE_KEY):
            raise RuntimeError(
                "Production startup failed: JWT_SECRET must be explicitly configured and cannot use the default insecure key."
            )

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

