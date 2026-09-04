from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional

class LLMProvider(ABC):
    """
    Abstract interface for LLM Providers. Swapping providers (OpenAI, Anthropic,
    Groq, Ollama) only requires writing an adapter extending this class.
    """

    model: str = "default"

    @abstractmethod
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> str:
        """Standard text generation call."""
        pass

    @abstractmethod
    async def stream(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Streams text chunks progressively."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Forces the LLM to output valid JSON matching a Pydantic structure."""
        pass

    @abstractmethod
    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes a single provider-neutral turn with tools.
        Returns:
        {
            "content": Optional[str],
            "tool_calls": [
                {
                    "id": str,
                    "name": str,
                    "arguments": dict
                }
            ],
            "finish_reason": "tool_calls" | "stop" | "length"
        }
        """
        pass
