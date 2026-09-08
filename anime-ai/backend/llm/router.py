import os
import sys
from typing import Dict, Any, Optional, List, AsyncGenerator
from llm.providers.base import LLMProvider
from llm.providers.openai import OpenAIProvider
from llm.providers.groq import GroqProvider
from llm.providers.anthropic import AnthropicProvider
from llm.providers.ollama import OllamaProvider

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
        model_fast = os.getenv("SAKURA_MODEL_FAST", "llama-3.1-8b-instant")
        model_balanced = os.getenv("SAKURA_MODEL_BALANCED", "llama-3.3-70b-versatile")
        model_reasoning = os.getenv("SAKURA_MODEL_REASONING", "claude-3-haiku-20240307")
        model_code = os.getenv("SAKURA_MODEL_CODE", "llama-3.1-8b-instant")

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

    def get_provider(self, intent: str = "general_chat") -> tuple[str, LLMProvider]:
        """
        Routes query to best provider based on domain intent and credentials.
        """
        intent_lower = (intent or "general_chat").lower()

        # Intent routing priorities:
        if intent_lower in ["code_generation", "repository_coding", "debugging", "architecture"]:
            # Prefer specialized coding / frontier models
            preferred = ["groq", "anthropic", "openai", "ollama"]
        elif intent_lower in ["reasoning", "deep_research", "document_analysis"]:
            # Prefer strong reasoning models
            preferred = ["anthropic", "openai", "groq", "ollama"]
        elif intent_lower in ["local_private", "private_data"]:
            preferred = ["ollama", "openai", "groq"]
        else: # general_chat / general_inquiry
            preferred = ["groq", "openai", "anthropic", "ollama"]

        for name in preferred:
            if name in self.providers:
                return name, self.providers[name]

        if "ollama" in self.providers:
            return "ollama", self.providers["ollama"]

        raise RuntimeError("No LLM providers available. Set GROQ_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY in .env.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_chat",
        **kwargs
    ) -> tuple[str, str]:
        """Routes and calls the appropriate model for direct text generation."""
        allow_mocks = os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        provider_name = "unknown"
        try:
            provider_name, provider = self.get_provider(intent)
            response = await provider.generate(prompt, system_prompt, history, **kwargs)
            from datetime import datetime, timezone
            self.provider_telemetry[provider_name] = {
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
                "healthy": True,
                "status": "AVAILABLE"
            }
            return provider_name, response
        except Exception as e:
            if provider_name in self.providers:
                from datetime import datetime, timezone
                self.provider_telemetry[provider_name] = {
                    "last_verified_at": self.provider_telemetry.get(provider_name, {}).get("last_verified_at"),
                    "healthy": False,
                    "status": "UNAVAILABLE",
                    "error": str(e)
                }
            if not allow_mocks:
                raise RuntimeError(f"LLM Provider unavailable: {str(e)}")
            print(f"LLM Router Error: {e}. Falling back to test mock generator.")
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
        """Streams content tokens with transparent failure handling."""
        allow_mocks = os.getenv("SAKURA_ALLOW_MOCKS", "false").lower() == "true"
        provider_name = "unknown"
        try:
            provider_name, provider = self.get_provider(intent)
            first = True
            async for token in provider.stream(prompt, system_prompt, history, **kwargs):
                if first:
                    first = False
                    from datetime import datetime, timezone
                    self.provider_telemetry[provider_name] = {
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                        "healthy": True,
                        "status": "AVAILABLE"
                    }
                yield {"token": token, "provider": provider_name}
        except Exception as e:
            if provider_name in self.providers:
                from datetime import datetime, timezone
                self.provider_telemetry[provider_name] = {
                    "last_verified_at": self.provider_telemetry.get(provider_name, {}).get("last_verified_at"),
                    "healthy": False,
                    "status": "UNAVAILABLE",
                    "error": str(e)
                }
            if not allow_mocks:
                raise RuntimeError(f"LLM Streaming failure: {str(e)}")
            print(f"LLM Router Streaming Error: {e}. Yielding fallback mock tokens for test environment.")
            from llm.prompts.mock_generator import local_mock_response
            fallback_text = local_mock_response(prompt)
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                token = word if i == 0 else " " + word
                yield {"token": token, "provider": "fallback_mock"}
                await __import__("asyncio").sleep(0.02)
