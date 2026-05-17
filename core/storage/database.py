from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "know_do_graph.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

# Try to load sqlite-vec on every new SQLite connection so vector search works.
# Optional dep: if sqlite-vec isn't installed, retrieval falls back to keyword-only.
try:
    import sqlite_vec  # type: ignore

    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_conn, _connection_record) -> None:
        try:
            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            dbapi_conn.enable_load_extension(False)
        except Exception:
            pass  # extension loading not supported on this build; vector search disabled
except ImportError:
    pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from core.storage.models import Base

    Base.metadata.create_all(bind=engine)

    # Migrate: add new columns idempotently (SQLite only supports ADD COLUMN)
    with engine.connect() as conn:
        for col, default in [
            ("aliases", "'[]'"),
            ("scripts_json", "'[]'"),
            ("embedding_hash", "NULL"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE entries ADD COLUMN {col} TEXT DEFAULT {default}"))
                conn.commit()
            except Exception:
                pass  # column already exists

        # Create the sqlite-vec virtual table for entry embeddings (if extension loaded).
        # 384 dims matches sentence-transformers/all-MiniLM-L6-v2 (the default).
        try:
            conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entry_embeddings USING vec0("
                "entry_id TEXT PRIMARY KEY, embedding FLOAT[384])"
            ))
            conn.commit()
        except Exception:
            pass  # sqlite-vec not loaded; hybrid retrieval will fall back to keyword
