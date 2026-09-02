import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from database.init_db import init_tables, seed_characters

app = FastAPI(
    title="Neo-Tokyo Vintage Anime AI Platform",
    description="A production-grade character chat platform with RAG, memory extraction, and dynamic routing.",
    version="1.0.0"
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Swap with strict domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
from fastapi import Request

@app.middleware("http")
async def record_latency(request: Request, call_next):
    if "/system/status" in request.url.path or "/ws" in request.url.path:
        return await call_next(request)
        
    start_time = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start_time) * 1000
    
    from api.routes import LATENCY_SAMPLES
    LATENCY_SAMPLES.append(latency_ms)
    if len(LATENCY_SAMPLES) > 50:
        LATENCY_SAMPLES.pop(0)
        
    return response

@app.on_event("startup")
def on_startup():
    """Initializes tables and seeds Sakura's profile on server startup."""
    try:
        init_tables()
        seed_characters()
        print("Neo-Tokyo AI Platform: Startup database initialized successfully.")
    except Exception as e:
        print(f"Neo-Tokyo AI Platform: Startup database error: {e}")

# Include core router
app.include_router(router)

@app.get("/health")
def health_check():
    return {"status": "online", "system": "Neo-Tokyo AI Core", "version": "1.0.0"}
