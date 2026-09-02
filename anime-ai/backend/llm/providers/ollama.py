import os
from typing import Optional, Any
from openai import AsyncOpenAI
from llm.providers.openai import OpenAIProvider

class OllamaProvider(OpenAIProvider):
    """
    Ollama Local API Adapter. Targets Ollama's local OpenAI-compatible
    endpoint at http://localhost:11434/v1 for local/private inference.
    """

    def __init__(self, base_url: Optional[str] = None, model: str = "llama3"):
        base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        # Format suffix for OpenAI API client route compatibility
        if not base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/v1"

        self.client = AsyncOpenAI(
            api_key="ollama",  # Dummy value for client library assertion checks
            base_url=base_url
        )
        self.model = model

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Manually injects schema structure and uses manual json validation
        for local models.
        """
        pydantic_schema = response_model.model_json_schema()
        enhanced_prompt = (
            f"{prompt}\n\nReturn output ONLY as a valid JSON object matching this schema:\n"
            f"{__import__('json').dumps(pydantic_schema)}"
        )
        
        messages = self._prepare_messages(enhanced_prompt, system_prompt)
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            **kwargs
        )
        
        content = response.choices[0].message.content
        return response_model.model_validate_json(content)
