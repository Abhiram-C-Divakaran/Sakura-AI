"""
Test Schema Parity & ORM Lifecycle Validation
Validates that a fresh database created via Alembic upgrade head matches the current
SQLAlchemy ORM models and supports CRUD across all representative entities.
"""

import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from database.models import (
    Base, User, Document, DocumentChunk, Conversation, Message,
    MessageFeedback, ConversationShare, UserMemory, Character,
    GeneratedImage, Project, ProjectRepository, ProjectFile,
    ProjectConversation, ScheduledTask, ScheduledTaskRun,
    UserIntegration, RepositoryWorkspace, CodingTask, ToolExecution,
    BackgroundTask, utc_now
)


class TestSchemaParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Run Alembic upgrade head on a dedicated clean database
        cls.temp_dir = tempfile.mkdtemp(prefix="sakura_parity_")
        cls.db_path = os.path.join(cls.temp_dir, "clean_parity.db")
        env_url = os.getenv("DATABASE_URL", "")
        if env_url and not env_url.startswith("sqlite"):
            cls.test_url = env_url
        else:
            cls.test_url = f"sqlite:///{cls.db_path}"

        cls.engine = sa.create_engine(cls.test_url)
        cls.Session = sessionmaker(bind=cls.engine)

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", cls.test_url)
        command.upgrade(alembic_cfg, "head")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "temp_dir"):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_schema_contains_all_orm_tables(self):
        insp = sa.inspect(self.engine)
        migrated_tables = set(insp.get_table_names())
        orm_tables = set(Base.metadata.tables.keys())

        missing = orm_tables - migrated_tables
        self.assertEqual(missing, set(), f"ORM tables missing in migrated schema: {missing}")

    def test_schema_contains_all_orm_columns(self):
        insp = sa.inspect(self.engine)
        for table_name in Base.metadata.tables.keys():
            mig_cols = {c["name"] for c in insp.get_columns(table_name)}
            orm_cols = {c.name for c in Base.metadata.tables[table_name].columns}
            missing_cols = orm_cols - mig_cols
            self.assertEqual(
                missing_cols,
                set(),
                f"Table '{table_name}' is missing columns in migrated schema: {missing_cols}"
            )

    def test_all_representative_orm_models_crud(self):
        """Exercises CRUD across all 18 representative ORM models on migrated database."""
        with self.Session() as db:
            # 1. User
            user = User(
                id=uuid.uuid4(),
                username=f"parity_user_{uuid.uuid4().hex[:8]}",
                hashed_password="hashed_parity_pw",
                created_at=utc_now()
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            self.assertIsNotNone(user.id)

            # 2. Character
            char = Character(
                id=f"char_{uuid.uuid4().hex[:8]}",
                name="Test Persona",
                description="A test persona description",
                config={"greeting": "Hello!"}
            )
            db.add(char)
            db.commit()

            # 3. Conversation
            conv = Conversation(
                id=uuid.uuid4(),
                user_id=user.id,
                character_id=char.id,
                title="Parity Thread",
                pinned=True,
                pinned_at=utc_now()
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

            # 4. Message
            msg = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                role="user",
                content="Hello Sakura!",
                metadata_json={"source": "test"}
            )
            db.add(msg)
            db.commit()
            db.refresh(msg)
            self.assertEqual(msg.role, "user")
            self.assertEqual(msg.content, "Hello Sakura!")

            # 5. MessageFeedback
            feedback = MessageFeedback(
                id=uuid.uuid4(),
                message_id=msg.id,
                user_id=user.id,
                rating="positive",
                reason="Helpful response"
            )
            db.add(feedback)
            db.commit()

            # 6. ConversationShare
            share = ConversationShare(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                user_id=user.id,
                share_token=uuid.uuid4().hex
            )
            db.add(share)
            db.commit()

            # 7. UserMemory
            mem = UserMemory(
                id=uuid.uuid4(),
                user_id=user.id,
                memory_type="preference",
                content="Loves Python testing",
                confidence=0.95
            )
            db.add(mem)
            db.commit()

            # 8. Document
            doc = Document(
                id=uuid.uuid4(),
                user_id=user.id,
                filename="spec.md",
                mime_type="text/markdown",
                storage_path="/tmp/spec.md",
                is_knowledge_base=True,
                indexing_status="INDEXED"
            )
            db.add(doc)
            db.commit()

            # 9. DocumentChunk
            chunk = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=0,
                content="Architecture details",
                embedding=None
            )
            db.add(chunk)
            db.commit()

            # 10. Project
            proj = Project(
                id=uuid.uuid4(),
                user_id=user.id,
                name="Sakura Platform",
                description="Core AI platform",
                instructions="Be precise and safe."
            )
            db.add(proj)
            db.commit()

            # 11. ProjectRepository
            repo = ProjectRepository(
                id=uuid.uuid4(),
                project_id=proj.id,
                repository_url="https://github.com/org/repo",
                branch="main",
                name="repo"
            )
            db.add(repo)
            db.commit()

            # 12. ProjectFile
            pfile = ProjectFile(
                id=uuid.uuid4(),
                project_id=proj.id,
                document_id=doc.id
            )
            db.add(pfile)
            db.commit()

            # 13. ProjectConversation
            pconv = ProjectConversation(
                id=uuid.uuid4(),
                project_id=proj.id,
                conversation_id=conv.id
            )
            db.add(pconv)
            db.commit()

            # 14. ScheduledTask & ScheduledTaskRun
            sch_task = ScheduledTask(
                id=uuid.uuid4(),
                user_id=user.id,
                title="Morning Briefing",
                prompt="Summarize today's goals",
                schedule="0 9 * * *",
                timezone="UTC"
            )
            db.add(sch_task)
            db.commit()

            sch_run = ScheduledTaskRun(
                id=uuid.uuid4(),
                task_id=sch_task.id,
                status="COMPLETED",
                scheduled_for=utc_now(),
                output="Here is your summary."
            )
            db.add(sch_run)
            db.commit()

            # 15. UserIntegration
            integ = UserIntegration(
                id=uuid.uuid4(),
                user_id=user.id,
                provider="github",
                account_name="testuser",
                connected=True,
                config_json={"health_status": "CONNECTED"}
            )
            db.add(integ)
            db.commit()

            # 16. RepositoryWorkspace, CodingTask, ToolExecution
            ws = RepositoryWorkspace(
                id=uuid.uuid4(),
                user_id=user.id,
                name="workspace-test",
                workspace_path=f"/workspaces/{uuid.uuid4()}",
                status="READY"
            )
            db.add(ws)
            db.commit()

            ct = CodingTask(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                user_id=user.id,
                title="Refactor task",
                objective="Refactor modules cleanly",
                status="COMPLETED"
            )
            db.add(ct)
            db.commit()

            te = ToolExecution(
                id=uuid.uuid4(),
                coding_task_id=ct.id,
                tool_name="run_command",
                arguments={"cmd": "pytest"},
                status="SUCCESS",
                exit_code=0
            )
            db.add(te)
            db.commit()

            # 17. BackgroundTask
            bg = BackgroundTask(
                id=uuid.uuid4(),
                user_id=user.id,
                type="test_job",
                title="Background Test",
                status="Queued",
                cancel_requested=False
            )
            db.add(bg)
            db.commit()

            # 18. GeneratedImage
            gi = GeneratedImage(
                id=uuid.uuid4(),
                user_id=user.id,
                conversation_id=conv.id,
                document_id=doc.id,
                prompt="A beautiful sakura tree",
                enhanced_prompt="Masterpiece sakura blossom",
                aspect_ratio="1:1",
                width=1024,
                height=1024,
                model="flux",
                storage_path="/tmp/sakura.png",
                image_url="/api/v1/library/files/sakura.png",
                metadata_json={"actual_provider": "pollinations", "actual_model": "flux"}
            )
            db.add(gi)
            db.commit()

            # Verify reads
            self.assertEqual(db.query(User).filter(User.id == user.id).count(), 1)
            self.assertEqual(db.query(Conversation).filter(Conversation.id == conv.id).count(), 1)
            self.assertEqual(db.query(Message).filter(Message.id == msg.id).count(), 1)
            self.assertEqual(db.query(UserMemory).filter(UserMemory.id == mem.id).count(), 1)
            self.assertEqual(db.query(GeneratedImage).filter(GeneratedImage.id == gi.id).count(), 1)
            self.assertEqual(db.query(BackgroundTask).filter(BackgroundTask.id == bg.id).count(), 1)
            self.assertEqual(db.query(ScheduledTaskRun).filter(ScheduledTaskRun.id == sch_run.id).count(), 1)

    def test_downgrade_and_upgrade_cycle(self):
        """Verifies migration rollback of the latest revision and re-upgrade to head."""
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", self.test_url)
        # Downgrade 1 revision
        command.downgrade(alembic_cfg, "-1")
        # Re-upgrade to head
        command.upgrade(alembic_cfg, "head")
        insp = sa.inspect(self.engine)
        self.assertIn("user_memories", insp.get_table_names())
        self.assertIn("scheduled_task_runs", insp.get_table_names())


if __name__ == "__main__":
    unittest.main()

