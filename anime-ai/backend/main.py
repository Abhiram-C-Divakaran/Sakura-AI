import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from database.init_db import init_tables, seed_characters

from config.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="Sakura AI Platform",
    description="A production-grade multimodal assistant and frontier repository-level coding engine.",
    version="1.0.0"
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
import uuid
from fastapi import Request

@app.middleware("http")
async def add_correlation_and_latency(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    if "/system/status" in request.url.path or "/ws" in request.url.path:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
        
    start_time = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start_time) * 1000
    
    response.headers["X-Request-ID"] = request_id
    from api.routes import LATENCY_SAMPLES
    LATENCY_SAMPLES.append(latency_ms)
    if len(LATENCY_SAMPLES) > 50:
        LATENCY_SAMPLES.pop(0)
        
    return response

scheduler_service = None

@app.on_event("startup")
async def on_startup():
    """Initializes tables, seeds profiles, and starts background scheduler."""
    global scheduler_service
    try:
        init_tables()
        seed_characters()
        print("Sakura AI Platform: Startup database initialized successfully.")
    except Exception as e:
        print(f"Sakura AI Platform: Startup database error: {e}")

    try:
        from tasks.scheduler import TaskSchedulerService
        scheduler_service = TaskSchedulerService(poll_interval_seconds=60)
        await scheduler_service.start()
        print("Sakura AI Platform: Task scheduler service started.")
    except Exception as e:
        print(f"Sakura AI Platform: Task scheduler start error: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    global scheduler_service
    if scheduler_service:
        await scheduler_service.stop()

# Include core router
app.include_router(router)

@app.get("/health")
def health_check():
    return {"status": "online", "system": "Sakura AI Core", "version": "1.0.0"}
