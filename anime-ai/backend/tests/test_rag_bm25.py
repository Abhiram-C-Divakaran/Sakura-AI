import unittest
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import Base, engine, get_db_context
from database.models import User, Document, DocumentChunk
from rag.retrieval import HybridRetriever, BM25Scorer


class DummyChunk:
    def __init__(self, id, content):
        self.id = id
        self.content = content


class TestRAGBM25(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        self.user1_id = uuid.uuid4()
        self.user2_id = uuid.uuid4()
        with get_db_context() as db:
            u1 = User(id=self.user1_id, username=f"rag_u1_{uuid.uuid4().hex[:8]}", hashed_password="pw")
            u2 = User(id=self.user2_id, username=f"rag_u2_{uuid.uuid4().hex[:8]}", hashed_password="pw")
            db.add_all([u1, u2])
            db.commit()

    def test_okapi_bm25_vs_naive_term_counting(self):
        """
        Demonstrates that Okapi BM25 ranks concise, high-IDF matches higher than
        repetitive keyword spamming, unlike naive occurrence counting.
        """
        scorer = BM25Scorer(k1=1.5, b=0.75)

        # Chunk 1 repeats common word "system" 10 times, but misses specific query keyword "postgresql"
        chunk1 = DummyChunk(
            1,
            "system system system system system system system system system system general architecture."
        )
        # Chunk 2 has specific term "postgresql" (rare in corpus) and "system"
        chunk2 = DummyChunk(
            2,
            "The postgresql database system stores transactions reliably."
        )
        # Chunk 3 has neither
        chunk3 = DummyChunk(
            3,
            "Frontend React components render pitch-black user interfaces."
        )

        corpus = [chunk1, chunk2, chunk3]
        query = "system postgresql"

        # Naive token counting score:
        # chunk1: count("system") = 10, count("postgresql") = 0 -> Score: 10
        # chunk2: count("system") = 1, count("postgresql") = 1 -> Score: 2
        # Naive counting would rank chunk1 FIRST!
        naive_chunk1_score = chunk1.content.lower().count("system") + chunk1.content.lower().count("postgresql")
        naive_chunk2_score = chunk2.content.lower().count("system") + chunk2.content.lower().count("postgresql")
        self.assertGreater(naive_chunk1_score, naive_chunk2_score)

        # Okapi BM25 scoring:
        scored = scorer.score_corpus(query, corpus)
        top_chunk, top_score = scored[0]

        # Chunk 2 MUST rank first in true Okapi BM25 because "postgresql" has high IDF
        # and chunk 1's "system" spam is saturated by k1 and penalized by b length normalization
        self.assertEqual(top_chunk.id, 2)
        self.assertGreater(top_score, scored[1][1])

    async def test_knowledge_base_vs_library_isolation(self):
        """
        Only documents explicitly marked is_knowledge_base=True should be retrieved by HybridRetriever.
        Regular uploaded library files must remain non-searchable in RAG until indexed.
        """
        with get_db_context() as db:
            # 1. Regular library file (is_knowledge_base=False)
            lib_doc = Document(
                id=uuid.uuid4(),
                user_id=self.user1_id,
                filename="private_notes.txt",
                mime_type="text/plain",
                storage_path="/tmp/fake1",
                is_knowledge_base=False,
                indexing_status="UPLOADED"
            )
            # 2. Knowledge base document (is_knowledge_base=True)
            kb_doc = Document(
                id=uuid.uuid4(),
                user_id=self.user1_id,
                filename="system_architecture.md",
                mime_type="text/markdown",
                storage_path="/tmp/fake2",
                is_knowledge_base=True,
                indexing_status="READY"
            )
            db.add_all([lib_doc, kb_doc])
            db.commit()

            c1 = DocumentChunk(
                id=uuid.uuid4(),
                document_id=lib_doc.id,
                chunk_index=0,
                content="Confidential library document about project secret design."
            )
            c2 = DocumentChunk(
                id=uuid.uuid4(),
                document_id=kb_doc.id,
                chunk_index=0,
                content="System architecture blueprint with microservices and API gateways."
            )
            db.add_all([c1, c2])
            db.commit()

            retriever = HybridRetriever(db)
            results = await retriever.retrieve(self.user1_id, "secret project design", only_kb=True)

            # lib_doc was NOT marked is_knowledge_base, so it must NOT be retrieved
            self.assertEqual(len(results), 0)

            # Search for KB content
            kb_results = await retriever.retrieve(self.user1_id, "system architecture microservices", only_kb=True)
            self.assertEqual(len(kb_results), 1)
            self.assertEqual(kb_results[0]["source"], "system_architecture.md")

    async def test_user_scoping_no_cross_tenant_leakage(self):
        """User B cannot retrieve User A's knowledge base chunks."""
        with get_db_context() as db:
            kb_doc = Document(
                id=uuid.uuid4(),
                user_id=self.user1_id,
                filename="user1_strategy.md",
                mime_type="text/markdown",
                storage_path="/tmp/fake3",
                is_knowledge_base=True,
                indexing_status="READY"
            )
            db.add(kb_doc)
            db.commit()

            c = DocumentChunk(
                id=uuid.uuid4(),
                document_id=kb_doc.id,
                chunk_index=0,
                content="Enterprise security strategies and firewall rules."
            )
            db.add(c)
            db.commit()

            retriever = HybridRetriever(db)
            # User 2 queries
            user2_results = await retriever.retrieve(self.user2_id, "firewall rules security", only_kb=True)
            self.assertEqual(len(user2_results), 0)


if __name__ == "__main__":
    unittest.main()
