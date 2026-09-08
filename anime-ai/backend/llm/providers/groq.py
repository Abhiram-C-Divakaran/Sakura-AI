import os
import json
import logging
from typing import Optional, Any, AsyncGenerator, List, Dict
from openai import AsyncOpenAI, NotFoundError
from llm.providers.openai import OpenAIProvider

logger = logging.getLogger("sakura.llm.groq")

FALLBACK_GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
]

class GroqProvider(OpenAIProvider):
    """
    Groq API Adapter with transparent model failover on deprecation/not-found.
    Uses OpenAI SDK client structure targeted at Groq's low-latency endpoints.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "qwen/qwen3.8-27b"):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set.")
        
        # Instantiate AsyncOpenAI client pointed at Groq with timeout
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=15.0
        )
        self.model = model

    async def _create_with_fallback(self, **kwargs) -> Any:
        """Executes chat completion with transparent fallback if model does not exist or is deprecated."""
        candidate_models = [self.model] + [m for m in FALLBACK_GROQ_MODELS if m != self.model]
        last_err = None
        for candidate in candidate_models:
            try:
                call_kwargs = kwargs.copy()
                call_kwargs["model"] = candidate
                res = await self.client.chat.completions.create(**call_kwargs)
                if candidate != self.model:
                    logger.warning(
                        f"GroqProvider: Switched active model from {self.model} to {candidate} due to model error."
                    )
                    self.model = candidate
                return res
            except NotFoundError as e:
                last_err = e
                continue
            except Exception as e:
                err_str = str(e).lower()
                if "model_not_found" in err_str or "does not exist" in err_str or "404" in err_str:
                    last_err = e
                    continue
                raise
        if last_err:
            raise last_err

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> str:
        messages = self._prepare_messages(prompt, system_prompt, history)
        response = await self._create_with_fallback(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.choices[0].message.content.strip()

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        messages = self._prepare_messages(prompt, system_prompt, history)
        response_stream = await self._create_with_fallback(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        async for chunk in response_stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    async def stream_messages(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        clean_messages = []
        for m in messages:
            msg: Dict[str, Any] = {"role": m.get("role"), "content": m.get("content") or ""}
            if m.get("role") == "tool" and m.get("tool_call_id"):
                msg["tool_call_id"] = m["tool_call_id"]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                msg["tool_calls"] = m["tool_calls"]
            clean_messages.append(msg)

        params: Dict[str, Any] = {
            "messages": clean_messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        response_stream = await self._create_with_fallback(**params)
        async for chunk in response_stream:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content

    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs
    ) -> Dict[str, Any]:
        openai_messages = self._convert_messages_for_openai(messages)
        response = await self._create_with_fallback(
            messages=openai_messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args
                })
        return {
            "content": choice.message.content,
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason
        }

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Overrides structured generation to use Groq JSON mode
        and manually parses response via Pydantic model validation.
        """
        pydantic_schema = response_model.model_json_schema()
        enhanced_prompt = (
            f"{prompt}\n\nReturn output ONLY in JSON matching this schema:\n"
            f"{json.dumps(pydantic_schema)}"
        )
        messages = self._prepare_messages(enhanced_prompt, system_prompt)
        response = await self._create_with_fallback(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            **kwargs
        )
        content = response.choices[0].message.content
        return response_model.model_validate_json(content)
