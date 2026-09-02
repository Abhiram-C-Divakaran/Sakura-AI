import uuid
from sqlalchemy import Column, String, Float, ForeignKey, DateTime, Text, Boolean, Integer, UUID, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from database.db import Base

# Dynamic fallback if pgvector is not installed locally
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    from sqlalchemy import PickleType as Vector
    HAS_PGVECTOR = False

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    storage_path = Column(String(510), nullable=False)
    metadata_json = Column(JSON, default={}, name="metadata")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)  # OpenAI 1536 dims standard
    metadata_json = Column(JSON, default={}, name="metadata")

    # Relationships
    document = relationship("Document", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(String(50), nullable=False, default="sakura")
    title = Column(String(255), default="New Conversation")
    pinned = Column(Boolean, default=False)
    pinned_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system', 'tool'
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, default={}, name="metadata")  # Stores emotional states, latency, citations
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    memory_type = Column(String(50), nullable=False)  # 'preference', 'fact', 'biography'
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="memories")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    config = Column(JSON, default={})  # Personality, speech styles, catchphrases
    created_at = Column(DateTime, default=datetime.utcnow)


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)

    prompt = Column(Text, nullable=False)
    enhanced_prompt = Column(Text, nullable=True)
    aspect_ratio = Column(String(20), default="1:1")
    width = Column(Integer, default=1024)
    height = Column(Integer, default=1024)
    model = Column(String(100), default="flux-realism")
    seed = Column(Integer, nullable=True)
    workflow = Column(String(50), default="TEXT_TO_IMAGE")  # TEXT_TO_IMAGE, EDIT_IMAGE, VARIATION, UPSCALE

    parent_image_id = Column(UUID(as_uuid=True), ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True)
    lineage_depth = Column(Integer, default=0)

    storage_path = Column(String(510), nullable=False)
    image_url = Column(String(510), nullable=False)
    metadata_json = Column(JSON, default={}, name="metadata")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
    conversation = relationship("Conversation")
    document = relationship("Document")
    parent_image = relationship("GeneratedImage", remote_side=[id])

