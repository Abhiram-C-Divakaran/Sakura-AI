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

        # 4. Ollama (Always check local fallback)
        try:
            ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
            self.providers["ollama"] = OllamaProvider(model=ollama_model)
            print("LLM Router: Ollama local adapter registered.")
        except Exception as e:
            print(f"LLM Router: Failed to register Ollama: {e}")

    def get_ordered_providers(self, intent: str = "general_chat") -> List[Tuple[str, LLMProvider]]:
        """Returns ordered list of available providers for priority intent routing and failover."""
        intent_lower = (intent or "general_chat").lower()
        if intent_lower in ["code_generation", "repository_coding", "debugging", "architecture"]:
            preferred = ["groq", "anthropic", "openai", "ollama"]
        elif intent_lower in ["reasoning", "deep_research", "document_analysis"]:
            preferred = ["anthropic", "openai", "groq", "ollama"]
        elif intent_lower in ["local_private", "private_data"]:
            preferred = ["ollama", "openai", "groq"]
        else:
            preferred = ["groq", "openai", "anthropic", "ollama"]

        ordered = []
        for name in preferred:
            if name in self.providers:
                ordered.append((name, self.providers[name]))
        return ordered

    def get_provider(self, intent: str = "general_chat") -> tuple[str, LLMProvider]:
        """Routes query to best provider based on domain intent and credentials."""
        ordered = self.get_ordered_providers(intent)
        if ordered:
            return ordered[0]
        raise RuntimeError("No LLM providers available. Set GROQ_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_chat",
        **kwargs
    ) -> tuple[str, str]:
        """Routes and calls the appropriate model with bounded transient failover."""
        allow_mocks = os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        candidates = self.get_ordered_providers(intent)
        if not candidates:
            if allow_mocks:
                from llm.prompts.mock_generator import local_mock_response
                return "fallback_mock", local_mock_response(prompt)
            raise RuntimeError("No LLM providers available.")

        last_error = None
        for provider_name, provider in candidates:
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
                if not is_transient_error(e):
                    # Do not failover on non-retryable auth/policy errors
                    break
                continue

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
        """Streams content tokens with bounded transient failure handling and failover."""
        allow_mocks = os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        candidates = self.get_ordered_providers(intent)
        if not candidates:
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
                if token_yielded or not is_transient_error(e):
                    # If tokens were already sent to client, we cannot cleanly switch providers mid-stream
                    break
                continue

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
