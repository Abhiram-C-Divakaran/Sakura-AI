import os
from typing import Optional, Any
from openai import AsyncOpenAI
from llm.providers.openai import OpenAIProvider

class GroqProvider(OpenAIProvider):
    """
    Groq API Adapter. Uses OpenAI SDK client structure
    but targets Groq's low-latency execution endpoints.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "qwen/qwen3.8-27b"):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set.")
        
        # Instantiate AsyncOpenAI client pointed at Groq
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
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
        Overrides structured generation to use Groq JSON mode
        and manually parses response via Pydantic model validation.
        """
        # Append JSON formatting rules to user prompt
        pydantic_schema = response_model.model_json_schema()
        enhanced_prompt = (
            f"{prompt}\n\nReturn output ONLY in JSON matching this schema:\n"
            f"{__import__('json').dumps(pydantic_schema)}"
        )
        
        messages = self._prepare_messages(enhanced_prompt, system_prompt)
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,  # Low temp for structured adherence
            **kwargs
        )
        
        content = response.choices[0].message.content
        return response_model.model_validate_json(content)
