import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import resources
from pathlib import Path
from typing import Callable, Generator, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.storage.config import DatabaseConfig
from core.storage.migrations import apply_migrations, create_vector_table


def _database_path() -> Path:
    return DatabaseConfig.from_env().path


def create_database_engine(path: str | Path) -> Engine:
    """Create a SQLite engine for a Know-Do Graph database."""
    db_path = Path(path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    # Optional dependency: retrieval falls back to keyword search when unavailable.
    try:
        import sqlite_vec  # type: ignore

        @event.listens_for(db_engine, "connect")
        def _load_sqlite_vec(dbapi_conn, _connection_record) -> None:
            try:
                dbapi_conn.enable_load_extension(True)
                sqlite_vec.load(dbapi_conn)
                dbapi_conn.enable_load_extension(False)
            except Exception:
                pass
    except ImportError:
        pass
    return db_engine


DB_PATH = _database_path()
engine = create_database_engine(DB_PATH)

_default_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_session_factory: ContextVar[Callable[[], Session]] = ContextVar(
    "kdg_session_factory",
    default=_default_session_factory,
)


def SessionLocal() -> Session:
    """Create a session using the database bound to the current context."""
    return _session_factory.get()()


@contextmanager
def bind_session_factory(factory: Callable[[], Session]) -> Iterator[None]:
    """Temporarily route legacy agent tools to a client-owned database."""
    token = _session_factory.set(factory)
    try:
        yield
    finally:
        _session_factory.reset(token)


def install_starter_database(*, force: bool = False) -> Path:
    """Copy the packaged starter DB to the configured working DB path."""
    if DB_PATH.exists() and not force:
        raise FileExistsError(DB_PATH)

    packaged_starter = resources.files("core").joinpath("resources/starter.db")
    source_checkout_starter = Path(__file__).resolve().parents[2] / "assets" / "starter.db"

    if packaged_starter.is_file():
        starter = packaged_starter
    elif source_checkout_starter.is_file():
        starter = source_checkout_starter
    else:
        raise FileNotFoundError("The starter database is not included in this installation.")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine.dispose()
    with resources.as_file(starter) as starter_path:
        if starter_path.resolve() != DB_PATH:
            shutil.copy2(starter_path, DB_PATH)
    return DB_PATH


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database(db_engine: Engine) -> None:
    """Create and migrate tables on the supplied engine."""
    from core.storage.models import Base

    Base.metadata.create_all(bind=db_engine)
    apply_migrations(db_engine)
    with db_engine.connect() as conn:
        create_vector_table(conn)
        conn.commit()


def init_db() -> None:
    initialize_database(engine)
