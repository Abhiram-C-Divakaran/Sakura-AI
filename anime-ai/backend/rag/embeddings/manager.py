import os
import numpy as np
from openai import OpenAI
from typing import List, Optional

class EmbeddingManager:
    """
    Manages vector embeddings generation. Uses OpenAI text-embedding-3-small
    by default (1536 dimensions) with graceful fallback to random mock vector generation.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = None
        if self.api_key:
            try:
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                print(f"EmbeddingManager: Failed to initialize OpenAI client: {e}")

    def get_embedding(self, text: str) -> List[float]:
        """Generates embedding vector for a single text string."""
        if self.client:
            try:
                response = self.client.embeddings.create(
                    input=[text.replace("\n", " ")],
                    model="text-embedding-3-small"
                )
                return response.data[0].embedding
            except Exception as e:
                print(f"EmbeddingManager API Error: {e}. Falling back to deterministic mock vector.")
        
        return self._generate_mock_embedding(text)

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Batch generates embeddings for multiple strings."""
        if self.client:
            try:
                cleaned_texts = [t.replace("\n", " ") for t in texts]
                response = self.client.embeddings.create(
                    input=cleaned_texts,
                    model="text-embedding-3-small"
                )
                return [d.embedding for d in response.data]
            except Exception as e:
                print(f"EmbeddingManager Batch API Error: {e}. Generating mock vectors.")

        return [self._generate_mock_embedding(t) for t in texts]

    def _generate_mock_embedding(self, text: str) -> List[float]:
        """
        Generates a deterministic 1536-dimensional mock embedding based on string hash.
        Normalized to unit length for cosine similarity compatibility.
        """
        state = sum(ord(c) for c in text)
        np.random.seed(state)
        vector = np.random.randn(1536)
        normalized = vector / np.linalg.norm(vector)
        return normalized.tolist()
