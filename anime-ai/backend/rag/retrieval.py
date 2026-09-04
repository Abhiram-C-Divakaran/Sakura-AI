"""
Sakura AI — Hybrid RAG Retrieval Engine
Combines dense vector similarity searches with Okapi BM25 lexical ranking
using Reciprocal Rank Fusion (RRF). Strictly enforces user scoping and knowledge-base isolation.
"""
import math
import re
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from database.models import DocumentChunk, Document
from rag.embeddings.manager import EmbeddingManager


class BM25Scorer:
    """
    Production Okapi BM25 Ranking Algorithm.
    Computes probabilistic Inverse Document Frequency (IDF),
    term frequency saturation with k1 parameter, and document length normalization with b parameter.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    @staticmethod
    def tokenize(text: str) -> List[str]:
        return [t.lower() for t in re.findall(r'\b\w+\b', text or "") if len(t) > 1]

    def score_corpus(self, query: str, chunks: List[DocumentChunk]) -> List[Tuple[DocumentChunk, float]]:
        if not chunks:
            return []

        query_terms = self.tokenize(query)
        if not query_terms:
            return [(c, 0.0) for c in chunks]

        # 1. Document tokenization & lengths
        doc_tokens = [self.tokenize(c.content) for c in chunks]
        doc_lens = [len(tokens) for tokens in doc_tokens]
        total_docs = len(chunks)
        avgdl = sum(doc_lens) / total_docs if total_docs > 0 else 1.0

        # 2. Document frequency n(q) for each query term
        df = {}
        for q in query_terms:
            df[q] = sum(1 for tokens in doc_tokens if q in tokens)

        # 3. Calculate Robertson-Spärck Jones IDF for each query term:
        # ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1.0)
        idf = {}
        for q in query_terms:
            n_q = df[q]
            idf[q] = math.log(((total_docs - n_q + 0.5) / (n_q + 0.5)) + 1.0)

        # 4. Compute BM25 score for each document chunk
        scored = []
        for i, chunk in enumerate(chunks):
            tokens = doc_tokens[i]
            d_len = doc_lens[i]
            score = 0.0

            # Term counts in this document
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1

            for q in query_terms:
                term_freq = tf.get(q, 0)
                if term_freq > 0:
                    numerator = term_freq * (self.k1 + 1.0)
                    denominator = term_freq + self.k1 * (1.0 - self.b + self.b * (d_len / avgdl))
                    score += idf[q] * (numerator / denominator)

            if score > 0.0:
                scored.append((chunk, score))

        scored.sort(key=lambda x: -x[1])
        return scored


class HybridRetriever:
    """
    RAG Retrieval Engine. Combines vector similarity searches with
    true Okapi BM25 lexical ranking using Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, db: Session, embedding_manager: Optional[EmbeddingManager] = None):
        self.db = db
        self.embedding_manager = embedding_manager or EmbeddingManager()

    async def retrieve(
        self, 
        user_id: Any, 
        query_text: str, 
        limit: int = 5,
        rrf_k: int = 60,
        only_kb: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid semantic + Okapi BM25 query.
        Merges results using Reciprocal Rank Fusion (RRF).
        Strictly scopes search to documents owned by user_id that are indexed in the Knowledge Base.
        """
        query_text = (query_text or "").strip()
        if not query_text:
            return []

        query_embedding = self.embedding_manager.get_embedding(query_text)

        # 1. Fetch only documents owned by this user (strictly isolated, no leaking operator_zero)
        query = self.db.query(Document).filter(Document.user_id == user_id)
        if only_kb:
            query = query.filter(Document.is_knowledge_base == True)

        docs = query.all()
        if not docs:
            return []
        doc_ids = [d.id for d in docs]

        # 2. Get Vector/Semantic Matches (if embeddings are available)
        semantic_results = self._search_semantic(doc_ids, query_embedding, limit * 2) if query_embedding else []

        # 3. Get Okapi BM25 Matches
        keyword_results = self._search_keyword(doc_ids, query_text, limit * 2)

        # 4. Merge results using Reciprocal Rank Fusion (RRF)
        # RRF formula: Score(d) = SUM_m (1 / (k + rank_m(d)))
        rrf_scores = {}
        chunk_lookup = {}

        # Semantic ranking scoring
        for rank, chunk in enumerate(semantic_results):
            chunk_id = str(chunk.id)
            chunk_lookup[chunk_id] = chunk
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + (rank + 1)))

        # BM25 ranking scoring
        for rank, chunk in enumerate(keyword_results):
            chunk_id = str(chunk.id)
            chunk_lookup[chunk_id] = chunk
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + (rank + 1)))

        # Sort and select top chunks
        sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda x: -rrf_scores[x])
        top_chunk_ids = sorted_chunk_ids[:limit]

        # Build citations mapping source files
        results = []
        for cid in top_chunk_ids:
            chunk = chunk_lookup[cid]
            doc = next((d for d in docs if d.id == chunk.document_id), None)
            filename = doc.filename if doc else "Unknown Source"

            results.append({
                "chunk_id": cid,
                "content": chunk.content,
                "score": round(rrf_scores[cid], 4),
                "source": filename,
                "page": chunk.metadata_json.get("page_number") if chunk.metadata_json else None
            })

        return results

    def _search_semantic(self, doc_ids: List[Any], query_vec: Optional[List[float]], limit: int) -> List[DocumentChunk]:
        """Runs vector database search with cosine similarity."""
        if not query_vec or not doc_ids:
            return []

        try:
            from database.db import DATABASE_URL
            bind_url = DATABASE_URL
        except Exception:
            bind_url = "sqlite"

        if "postgresql" in bind_url:
            return (
                self.db.query(DocumentChunk)
                .filter(DocumentChunk.document_id.in_(doc_ids))
                .order_by(DocumentChunk.embedding.cosine_distance(query_vec))
                .limit(limit)
                .all()
            )

        # Fallback NumPy calculation for SQLite testing envs
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id.in_(doc_ids))
            .all()
        )
        if not chunks:
            return []

        q_arr = np.array(query_vec)
        matches = []
        for c in chunks:
            if c.embedding:
                c_arr = np.array(c.embedding)
                denom = np.linalg.norm(q_arr) * np.linalg.norm(c_arr)
                similarity = np.dot(q_arr, c_arr) / denom if denom > 0 else 0.0
                matches.append((c, similarity))

        matches.sort(key=lambda x: -x[1])
        return [m[0] for m in matches[:limit]]

    def _search_keyword(self, doc_ids: List[Any], query_text: str, limit: int) -> List[DocumentChunk]:
        """Runs true Okapi BM25 ranking across document chunks."""
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id.in_(doc_ids))
            .all()
        )
        if not chunks:
            return []

        scorer = BM25Scorer()
        scored_matches = scorer.score_corpus(query_text, chunks)
        return [m[0] for m in scored_matches[:limit]]
