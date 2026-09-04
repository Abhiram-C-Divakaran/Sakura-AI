import os
from typing import AsyncGenerator, List, Dict, Any, Optional
from anthropic import AsyncAnthropic
from llm.providers.base import LLMProvider

class AnthropicProvider(LLMProvider):
    """
    Anthropic API Adapter.
    Uses Anthropic's message-based structure for Claude.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-haiku-20240307"):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    def _prepare_messages_and_system(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> tuple[List[Dict[str, str]], Optional[str]]:
        messages = []
        if history:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})
        
        # Anthropic separates system prompt into its own top-level param
        return messages, system_prompt

    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> str:
        messages, system = self._prepare_messages_and_system(prompt, system_prompt, history)
        
        # Strip system role if present in messages (Anthropic does not allow 'system' in messages list)
        filtered_messages = [m for m in messages if m["role"] != "system"]
        
        response = await self.client.messages.create(
            model=self.model,
            messages=filtered_messages,
            system=system or "",
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.content[0].text

    async def stream(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        messages, system = self._prepare_messages_and_system(prompt, system_prompt, history)
        filtered_messages = [m for m in messages if m["role"] != "system"]
        
        async with self.client.messages.stream(
            model=self.model,
            messages=filtered_messages,
            system=system or "",
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Structured extraction utilizing standard JSON output instructions 
        and manual parsing validation.
        """
        pydantic_schema = response_model.model_json_schema()
        enhanced_prompt = (
            f"{prompt}\n\nReturn output ONLY as a valid JSON object matching this schema:\n"
            f"{__import__('json').dumps(pydantic_schema)}"
        )
        
        messages, system = self._prepare_messages_and_system(enhanced_prompt, system_prompt)
        filtered_messages = [m for m in messages if m["role"] != "system"]
        
        response = await self.client.messages.create(
            model=self.model,
            messages=filtered_messages,
            system=system or "",
            temperature=0.1,
            max_tokens=1000,
            **kwargs
        )
        
        content = response.content[0].text
        # Clean any potential markdown wrapper blocks
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
            
        return response_model.model_validate_json(content)

    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Translates OpenAI tool format and conversation structure to Anthropic native tools API,
        and returns normalized provider-neutral tool turn results.
        """
        system_prompt = ""
        claude_messages = []

        # 1. Translate tools to Anthropic format
        anthropic_tools = []
        for t in tools:
            if t.get("type") == "function":
                fn = t["function"]
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}})
                })

        # 2. Translate messages
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_prompt += (m.get("content") or "") + "\n"
            elif role == "user":
                claude_messages.append({"role": "user", "content": m.get("content") or ""})
            elif role == "assistant":
                content_blocks = []
                if m.get("content"):
                    content_blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    tc_args = tc.get("arguments", {})
                    if isinstance(tc_args, str):
                        try:
                            tc_args = __import__("json").loads(tc_args)
                        except Exception:
                            tc_args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "input": tc_args
                    })
                claude_messages.append({"role": "assistant", "content": content_blocks if content_blocks else ""})
            elif role == "tool":
                # In Anthropic, tool responses are user turns with tool_result blocks
                claude_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id"),
                        "content": str(m.get("content") or "")
                    }]
                })

        response = await self.client.messages.create(
            model=self.model,
            messages=claude_messages,
            system=system_prompt.strip() or "You are Sakura AI.",
            tools=anthropic_tools if anthropic_tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        text_content = ""
        tool_calls = []

        for block in response.content:
            if getattr(block, "type", "") == "text":
                text_content += block.text
            elif getattr(block, "type", "") == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input if isinstance(block.input, dict) else {}
                })

        finish_reason = "tool_calls" if tool_calls else ("stop" if response.stop_reason == "end_turn" else str(response.stop_reason))

        return {
            "content": text_content if text_content else None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason
        }
