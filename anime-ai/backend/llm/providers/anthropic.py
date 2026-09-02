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
