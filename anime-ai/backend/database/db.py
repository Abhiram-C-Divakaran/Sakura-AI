import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

def normalize_database_url(url: str) -> str:
    """
    Ensures PostgreSQL connection URLs consistently select the installed
    psycopg2 driver (postgresql+psycopg2://) rather than defaulting to
    an uninstalled psycopg v3 driver.
    """
    if not url:
        return url
    trimmed = url.strip()
    if trimmed.startswith("postgres://"):
        return "postgresql+psycopg2://" + trimmed[len("postgres://"):]
    if trimmed.startswith("postgresql://"):
        return "postgresql+psycopg2://" + trimmed[len("postgresql://"):]
    return trimmed


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/anime_ai"
    )
)

# Connect engine. Setup pool for production-grade throughput
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_pre_ping=True
    )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI Dependency to yield a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_context():
    """Standard context manager for non-FastAPI blocks (background tasks, scripts)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
