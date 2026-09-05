"""
Sakura AI — Centralized Typed Settings & Production Security Validation

Uses pydantic-settings to validate configuration across development,
staging, and production environments with strict JWT security enforcement.
"""

import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

KNOWN_DEV_SECRETS = {
    "supersecret_vintage_anime_key_replace_in_production",
    "sakura_dev_secret_change_for_prod_123456789",
    "change-this-in-production",
    "secret",
    "changeme",
    "password",
    "12345678",
    "sakura_dev_secret_local_only_1234567890",
    "sakura_dev_integration_key_local_only_1234567890",
}

class Settings(BaseSettings):
    """Production application settings with strict validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    jwt_secret: str = Field(
        default="sakura_dev_secret_local_only_1234567890",
        alias="JWT_SECRET"
    )
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Integration Encryption (independent from JWT_SECRET)
    integration_encryption_key: Optional[str] = Field(
        default="sakura_dev_integration_key_local_only_1234567890",
        alias="INTEGRATION_ENCRYPTION_KEY"
    )

    # CORS
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS"
    )

    # Databases
    database_url: str = Field(default="sqlite:///./anime_ai.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # LLM Providers
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # Model Routing
    sakura_model_fast: str = Field(default="llama-3.1-8b-instant", alias="SAKURA_MODEL_FAST")
    sakura_model_code: str = Field(default="qwen/qwen3.8-27b", alias="SAKURA_MODEL_CODE")
    sakura_model_reasoning: str = Field(default="deepseek-r1-distill-llama-70b", alias="SAKURA_MODEL_REASONING")

    # Sandbox Isolation & Internal Executor Service
    sakura_sandbox_runtime: str = Field(default="auto", alias="SAKURA_SANDBOX_RUNTIME")
    sakura_sandbox_image: str = Field(default="sakura-sandbox:latest", alias="SAKURA_SANDBOX_IMAGE")
    sakura_sandbox_executor_url: str = Field(default="http://sandbox-executor:9000", alias="SAKURA_SANDBOX_EXECUTOR_URL")
    sakura_sandbox_service_token: Optional[str] = Field(default=None, alias="SAKURA_SANDBOX_SERVICE_TOKEN")

    # Mocks & Reliability
    sakura_allow_mocks: bool = Field(default=False, alias="SAKURA_ALLOW_MOCKS")

    # Search & RAG
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")
    cohere_api_key: Optional[str] = Field(default=None, alias="COHERE_API_KEY")

    # Media
    stability_api_key: Optional[str] = Field(default=None, alias="STABILITY_API_KEY")
    replicate_api_token: Optional[str] = Field(default=None, alias="REPLICATE_API_TOKEN")

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        return str(v or "development").strip().lower()

    def validate_production_guards(self) -> None:
        """
        Guarantees that production environments enforce secure, high-entropy secrets.
        Fails startup loudly if insecure configurations are detected.
        """
        is_prod = self.environment in ["production", "prod"]
        
        if is_prod:
            if not self.jwt_secret or self.jwt_secret in KNOWN_DEV_SECRETS:
                raise RuntimeError(
                    "Production startup failed: FATAL PRODUCTION SECURITY ERROR: JWT_SECRET must be explicitly provided in production "
                    "and cannot match any known default or development keys."
                )
            if len(self.jwt_secret) < 32:
                raise RuntimeError(
                    "Production startup failed: FATAL PRODUCTION SECURITY ERROR: JWT_SECRET must be at least 32 characters long "
                    f"in production (current length: {len(self.jwt_secret)})."
                )
            if not self.integration_encryption_key or self.integration_encryption_key in KNOWN_DEV_SECRETS:
                raise RuntimeError(
                    "Production startup failed: FATAL PRODUCTION SECURITY ERROR: INTEGRATION_ENCRYPTION_KEY must be explicitly provided in production "
                    "and cannot match any known default or development keys."
                )
            if len(self.integration_encryption_key) < 32:
                raise RuntimeError(
                    "Production startup failed: FATAL PRODUCTION SECURITY ERROR: INTEGRATION_ENCRYPTION_KEY must be at least 32 characters long "
                    f"in production (current length: {len(self.integration_encryption_key)})."
                )


@lru_cache()
def get_settings() -> Settings:
    """Returns cached application settings instance with startup validation."""
    settings = Settings()
    settings.validate_production_guards()
    return settings
