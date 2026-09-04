import numpy as np
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database.models import DocumentChunk, Document
from rag.embeddings.manager import EmbeddingManager

class HybridRetriever:
    """
    RAG Retrieval Engine. Combines vector similarity searches with
    keyword matches using Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, db: Session, embedding_manager: Optional[EmbeddingManager] = None):
        self.db = db
        self.embedding_manager = embedding_manager or EmbeddingManager()

    async def retrieve(
        self, 
        user_id: Any, 
        query_text: str, 
        limit: int = 5,
        rrf_k: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid semantic + keyword query. 
        Merges results using Reciprocal Rank Fusion.
        """
        query_embedding = self.embedding_manager.get_embedding(query_text)
        
        # 1. Fetch all documents for this user OR system user (operator_zero) to filter scope
        from database.models import User
        sys_user = self.db.query(User).filter_by(username="operator_zero").first()
        sys_user_id = sys_user.id if sys_user else None

        docs = self.db.query(Document).filter(
            (Document.user_id == user_id) | (Document.user_id == sys_user_id)
        ).all()
        if not docs:
            return []
        doc_ids = [d.id for d in docs]

        # 2. Get Vector/Semantic Matches (if embeddings are available)
        semantic_results = self._search_semantic(doc_ids, query_embedding, limit * 2) if query_embedding else []

        # 3. Get Keyword/BM25 Matches
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

        # Keyword ranking scoring
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
        """Runs vector database search, with CPU-level numpy fallback for local SQLite testing."""
        if not query_vec or not doc_ids:
            return []

        # Check connection type (SQLite vs Postgres)
        try:
            from database.db import DATABASE_URL
            bind_url = DATABASE_URL
        except Exception:
            bind_url = "sqlite"
        
        if "postgresql" in bind_url:
            # Native PostgreSQL pgvector cosine distance search
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
        """Simple text-normalizing tf keyword matching search."""
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id.in_(doc_ids))
            .all()
        )
        if not chunks:
            return []

        query_tokens = set(query_text.lower().split())
        matches = []
        for c in chunks:
            content_lower = c.content.lower()
            # Calculate overlapping tokens score
            score = sum(content_lower.count(token) for token in query_tokens)
            if score > 0:
                matches.append((c, score))

        matches.sort(key=lambda x: -x[1])
        return [m[0] for m in matches[:limit]]
