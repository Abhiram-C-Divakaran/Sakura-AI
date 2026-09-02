from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.models import UserMemory
from llm.router import LLMRouter

class ExtractedMemory(BaseModel):
    memory_type: str = Field(..., description="E.g. 'preference' (like coding languages, explanation formats) or 'fact' (like name, location, occupation).")
    content: str = Field(..., description="The factual/preference statement, written in third person. E.g. 'User lives in Neo-Tokyo' or 'User prefers concise coding tutorials'.")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0 based on how explicit the statement was.")

class MemoryExtractionResult(BaseModel):
    memories: List[ExtractedMemory]


class MemoryManager:
    """
    Manages three-tier memory architecture:
    - Short-term (loaded conversation context)
    - Episodic (summaries of historical conversations)
    - Semantic (long-term user facts and preferences extracted via LLM structured analysis)
    """

    def __init__(self, db: Session, router: Optional[LLMRouter] = None):
        self.db = db
        self.router = router or LLMRouter()

    def get_relevant_memories(self, user_id: Any, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetches semantic memories relevant to the current query.
        Uses simple keyword matching over user-stored semantic memory blocks.
        """
        memories = self.db.query(UserMemory).filter(UserMemory.user_id == user_id).all()
        if not memories:
            return []

        query_tokens = set(query_text.lower().split())
        scored = []
        for m in memories:
            m_text = m.content.lower()
            overlap = sum(m_text.count(token) for token in query_tokens)
            if overlap > 0:
                scored.append((m, overlap))

        # Fallback to returning most recent memories if no keyword match
        if not scored:
            scored = [(m, 0) for m in memories[-limit:]]

        scored.sort(key=lambda x: -x[1])
        return [
            {
                "memory_type": m[0].memory_type,
                "content": m[0].content,
                "confidence": m[0].confidence
            }
            for m in scored[:limit]
        ]

    async def extract_and_save_memories(self, user_id: Any, recent_messages: List[Dict[str, str]]) -> int:
        """
        Analyzes recent conversation history to extract important user facts/preferences,
        and saves them into the user_memories database.
        """
        if len(recent_messages) < 2:
            return 0  # Not enough context

        history_text = ""
        for msg in recent_messages[-6:]:  # Analyze last 6 interactions
            history_text += f"{msg['role'].capitalize()}: {msg['content']}\n"

        prompt = (
            f"Analyze the following conversation context and extract long-term user facts "
            f"or preferences that are worth remembering for future sessions.\n\n"
            f"Conversation History:\n{history_text}\n"
            f"Extract only factual details or explicitly stated preferences. If nothing is worth "
            f"remembering, return an empty memories list."
        )

        system_prompt = (
            "You are a cognitive processor for an AI agent memory system. Your goal is to "
            "identify name, location, preferences, or core user attributes. Extract written statements "
            "in third-person. Assign a confidence score based on explicitness."
        )

        try:
            # We use structured generation to ensure valid JSON schema adherence
            result: MemoryExtractionResult = await self.router.providers["openai" if "openai" in self.router.providers else "groq"].generate_structured(
                prompt=prompt,
                response_model=MemoryExtractionResult,
                system_prompt=system_prompt
            )
        except Exception as e:
            print(f"Memory extraction failed: {e}. Skipping memory consolidation.")
            return 0

        saved_count = 0
        if result and result.memories:
            for mem in result.memories:
                if mem.confidence > 0.6:
                    # Deduplicate: Check if a similar memory exists
                    existing = self.db.query(UserMemory).filter(
                        UserMemory.user_id == user_id,
                        UserMemory.content.like(f"%{mem.content[:15]}%")
                    ).first()

                    if not existing:
                        new_mem = UserMemory(
                            user_id=user_id,
                            memory_type=mem.memory_type,
                            content=mem.content,
                            confidence=mem.confidence
                        )
                        self.db.add(new_mem)
                        saved_count += 1
            
            if saved_count > 0:
                self.db.commit()

        return saved_count
