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
    computational complexity, and handles automatic fallback recovery.
    """

    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self._initialize_adapters()

    def _initialize_adapters(self):
        """Initializes only the adapters that have valid credentials available."""
        # 1. OpenAI
        if os.getenv("OPENAI_API_KEY"):
            try:
                self.providers["openai"] = OpenAIProvider(model="gpt-4o-mini")
                print("LLM Router: OpenAI adapter active.")
            except Exception as e:
                print(f"LLM Router: Failed to initialize OpenAI: {e}")

        # 2. Groq
        if os.getenv("GROQ_API_KEY"):
            try:
                groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
                self.providers["groq"] = GroqProvider(model=groq_model)
                print(f"LLM Router: Groq adapter active ({groq_model}).")
            except Exception as e:
                print(f"LLM Router: Failed to initialize Groq: {e}")

        # 3. Anthropic
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                self.providers["anthropic"] = AnthropicProvider(model="claude-3-haiku-20240307")
                print("LLM Router: Anthropic adapter active.")
            except Exception as e:
                print(f"LLM Router: Failed to initialize Anthropic: {e}")

        # 4. Ollama (Always check local fallback)
        try:
            # We don't verify connection immediately to avoid startup delay
            self.providers["ollama"] = OllamaProvider(model="llama3")
            print("LLM Router: Ollama local adapter registered.")
        except Exception as e:
            print(f"LLM Router: Failed to register Ollama: {e}")

    def get_provider(self, intent: str = "general_inquiry") -> tuple[str, LLMProvider]:
        """
        Routes the query to the best provider based on classification intent 
        and available keys.
        """
        # Routing Rules:
        # - login_issue, general_inquiry -> Groq (fast/cheap) or OpenAI Mini
        # - app_crash, billing_issue -> OpenAI or Anthropic (higher reasoning)
        # - local / offline queries -> Ollama
        
        if intent in ["code_generation", "complex_reasoning", "app_crash", "billing_issue"]:
            preferred = ["groq", "openai", "anthropic", "ollama"]
        elif intent in ["local_workload", "private_data"]:
            preferred = ["ollama", "openai", "groq"]
        else:
            preferred = ["groq", "openai", "anthropic", "ollama"]

        for name in preferred:
            if name in self.providers:
                return name, self.providers[name]
        
        # Absolute fallback: Return Ollama if it is registered, or raise
        if "ollama" in self.providers:
            return "ollama", self.providers["ollama"]
            
        raise RuntimeError("No LLM providers available. Set api keys in .env.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_inquiry",
        **kwargs
    ) -> tuple[str, str]:
        """Routes and calls the appropriate model for direct text generation."""
        try:
            provider_name, provider = self.get_provider(intent)
            response = await provider.generate(prompt, system_prompt, history, **kwargs)
            return provider_name, response
        except Exception as e:
            print(f"LLM Router Error: {e}. Falling back to local mock generator.")
            from llm.providers.ollama import OllamaProvider
            # We import local fallback response from llm helper
            from llm.prompts.mock_generator import local_mock_response
            return "fallback_mock", local_mock_response(prompt)

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        intent: str = "general_inquiry",
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streams content tokens. Yields dictionary objects with token metadata."""
        provider_name = "fallback_mock"
        try:
            provider_name, provider = self.get_provider(intent)
            async for token in provider.stream(prompt, system_prompt, history, **kwargs):
                yield {"token": token, "provider": provider_name}
        except Exception as e:
            print(f"LLM Router Streaming Error: {e}. Yielding fallback mock tokens.")
            from llm.prompts.mock_generator import local_mock_response
            fallback_text = local_mock_response(prompt)
            # Yield characters one by one or in small word chunks to simulate stream
            words = fallback_text.split(" ")
            for i, word in enumerate(words):
                # Add spacing back
                token = word if i == 0 else " " + word
                yield {"token": token, "provider": "fallback_mock"}
                await __import__("asyncio").sleep(0.02)
