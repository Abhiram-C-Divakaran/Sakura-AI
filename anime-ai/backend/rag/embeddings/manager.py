"""
Sakura AI — RAG Vector Embedding Manager

Generates true semantic embeddings using configured embedding providers.
Strictly eliminates mock/fake embeddings when unconfigured, allowing
RAG pipelines to truthfully fall back to lexical BM25 matching.
"""
import os
from openai import OpenAI
from typing import List, Optional

class EmbeddingManager:
    """
    Manages vector embeddings generation using OpenAI text-embedding-3-small (1536 dimensions).
    Does NOT generate fake or random mock embeddings when unconfigured.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client: Optional[OpenAI] = None
        if self.api_key:
            try:
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                print(f"EmbeddingManager: Failed to initialize OpenAI client: {e}")

    @property
    def is_available(self) -> bool:
        """Returns True only if a valid embedding provider is configured."""
        return self.client is not None

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Generates embedding vector for a single text string, or None if unavailable."""
        if not self.client:
            return None

        try:
            response = self.client.embeddings.create(
                input=[text.replace("\n", " ")],
                model="text-embedding-3-small"
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"EmbeddingManager API Error: {e}")
            return None

    def get_embeddings(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Batch generates embeddings for multiple strings, or list of None if unavailable."""
        if not self.client:
            return [None for _ in texts]

        try:
            cleaned_texts = [t.replace("\n", " ") for t in texts]
            response = self.client.embeddings.create(
                input=cleaned_texts,
                model="text-embedding-3-small"
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            print(f"EmbeddingManager Batch API Error: {e}")
            return [None for _ in texts]
