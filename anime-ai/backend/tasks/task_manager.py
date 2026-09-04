"""
Sakura AI — Durable Background Task Queue & Job Execution Engine
Persists all background tasks in PostgreSQL / SQLite via SQLAlchemy BackgroundTask model.
Ensures consistency across server restarts, worker instances, and provides real status,
cancellation semantics, and real web research without artificial sleeps or fabricated progress.
"""
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from database.models import BackgroundTask, Document, DocumentChunk, utc_now
from database.db import get_db_context
from llm.router import LLMRouter
from services.web_search import perform_web_search


ACTIVE_ASYNCIO_TASKS: Dict[str, asyncio.Task] = {}


class TaskManager:
    """Manages persistent background tasks with durable database state."""

    @staticmethod
    def create_task(user_id: uuid.UUID, task_type: str, title: str, payload: dict) -> BackgroundTask:
        with get_db_context() as db:
            task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=user_id,
                type=task_type,
                title=title,
                payload=payload or {},
                status="Queued",
                progress=0,
                created_at=utc_now(),
                retry_count=0
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            # Dispatch asynchronous execution if an event loop is running
            task_id_str = str(task.id)
            try:
                loop = asyncio.get_running_loop()
                t = loop.create_task(run_task_execution(task.id, user_id))
                ACTIVE_ASYNCIO_TASKS[task_id_str] = t
            except RuntimeError:
                pass
            return task

    @staticmethod
    def get_task(task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[BackgroundTask]:
        with get_db_context() as db:
            return db.query(BackgroundTask).filter(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            ).first()

    @staticmethod
    def list_tasks(user_id: uuid.UUID) -> List[BackgroundTask]:
        with get_db_context() as db:
            return db.query(BackgroundTask).filter(
                BackgroundTask.user_id == user_id
            ).order_by(BackgroundTask.created_at.desc()).all()

    @staticmethod
    def count_active_tasks(user_id: uuid.UUID) -> int:
        with get_db_context() as db:
            return db.query(BackgroundTask).filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.status.in_(["Queued", "Starting", "Running", "Waiting"])
            ).count()

    @staticmethod
    async def cancel_task(task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[BackgroundTask]:
        task_id_str = str(task_id)
        if task_id_str in ACTIVE_ASYNCIO_TASKS:
            ACTIVE_ASYNCIO_TASKS[task_id_str].cancel()
            del ACTIVE_ASYNCIO_TASKS[task_id_str]

        with get_db_context() as db:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            ).first()
            if not task:
                return None

            if task.status in ["Queued", "Starting", "Running", "Waiting"]:
                task.status = "Cancelled"
                task.completed_at = utc_now()
                db.commit()
                db.refresh(task)
                await emit_task_update(task.to_dict())
            return task

    @staticmethod
    async def retry_task(task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[BackgroundTask]:
        with get_db_context() as db:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            ).first()
            if not task:
                return None

            if task.status in ["Failed", "Cancelled"]:
                task.status = "Queued"
                task.progress = 0
                task.error = None
                task.result = None
                task.started_at = None
                task.completed_at = None
                task.retry_count = (task.retry_count or 0) + 1
                db.commit()
                db.refresh(task)

                task_id_str = str(task.id)
                try:
                    loop = asyncio.get_running_loop()
                    t = loop.create_task(run_task_execution(task.id, user_id))
                    ACTIVE_ASYNCIO_TASKS[task_id_str] = t
                except RuntimeError:
                    pass
                await emit_task_update(task.to_dict())

            return task

    @staticmethod
    def delete_task(task_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        task_id_str = str(task_id)
        if task_id_str in ACTIVE_ASYNCIO_TASKS:
            ACTIVE_ASYNCIO_TASKS[task_id_str].cancel()
            del ACTIVE_ASYNCIO_TASKS[task_id_str]

        with get_db_context() as db:
            task = db.query(BackgroundTask).filter(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            ).first()
            if not task:
                return False
            db.delete(task)
            db.commit()
            return True

    @staticmethod
    def clear_completed_tasks(user_id: uuid.UUID) -> int:
        with get_db_context() as db:
            tasks = db.query(BackgroundTask).filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.status.in_(["Completed", "Failed", "Cancelled"])
            ).all()
            count = len(tasks)
            for t in tasks:
                db.delete(t)
            db.commit()
            return count


async def emit_task_update(task_dict: dict):
    """Emits realtime task update to client websocket."""
    try:
        from api.routes import ws_manager
        user_id = task_dict.get("userId")
        if user_id:
            await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_dict})
    except Exception:
        pass


async def update_task_state(
    task_id: uuid.UUID,
    status: str,
    progress: int,
    error: Optional[str] = None,
    result: Optional[str] = None,
    result_metadata: Optional[dict] = None
) -> Optional[dict]:
    """Updates task in database and broadcasts update."""
    with get_db_context() as db:
        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if not task:
            return None

        task.status = status
        task.progress = progress
        if status in ["Starting", "Running"] and not task.started_at:
            task.started_at = utc_now()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result
        if result_metadata is not None:
            task.result_metadata = result_metadata
        if status in ["Completed", "Failed", "Cancelled"]:
            task.completed_at = utc_now()

        db.commit()
        db.refresh(task)
        task_dict = task.to_dict()

    await emit_task_update(task_dict)
    return task_dict


async def run_task_execution(task_id: uuid.UUID, user_id: uuid.UUID):
    """Executes a background task according to its real phase and requirements."""
    task_id_str = str(task_id)
    try:
        with get_db_context() as db:
            task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not task:
                return
            task_type = task.type
            payload = dict(task.payload or {})

        await update_task_state(task_id, "Starting", 5)

        router = LLMRouter()
        if task_type == "code_analysis":
            await execute_code_analysis(task_id, user_id, payload, router)
        elif task_type == "doc_summary":
            await execute_doc_summary(task_id, user_id, payload, router)
        elif task_type == "dataset_analysis":
            await execute_dataset_analysis(task_id, user_id, payload, router)
        elif task_type == "web_research":
            await execute_web_research(task_id, user_id, payload, router)
        else:
            await update_task_state(task_id, "Failed", 100, error=f"Unknown task type: {task_type}")

    except asyncio.CancelledError:
        await update_task_state(task_id, "Cancelled", 100)
    except Exception as e:
        await update_task_state(task_id, "Failed", 100, error=str(e))
    finally:
        if task_id_str in ACTIVE_ASYNCIO_TASKS:
            del ACTIVE_ASYNCIO_TASKS[task_id_str]


async def execute_code_analysis(task_id: uuid.UUID, user_id: uuid.UUID, payload: dict, router: LLMRouter):
    code = payload.get("code", "")
    instruction = payload.get("task", "explain")

    await update_task_state(task_id, "Running", 25)
    prompt = (
        f"Please analyze this code and provide a comprehensive code review:\n"
        f"Instruction: {instruction}\n"
        f"Code:\n```\n{code}\n```"
    )
    await update_task_state(task_id, "Running", 60)
    _, response = await router.generate(
        prompt=prompt,
        system_prompt="You are a senior software architect and code reviewer."
    )
    await update_task_state(task_id, "Completed", 100, result=response)


async def execute_doc_summary(task_id: uuid.UUID, user_id: uuid.UUID, payload: dict, router: LLMRouter):
    doc_id_str = payload.get("document_id")
    if not doc_id_str:
        await update_task_state(task_id, "Failed", 100, error="Missing document_id in task payload")
        return

    try:
        doc_u = uuid.UUID(doc_id_str)
    except ValueError:
        await update_task_state(task_id, "Failed", 100, error="Invalid document identifier")
        return

    await update_task_state(task_id, "Running", 20)
    with get_db_context() as db:
        doc = db.query(Document).filter(Document.id == doc_u, Document.user_id == user_id).first()
        if not doc:
            await update_task_state(task_id, "Failed", 100, error="Document not found or access denied")
            return

        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id
        ).order_by(DocumentChunk.chunk_index.asc()).all()
        if not chunks:
            await update_task_state(task_id, "Failed", 100, error="No text content indexed for this document")
            return
        combined_text = "\n\n".join(c.content for c in chunks[:10])

    await update_task_state(task_id, "Running", 60)
    prompt = f"Please provide an accurate, high-density summary of the following document:\n\n{combined_text}"
    _, response = await router.generate(
        prompt=prompt,
        system_prompt="You are an analytical document summarizer."
    )
    await update_task_state(task_id, "Completed", 100, result=response)


async def execute_dataset_analysis(task_id: uuid.UUID, user_id: uuid.UUID, payload: dict, router: LLMRouter):
    dataset_text = payload.get("dataset_text", "")
    if not dataset_text.strip():
        await update_task_state(task_id, "Failed", 100, error="Empty dataset provided")
        return

    await update_task_state(task_id, "Running", 30)
    lines = [l for l in dataset_text.strip().split("\n") if l.strip()]
    num_rows = len(lines)
    header = lines[0] if lines else ""
    num_cols = len(header.split(",")) if header else 0

    stats_summary = f"Dataset Metrics:\n- Total Rows: {num_rows}\n- Columns: {num_cols}\n- Header: {header}"

    await update_task_state(task_id, "Running", 70)
    prompt = (
        f"Perform an analytical review of this dataset sample:\n"
        f"{stats_summary}\n"
        f"Sample Preview:\n{chr(10).join(lines[:10])}"
    )
    _, response = await router.generate(
        prompt=prompt,
        system_prompt="You are a data scientist analyzing tabular datasets."
    )
    full_result = f"{stats_summary}\n\nAnalysis:\n{response}"
    await update_task_state(task_id, "Completed", 100, result=full_result)


async def execute_web_research(task_id: uuid.UUID, user_id: uuid.UUID, payload: dict, router: LLMRouter):
    """
    Executes real web research:
    1. Runs real web search via Tavily / DuckDuckGo fallback.
    2. Gathers structured results and citation links.
    3. Synthesizes findings using LLM.
    4. Stores result and source URLs truthfully. If search is unavailable, fails truthfully.
    """
    query = payload.get("query", "").strip()
    if not query:
        await update_task_state(task_id, "Failed", 100, error="Empty query provided for web research")
        return

    await update_task_state(task_id, "Running", 25)

    # 1. Real web search
    search_data = await perform_web_search(query, max_results=6)
    results = search_data.get("results", [])

    if not search_data.get("success") or not results:
        error_msg = search_data.get("error") or "No live web search results found."
        await update_task_state(
            task_id,
            "Failed",
            100,
            error=f"Web search unavailable: {error_msg}. Cannot synthesize ungrounded research.",
            result_metadata={"query": query, "provider": search_data.get("provider")}
        )
        return

    await update_task_state(task_id, "Running", 65)

    # 2. Structured source compilation
    sources_text = "\n\n".join([
        f"[{r.get('source_index', i+1)}] {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('snippet')}"
        for i, r in enumerate(results)
    ])

    # 3. LLM synthesis
    prompt = (
        f"You are Sakura AI conducting research on the topic: '{query}'.\n"
        f"Below are the verified live search results gathered for this query:\n\n"
        f"{sources_text}\n\n"
        f"Synthesize a clear, detailed research brief on '{query}' based ONLY on these sources.\n"
        f"Cite sources using numbered brackets [1], [2], etc. Include a final 'Sources' list with URLs."
    )

    _, response = await router.generate(
        prompt=prompt,
        system_prompt="You are an expert research analyst providing cited, factual intelligence."
    )

    metadata = {
        "query": query,
        "provider": search_data.get("provider"),
        "sources": [
            {"index": r.get("source_index", i+1), "title": r.get("title"), "url": r.get("url")}
            for i, r in enumerate(results)
        ]
    }

    await update_task_state(
        task_id,
        "Completed",
        100,
        result=response,
        result_metadata=metadata
    )
