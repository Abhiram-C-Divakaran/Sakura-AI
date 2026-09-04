import os
from typing import AsyncGenerator, List, Dict, Any, Optional
from openai import AsyncOpenAI
from llm.providers.base import LLMProvider

class OpenAIProvider(LLMProvider):
    """OpenAI API Adapter."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set.")
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    def _prepare_messages(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None, 
        history: Optional[List[Dict[str, str]]] = None
    ) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})
        return messages

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
        response = await self.client.chat.completions.create(
            model=self.model,
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
        response_stream = await self.client.chat.completions.create(
            model=self.model,
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
            "model": self.model,
            "messages": clean_messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        response_stream = await self.client.chat.completions.create(**params)
        async for chunk in response_stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        # Leverage OpenAI client library Pydantic validation (beta.chat.completions.parse)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=response_model,
            **kwargs
        )
        return response.choices[0].message.parsed

    def _convert_messages_for_openai(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Converts canonical provider-neutral messages to OpenAI API wire format."""
        import json
        converted = []
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                formatted_calls = []
                for tc in m["tool_calls"]:
                    if "function" in tc:
                        formatted_calls.append(tc)
                    else:
                        args = tc.get("arguments", {})
                        args_str = json.dumps(args) if isinstance(args, dict) else str(args)
                        formatted_calls.append({
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": args_str
                            }
                        })
                converted.append({
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": formatted_calls
                })
            elif role == "tool":
                converted.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": str(m.get("content") or "")
                })
            else:
                converted.append(m)
        return converted

    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs
    ) -> Dict[str, Any]:
        import json
        openai_messages = self._convert_messages_for_openai(messages)
        response = await self.client.chat.completions.create(
            model=self.model,
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
