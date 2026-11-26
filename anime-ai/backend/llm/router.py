import os
import sys
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator, Tuple
from datetime import datetime, timezone

from llm.providers.base import LLMProvider
from llm.providers.openai import OpenAIProvider
from llm.providers.groq import GroqProvider
from llm.providers.anthropic import AnthropicProvider
from llm.providers.ollama import OllamaProvider

logger = logging.getLogger("sakura.llm.router")

PRIVATE_INTENTS = {"local_private", "private_data"}
CLOUD_PROVIDERS = {"openai", "groq", "anthropic"}


class PrivateModelUnavailableError(RuntimeError):
    """Raised when a private/local-only intent cannot be served by a configured local provider."""
    pass


def is_transient_error(e: Exception) -> bool:
    """
    Classifies whether an LLM error is transient (eligible for provider failover)
    vs non-retryable (bad request, authentication failure, permissions).
    """
    err_msg = str(e).lower()
    # Non-retryable: auth failure, invalid API key, permission denied
    if any(k in err_msg for k in ["401", "unauthorized", "invalid api key", "403", "forbidden"]):
        return False
    # Transient: rate limit 429, timeouts, connection/network errors, 502/503/504
    transient_indicators = [
        "429", "rate limit", "timeout", "timed out", "connection",
        "connecterror", "getaddrinfo", "econnreset", "500", "502", "503", "504",
        "overloaded", "server error", "temporarily unavailable"
    ]
    return any(k in err_msg for k in transient_indicators)


class LLMRouter:
    """
    Orchestrates provider adapters, routes queries according to 
    computational complexity, intent, and intensity, and handles transparent errors.
    """

    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self.provider_telemetry: Dict[str, Dict[str, Any]] = {}
        self._initialize_adapters()

    def _initialize_adapters(self):
        """Initializes adapters configured via environment variables."""
        # Configurable model identifiers
        model_fast = os.getenv("SAKURA_MODEL_FAST", "qwen/qwen3.8-27b")
        model_balanced = os.getenv("SAKURA_MODEL_BALANCED", "llama-3.3-70b-versatile")
        model_reasoning = os.getenv("SAKURA_MODEL_REASONING", "claude-3-haiku-20240307")
        model_code = os.getenv("SAKURA_MODEL_CODE", "qwen/qwen3.8-27b")

        # 1. Groq (High-speed inference)
        if os.getenv("GROQ_API_KEY"):
            try:
                self.providers["groq"] = GroqProvider(model=model_code)
                print(f"LLM Router: Groq adapter active ({model_code}).")
            except Exception as e:
                print(f"LLM Router: Failed to initialize Groq: {e}")

        # 2. OpenAI
        if os.getenv("OPENAI_API_KEY"):
            try:
                self.providers["openai"] = OpenAIProvider(model=model_balanced)
                print(f"LLM Router: OpenAI adapter active ({model_balanced}).")
            except Exception as e:
                print(f"LLM Router: Failed to initialize OpenAI: {e}")

        # 3. Anthropic
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                self.providers["anthropic"] = AnthropicProvider(model=model_reasoning)
                print(f"LLM Router: Anthropic adapter active ({model_reasoning}).")
            except Exception as e:
                print(f"LLM Router: Failed to initialize Anthropic: {e}")

        # 4. Ollama (Register only when explicitly configured via env)
        ollama_url = (os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "").strip()
        ollama_model = (os.getenv("OLLAMA_MODEL") or "").strip()
        if ollama_url or ollama_model:
            try:
                self.providers["ollama"] = OllamaProvider(
                    base_url=ollama_url or "http://localhost:11434",
                    model=ollama_model or "llama3"
                )
                print("LLM Router: Ollama local adapter registered.")
            except Exception as e:
                print(f"LLM Router: Failed to register Ollama: {e}")

    def is_private_intent(self, intent: Optional[str]) -> bool:
        return (intent or "general_chat").strip().lower() in PRIVATE_INTENTS

    def get_ordered_providers(self, intent: str = "general_chat") -> List[Tuple[str, LLMProvider]]:
        """Returns ordered list of available providers for priority intent routing and failover."""
        intent_lower = (intent or "general_chat").strip().lower()
        if intent_lower in PRIVATE_INTENTS:
            # STRICT PRIVACY BOUNDARY: Private intents may ONLY use explicitly configured local providers.
            # Cloud providers (OpenAI, Groq, Anthropic) are strictly prohibited from this list.
            preferred = ["ollama"]
        elif intent_lower in ["code_generation", "repository_coding", "debugging", "architecture"]:
            preferred = ["groq", "anthropic", "openai", "ollama"]
        elif intent_lower in ["reasoning", "deep_research", "document_analysis"]:
            preferred = ["anthropic", "openai", "groq", "ollama"]
        else:
            preferred = ["groq", "openai", "anthropic", "ollama"]

        ordered = []
        for name in preferred:
            if intent_lower in PRIVATE_INTENTS and name in CLOUD_PROVIDERS:
                continue
            if name in self.providers:
                ordered.append((name, self.providers[name]))
        return ordered

    def get_provider(self, intent: str = "general_chat") -> tuple[str, LLMProvider]:
        """Routes query to best provider based on domain intent and credentials."""
        ordered = self.get_ordered_providers(intent)
        if ordered:
            return ordered[0]
        if self.is_private_intent(intent):
            raise PrivateModelUnavailableError(
                "Private local model is not configured or unavailable. "
                "Private requests fail closed and will not be sent to cloud providers."
            )
        raise RuntimeError("No LLM providers available. Set GROQ_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_chat",
        **kwargs
    ) -> tuple[str, str]:
        """Routes and calls the appropriate model with bounded transient failover (fail-closed for private intents)."""
        is_private = self.is_private_intent(intent)
        allow_mocks = (not is_private) and os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        candidates = self.get_ordered_providers(intent)
        if is_private:
            candidates = [(n, p) for n, p in candidates if n not in CLOUD_PROVIDERS]

        if not candidates:
            if is_private:
                raise PrivateModelUnavailableError(
                    "Private local model is not configured or unavailable. "
                    "To protect your data, this request was not sent to any cloud AI provider."
                )
            if allow_mocks:
                from llm.prompts.mock_generator import local_mock_response
                return "fallback_mock", local_mock_response(prompt)
            raise RuntimeError("No LLM providers available.")

        last_error = None
        for provider_name, provider in candidates:
            if is_private and provider_name in CLOUD_PROVIDERS:
                continue
            try:
                response = await provider.generate(prompt, system_prompt, history, **kwargs)
                self.provider_telemetry[provider_name] = {
                    "last_verified_at": datetime.now(timezone.utc).isoformat(),
                    "healthy": True,
                    "status": "AVAILABLE"
                }
                return provider_name, response
            except Exception as e:
                last_error = e
                self.provider_telemetry[provider_name] = {
                    "last_verified_at": self.provider_telemetry.get(provider_name, {}).get("last_verified_at"),
                    "healthy": False,
                    "status": "DEGRADED" if is_transient_error(e) else "UNAVAILABLE",
                    "error": str(e)
                }
                logger.warning(f"LLM Provider {provider_name} failed: {e}")
                if is_private or not is_transient_error(e):
                    break
                continue

        if is_private:
            raise PrivateModelUnavailableError(
                f"Private local model is currently unavailable ({last_error}). "
                "To protect your privacy, this request was not routed to any cloud provider."
            )
        if not allow_mocks:
            raise RuntimeError(f"LLM Provider unavailable: {str(last_error)}")
        print(f"LLM Router Error: {last_error}. Falling back to test mock generator.")
        from llm.prompts.mock_generator import local_mock_response
        return "fallback_mock", local_mock_response(prompt)

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_chat",
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streams content tokens with bounded transient failure handling (fail-closed for private intents)."""
        is_private = self.is_private_intent(intent)
        allow_mocks = (not is_private) and os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        candidates = self.get_ordered_providers(intent)
        if is_private:
            candidates = [(n, p) for n, p in candidates if n not in CLOUD_PROVIDERS]

        if not candidates:
            if is_private:
                raise PrivateModelUnavailableError(
                    "Private local model is not configured or unavailable. "
                    "To protect your data, this request was not sent to any cloud AI provider."
                )
            if allow_mocks:
                from llm.prompts.mock_generator import local_mock_response
                fallback_text = local_mock_response(prompt)
                for i, word in enumerate(fallback_text.split(" ")):
                    token = word if i == 0 else " " + word
                    yield {"token": token, "provider": "fallback_mock"}
                return
            raise RuntimeError("No LLM providers available.")

        last_error = None
        for provider_name, provider in candidates:
            if is_private and provider_name in CLOUD_PROVIDERS:
                continue
            token_yielded = False
            try:
                first = True
                async for token in provider.stream(prompt, system_prompt, history, **kwargs):
                    token_yielded = True
                    if first:
                        first = False
                        self.provider_telemetry[provider_name] = {
                            "last_verified_at": datetime.now(timezone.utc).isoformat(),
                            "healthy": True,
                            "status": "AVAILABLE"
                        }
                    yield {"token": token, "provider": provider_name}
                # Successfully streamed entire response
                return
            except Exception as e:
                last_error = e
                self.provider_telemetry[provider_name] = {
                    "last_verified_at": self.provider_telemetry.get(provider_name, {}).get("last_verified_at"),
                    "healthy": False,
                    "status": "DEGRADED" if is_transient_error(e) else "UNAVAILABLE",
                    "error": str(e)
                }
                logger.warning(f"LLM Provider stream {provider_name} failed: {e}")
                if is_private or token_yielded or not is_transient_error(e):
                    break
                continue

        if is_private:
            raise PrivateModelUnavailableError(
                f"Private local model is currently unavailable ({last_error}). "
                "To protect your privacy, this request was not routed to any cloud provider."
            )
        if not allow_mocks:
            raise RuntimeError(f"LLM Streaming failure: {str(last_error)}")
        print(f"LLM Router Streaming Error: {last_error}. Yielding fallback mock tokens for test environment.")
        from llm.prompts.mock_generator import local_mock_response
        fallback_text = local_mock_response(prompt)
        words = fallback_text.split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else " " + word
            yield {"token": token, "provider": "fallback_mock"}
            await __import__("asyncio").sleep(0.02)
