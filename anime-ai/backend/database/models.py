import uuid
from sqlalchemy import Column, String, Float, ForeignKey, DateTime, Text, Boolean, Integer, JSON, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database.db import Base

def utc_now():
    return datetime.now(timezone.utc)

# Dynamic fallback if pgvector is not installed locally or running SQLite
import os
if os.getenv("DATABASE_URL", "").startswith("sqlite"):
    from sqlalchemy import JSON as Vector
    HAS_PGVECTOR = False
else:
    try:
        from pgvector.sqlalchemy import Vector
        HAS_PGVECTOR = True
    except ImportError:
        from sqlalchemy import JSON as Vector
        HAS_PGVECTOR = False

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    scheduled_tasks = relationship("ScheduledTask", back_populates="user", cascade="all, delete-orphan")
    background_tasks = relationship("BackgroundTask", back_populates="user", cascade="all, delete-orphan")
    integrations = relationship("UserIntegration", back_populates="user", cascade="all, delete-orphan")
    workspaces = relationship("RepositoryWorkspace", back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    storage_path = Column(String(510), nullable=False)
    metadata_json = Column(JSON, default=dict, name="metadata")
    is_knowledge_base = Column(Boolean, default=False, nullable=False, index=True)
    indexing_status = Column(String(50), default="UPLOADED", nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    user = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)  # OpenAI 1536 dims standard
    metadata_json = Column(JSON, default=dict, name="metadata")

    # Relationships
    document = relationship("Document", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id = Column(String(50), nullable=False, default="sakura")
    title = Column(String(255), default="New Conversation")
    pinned = Column(Boolean, default=False)
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    shares = relationship("ConversationShare", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system', 'tool'
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, default=dict, name="metadata")
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    feedbacks = relationship("MessageFeedback", back_populates="message", cascade="all, delete-orphan")


class MessageFeedback(Base):
    __tablename__ = "message_feedbacks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(String(50), nullable=False)  # "positive", "negative", "1", "-1"
    reason = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    message = relationship("Message", back_populates="feedbacks")
    user = relationship("User")


class ConversationShare(Base):
    __tablename__ = "conversation_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    share_token = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    conversation = relationship("Conversation", back_populates="shares")
    user = relationship("User", foreign_keys=[user_id])


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False)  # 'preference', 'fact', 'biography'
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="memories")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)

    prompt = Column(Text, nullable=False)
    enhanced_prompt = Column(Text, nullable=True)
    aspect_ratio = Column(String(20), default="1:1")
    width = Column(Integer, default=1024)
    height = Column(Integer, default=1024)
    model = Column(String(100), default="flux-realism")
    seed = Column(Integer, nullable=True)
    workflow = Column(String(50), default="TEXT_TO_IMAGE")

    parent_image_id = Column(UUID(as_uuid=True), ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True)
    lineage_depth = Column(Integer, default=0)

    storage_path = Column(String(510), nullable=False)
    image_url = Column(String(510), nullable=False)
    metadata_json = Column(JSON, default=dict, name="metadata")
    created_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User")
    conversation = relationship("Conversation")
    document = relationship("Document")
    parent_image = relationship("GeneratedImage", remote_side=[id])


# ─── Projects ─────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, default="")
    instructions = Column(Text, default="")
    metadata_json = Column(JSON, default=dict, name="metadata")
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="projects")
    repositories = relationship("ProjectRepository", back_populates="project", cascade="all, delete-orphan")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("ProjectConversation", back_populates="project", cascade="all, delete-orphan")


class ProjectRepository(Base):
    __tablename__ = "project_repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_url = Column(String(500), nullable=False)
    branch = Column(String(100), default="main")
    name = Column(String(150), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="repositories")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="files")
    document = relationship("Document")


class ProjectConversation(Base):
    __tablename__ = "project_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="conversations")
    conversation = relationship("Conversation")


# ─── Scheduled Tasks ───────────────────────────────────────────────────────

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    prompt = Column(Text, nullable=False)
    schedule = Column(String(100), nullable=False)  # e.g. "every day at 9am", cron, or timestamp
    timezone = Column(String(50), default="UTC")
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, default=dict, name="metadata")
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="scheduled_tasks")
    runs = relationship("ScheduledTaskRun", back_populates="task", cascade="all, delete-orphan")


class ScheduledTaskRun(Base):
    __tablename__ = "scheduled_task_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="RUNNING")  # RUNNING, COMPLETED, FAILED
    scheduled_for = Column(DateTime(timezone=True), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    output = Column(Text, nullable=True)
    duration_ms = Column(Integer, default=0)

    task = relationship("ScheduledTask", back_populates="runs")

    __table_args__ = (
        UniqueConstraint("task_id", "scheduled_for", name="uq_scheduled_task_run_occurrence"),
        Index("ix_scheduled_task_runs_task_occurrence", "task_id", "scheduled_for", unique=True),
    )


class TaskOutcome:
    QUEUED = "Queued"
    EXPLORING = "Exploring"
    PLANNING = "Planning"
    IMPLEMENTING = "Implementing"
    TESTING = "Testing"
    REVIEWING = "Reviewing"
    COMPLETED_VERIFIED = "Completed_Verified"
    COMPLETED_UNVERIFIED = "Completed_Unverified"
    FAILED = "Failed"
    BLOCKED = "Blocked"
    MAX_ITERATIONS = "Max_Iterations"
    CANCELLED = "Cancelled"


# ─── Integrations (e.g. GitHub) ───────────────────────────────────────────

class UserIntegration(Base):
    __tablename__ = "user_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # 'github', 'notion', 'postgres', etc.
    account_name = Column(String(150), nullable=True)
    connected = Column(Boolean, default=False)
    config_json = Column(JSON, default=dict, name="config")
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="integrations")


# ─── Frontier Coding Workspaces & Execution ──────────────────────────────

class RepositoryWorkspace(Base):
    __tablename__ = "repository_workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    repository_url = Column(String(500), nullable=True)
    workspace_path = Column(String(500), nullable=False)
    active_branch = Column(String(100), default="main")
    base_commit = Column(String(64), nullable=True)
    status = Column(String(50), default="READY")  # READY, CLONING, INDEXING, ERROR
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="workspaces")
    tasks = relationship("CodingTask", back_populates="workspace", cascade="all, delete-orphan")


class CodingTask(Base):
    __tablename__ = "coding_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("repository_workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    status = Column(String(50), default="QUEUED")  # QUEUED, EXPLORING, IMPLEMENTING, TESTING, COMPLETED, FAILED, CANCELLED
    files_modified = Column(JSON, default=list)
    verification_summary = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    workspace = relationship("RepositoryWorkspace", back_populates="tasks")
    executions = relationship("ToolExecution", back_populates="task", cascade="all, delete-orphan")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coding_task_id = Column(UUID(as_uuid=True), ForeignKey("coding_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False)
    arguments = Column(JSON, default=dict)
    status = Column(String(50), default="SUCCESS")  # SUCCESS, FAILED, TIMEOUT
    stdout_preview = Column(Text, nullable=True)
    stderr_preview = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    task = relationship("CodingTask", back_populates="executions")


# ─── Durable Background Tasks ──────────────────────────────────────────────

class BackgroundTask(Base):
    __tablename__ = "background_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String(50), nullable=False, default="Queued", index=True)
    progress = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    result_metadata = Column(JSON, default=dict)
    retry_count = Column(Integer, default=0)
    worker_id = Column(String(100), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="background_tasks")

    def to_dict(self):
        return {
            "id": str(self.id),
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "result": self.result,
            "payload": self.payload or {},
            "userId": str(self.user_id),
            "retryCount": self.retry_count,
            "workerId": self.worker_id,
            "leaseExpiresAt": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "cancelRequested": self.cancel_requested,
            "resultMetadata": self.result_metadata or {},
        }
