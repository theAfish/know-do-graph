from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "know_do_graph.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

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

    # Migrate: add aliases column if it doesn't exist yet (SQLite only supports ADD COLUMN)
    with engine.connect() as conn:
        for col, default in [
            ("aliases", "'[]'"),
            ("scripts_json", "'[]'"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE entries ADD COLUMN {col} TEXT DEFAULT {default}"))
                conn.commit()
            except Exception:
                pass  # column already exists
