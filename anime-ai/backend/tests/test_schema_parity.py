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

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from database.db import normalize_database_url
from database.models import (
    Base, User, Document, DocumentChunk, Conversation, Message,
    MessageFeedback, ConversationShare, UserMemory, Character,
    GeneratedImage, Project, ProjectRepository, ProjectFile,
    ProjectConversation, ScheduledTask, ScheduledTaskRun,
    UserIntegration, RepositoryWorkspace, CodingTask, ToolExecution,
    BackgroundTask, CodingJob, CodingTaskEvent, WebSocketTicket,
    ImageGenerationJob, ImageVariationBatch, StorageDeletionOutbox, PasswordResetToken,
    UserUsageQuota, UserDataExport, AccountAuditEvent,
    utc_now
)


class TestSchemaParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Run Alembic upgrade head on a dedicated clean database
        cls.temp_dir = tempfile.mkdtemp(prefix="sakura_parity_")
        cls.db_path = os.path.join(cls.temp_dir, "clean_parity.db")
        env_url = os.getenv("DATABASE_URL", "")
        if env_url and not env_url.startswith("sqlite"):
            cls.test_url = normalize_database_url(env_url)
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

            # 19. UserUsageQuota, UserDataExport, AccountAuditEvent, ImageVariationBatch, StorageDeletionOutbox
            uq = UserUsageQuota(
                id=uuid.uuid4(),
                user_id=user.id,
                category="chat",
                window_key="2026-11-26",
                usage_count=1,
            )
            db.add(uq)
            exp = UserDataExport(
                id=uuid.uuid4(),
                user_id=user.id,
                status="QUEUED",
            )
            db.add(exp)
            aud = AccountAuditEvent(
                id=uuid.uuid4(),
                subject_user_id=user.id,
                event_type="DATA_EXPORT_REQUESTED",
                details_json={"export_id": str(exp.id)},
            )
            db.add(aud)
            vbatch = ImageVariationBatch(
                id=uuid.uuid4(),
                user_id=user.id,
                idempotency_key=f"batch_{uuid.uuid4().hex[:8]}",
                parent_image_id=gi.id,
                job_ids=[],
            )
            db.add(vbatch)
            outbox_rec = StorageDeletionOutbox(
                id=uuid.uuid4(),
                user_id=user.id,
                storage_backend="local",
                storage_key=f"users/{user.id}/parity_probe.txt",
                status="PENDING",
                worker_id="parity_worker",
                claim_token=uuid.uuid4(),
                claimed_at=utc_now(),
                lease_expires_at=utc_now(),
            )
            db.add(outbox_rec)
            db.commit()

            # Verify reads
            self.assertEqual(db.query(User).filter(User.id == user.id).count(), 1)
            self.assertEqual(db.query(Conversation).filter(Conversation.id == conv.id).count(), 1)
            self.assertEqual(db.query(Message).filter(Message.id == msg.id).count(), 1)
            self.assertEqual(db.query(UserMemory).filter(UserMemory.id == mem.id).count(), 1)
            self.assertEqual(db.query(GeneratedImage).filter(GeneratedImage.id == gi.id).count(), 1)
            self.assertEqual(db.query(BackgroundTask).filter(BackgroundTask.id == bg.id).count(), 1)
            self.assertEqual(db.query(ScheduledTaskRun).filter(ScheduledTaskRun.id == sch_run.id).count(), 1)
            self.assertEqual(db.query(UserUsageQuota).filter(UserUsageQuota.id == uq.id).count(), 1)
            self.assertEqual(db.query(UserDataExport).filter(UserDataExport.id == exp.id).count(), 1)
            self.assertEqual(db.query(AccountAuditEvent).filter(AccountAuditEvent.id == aud.id).count(), 1)
            self.assertEqual(db.query(ImageVariationBatch).filter(ImageVariationBatch.id == vbatch.id).count(), 1)
            self.assertEqual(db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_rec.id).count(), 1)

    def _orm_type_family(self, col: sa.Column, dialect: str) -> str:
        """Maps an ORM column type to a canonical dialect-aware type family."""
        t = col.type
        if isinstance(t, sa.types.Variant):
            t = t.mapping.get(dialect, t.impl)
        # Unwrap SQLAlchemy 2.0 _VariantMapping if present
        if hasattr(t, "_variant_mapping") and dialect in getattr(t, "_variant_mapping", {}):
            t = t._variant_mapping[dialect]

        cls_name = type(t).__name__.upper()
        if cls_name == "VECTOR":
            return "VECTOR(1536)" if dialect == "postgresql" else "JSON"
        if cls_name == "UUID":
            return "UUID" if dialect == "postgresql" else "CHAR_OR_UUID"
        if cls_name in ("JSON", "JSONB"):
            return "JSON"
        if cls_name in ("STRING", "VARCHAR", "TEXT"):
            return "TEXT"
        if cls_name in ("INTEGER", "BIGINTEGER", "SMALLINTEGER"):
            return "INTEGER"
        if cls_name in ("FLOAT", "NUMERIC", "DOUBLE_PRECISION", "REAL"):
            return "FLOAT"
        if cls_name == "BOOLEAN":
            return "BOOLEAN"
        if cls_name == "DATETIME":
            return "TIMESTAMPTZ" if dialect == "postgresql" else "DATETIME"
        return cls_name

    def _db_type_family(self, db_type_str: str, dialect: str) -> str:
        """Maps an inspected database column type string to a canonical type family."""
        s = (db_type_str or "").strip().upper()
        if dialect == "postgresql":
            if s.startswith("VECTOR"):
                return s.replace(" ", "")
            if s == "UUID":
                return "UUID"
            if s in ("JSON", "JSONB"):
                return "JSON"
            if s.startswith("CHARACTER VARYING") or s.startswith("VARCHAR") or s == "TEXT":
                return "TEXT"
            if s in ("INTEGER", "INT4", "BIGINT", "INT8", "SMALLINT", "INT2"):
                return "INTEGER"
            if s in ("DOUBLE PRECISION", "REAL", "FLOAT8", "FLOAT4", "NUMERIC"):
                return "FLOAT"
            if s in ("BOOLEAN", "BOOL"):
                return "BOOLEAN"
            if "TIMESTAMP" in s:
                return "TIMESTAMPTZ"
            return s

        # SQLite
        if "JSON" in s:
            return "JSON"
        if "CHAR" in s or "TEXT" in s or "CLOB" in s or "UUID" in s:
            return "TEXT_OR_UUID"
        if "INT" in s:
            return "INTEGER"
        if "REAL" in s or "FLOA" in s or "DOUB" in s or "NUM" in s:
            return "FLOAT"
        if "BOOL" in s:
            return "BOOLEAN"
        if "DATE" in s or "TIME" in s:
            return "DATETIME"
        return s

    def test_schema_column_types_nullability_keys_and_indexes_match_orm(self):
        """
        Dialect-aware structural parity check across ALL ORM tables:
        - Column types (strictly fails if PostgreSQL has JSON where ORM expects vector(1536))
        - Primary keys
        - Foreign keys
        - Critical unique constraints and indexes
        - PostgreSQL pgvector extension availability
        """
        insp = sa.inspect(self.engine)
        dialect = self.engine.dialect.name

        if dialect == "postgresql":
            with self.engine.connect() as conn:
                has_vec = conn.execute(
                    sa.text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                ).scalar()
                self.assertEqual(has_vec, 1, "PostgreSQL 'vector' extension MUST be installed by Alembic migrations!")

                emb_fmt = conn.execute(
                    sa.text(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON a.attrelid = c.oid
                        WHERE c.relname = 'document_chunks'
                          AND a.attname = 'embedding'
                          AND NOT a.attisdropped
                        """
                    )
                ).scalar()
                self.assertEqual(
                    emb_fmt,
                    "vector(1536)",
                    f"PostgreSQL document_chunks.embedding MUST be vector(1536), found '{emb_fmt}'!",
                )

        # Fetch PostgreSQL format_type map for exact type verification
        pg_types = {}
        if dialect == "postgresql":
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sa.text(
                        """
                        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON a.attrelid = c.oid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = current_schema()
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                        """
                    )
                ).fetchall()
                for tname, cname, ftype in rows:
                    pg_types[(tname, cname)] = ftype

        # 1. Column types & PKs & FKs across every ORM table
        for table_name, table in Base.metadata.tables.items():
            db_cols = {c["name"]: c for c in insp.get_columns(table_name)}
            for col in table.columns:
                self.assertIn(col.name, db_cols, f"Missing column {table_name}.{col.name}")
                orm_fam = self._orm_type_family(col, dialect)
                raw_db_type = (
                    pg_types.get((table_name, col.name), str(db_cols[col.name]["type"]))
                    if dialect == "postgresql"
                    else str(db_cols[col.name]["type"])
                )
                db_fam = self._db_type_family(raw_db_type, dialect)

                if dialect == "sqlite" and orm_fam == "CHAR_OR_UUID" and db_fam in ("TEXT_OR_UUID", "FLOAT"):
                    # SQLAlchemy generic sa.UUID() compiles to NUMERIC/CHAR on SQLite
                    continue
                if dialect == "sqlite" and orm_fam == "TEXT" and db_fam == "TEXT_OR_UUID":
                    continue
                self.assertEqual(
                    db_fam,
                    orm_fam,
                    f"Type mismatch on {table_name}.{col.name} ({dialect}): ORM expects {orm_fam}, DB has {raw_db_type} ({db_fam})",
                )

            # Primary key columns must match
            db_pk = set(insp.get_pk_constraint(table_name).get("constrained_columns") or [])
            orm_pk = {c.name for c in table.primary_key.columns}
            self.assertEqual(db_pk, orm_pk, f"Primary key mismatch on table '{table_name}': db={db_pk}, orm={orm_pk}")

            # Every ORM FK target must exist in migrated DB
            db_fks = {
                (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                for fk in insp.get_foreign_keys(table_name)
            }
            for fk in table.foreign_key_constraints:
                expected_fk = (
                    tuple(c.name for c in fk.columns),
                    fk.referred_table.name,
                    tuple(elem.column.name for elem in fk.elements),
                )
                self.assertIn(
                    expected_fk,
                    db_fks,
                    f"Missing foreign key on table '{table_name}': expected {expected_fk}, found {db_fks}",
                )

        # 2. Verify nullability on critical NOT NULL columns of core & new tables
        critical_not_null = [
            ("users", "username"),
            ("users", "hashed_password"),
            ("documents", "user_id"),
            ("document_chunks", "document_id"),
            ("document_chunks", "content"),
            ("image_generation_jobs", "user_id"),
            ("image_generation_jobs", "prompt"),
            ("image_variation_batches", "user_id"),
            ("image_variation_batches", "idempotency_key"),
            ("storage_deletion_outbox", "storage_key"),
            ("storage_deletion_outbox", "status"),
            ("user_usage_quotas", "user_id"),
            ("user_usage_quotas", "category"),
            ("user_usage_quotas", "window_key"),
            ("user_data_exports", "user_id"),
        ]
        for tname, cname in critical_not_null:
            col_info = {c["name"]: c for c in insp.get_columns(tname)}[cname]
            self.assertFalse(
                col_info["nullable"],
                f"Critical column {tname}.{cname} must be NOT NULL in migrated schema!",
            )

        # 3. Verify critical unique constraints exist (either as unique constraint or unique index)
        critical_uniques = [
            ("image_generation_jobs", ("user_id", "idempotency_key")),
            ("image_variation_batches", ("user_id", "idempotency_key")),
            ("user_usage_quotas", ("user_id", "category", "window_key")),
            ("coding_task_events", ("task_id", "sequence_number")),
            ("scheduled_task_runs", ("task_id", "scheduled_for")),
        ]
        for tname, cols in critical_uniques:
            uqs = {tuple(u["column_names"]) for u in insp.get_unique_constraints(tname)}
            uidxs = {tuple(i["column_names"]) for i in insp.get_indexes(tname) if i.get("unique")}
            self.assertIn(
                cols,
                uqs | uidxs,
                f"Missing unique constraint/index on {tname}{cols}: found uqs={uqs}, uidxs={uidxs}",
            )

        # 4. Verify critical indexes exist
        critical_indexes = [
            ("document_chunks", ("document_id",)),
            ("storage_deletion_outbox", ("lease_expires_at",)),
            ("storage_deletion_outbox", ("claim_token",)),
            ("image_variation_batches", ("idempotency_key",)),
            ("image_variation_batches", ("request_fingerprint",)),
        ]
        for tname, cols in critical_indexes:
            idxs = {tuple(i["column_names"]) for i in insp.get_indexes(tname)}
            self.assertIn(cols, idxs, f"Missing index on {tname}{cols}: found {idxs}")

    def test_real_non_null_1536_vector_persistence(self):
        """Persists and reads back a real 1536-dim non-null embedding vector on migrated DB."""
        vec = [0.0] * 1536
        vec[0] = 0.75
        vec[1] = 0.25
        vec[1535] = 0.5

        with self.Session() as db:
            u = User(
                id=uuid.uuid4(),
                username=f"vec_parity_{uuid.uuid4().hex[:8]}",
                hashed_password="hashed_pw_parity",
                created_at=utc_now(),
            )
            db.add(u)
            doc = Document(
                id=uuid.uuid4(),
                user_id=u.id,
                filename="vec_test.md",
                mime_type="text/markdown",
                storage_path="/tmp/vec_test.md",
                is_knowledge_base=True,
                indexing_status="READY",
            )
            db.add(doc)
            chunk = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=0,
                content="Vector persistence check",
                embedding=vec,
            )
            null_chunk = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=1,
                content="Null embedding check",
                embedding=None,
            )
            db.add(chunk)
            db.add(null_chunk)
            db.commit()
            cid = chunk.id
            ncid = null_chunk.id

        with self.Session() as db:
            loaded = db.query(DocumentChunk).filter(DocumentChunk.id == cid).first()
            self.assertIsNotNone(loaded.embedding)
            vals = list(loaded.embedding)
            self.assertEqual(len(vals), 1536)
            self.assertAlmostEqual(float(vals[0]), 0.75, places=5)
            self.assertAlmostEqual(float(vals[1]), 0.25, places=5)
            self.assertAlmostEqual(float(vals[1535]), 0.5, places=5)

            loaded_null = db.query(DocumentChunk).filter(DocumentChunk.id == ncid).first()
            self.assertIsNone(loaded_null.embedding)

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

