import os
import urllib.parse
import logging
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.database.models import Base

logger = logging.getLogger("app.database")
logging.basicConfig(level=logging.INFO)

def create_db_engine():
    """
    Attempts to create an MSSQL engine.
    If connection fails or DB_TYPE='sqlite', falls back gracefully to SQLite.
    """
    if settings.DB_TYPE.lower() == "mssql":
        try:
            logger.info(f"Attempting connection to MSSQL Server [{settings.MSSQL_SERVER}], Database [{settings.MSSQL_DATABASE}]...")
            if settings.MSSQL_TRUSTED_CONNECTION:
                odbc_str = (
                    f"DRIVER={{{settings.MSSQL_DRIVER}}};"
                    f"SERVER={settings.MSSQL_SERVER};"
                    f"DATABASE={settings.MSSQL_DATABASE};"
                    f"Trusted_Connection=yes;"
                    f"TrustServerCertificate=yes;"
                )
            else:
                odbc_str = (
                    f"DRIVER={{{settings.MSSQL_DRIVER}}};"
                    f"SERVER={settings.MSSQL_SERVER};"
                    f"DATABASE={settings.MSSQL_DATABASE};"
                    f"UID={settings.MSSQL_USERNAME};"
                    f"PWD={settings.MSSQL_PASSWORD};"
                    f"TrustServerCertificate=yes;"
                )
            params = urllib.parse.quote_plus(odbc_str)
            mssql_url = f"mssql+pyodbc:///?odbc_connect={params}"
            
            # Test engine with a short connection timeout
            test_engine = create_engine(
                mssql_url,
                connect_args={"timeout": 4},
                pool_pre_ping=True
            )
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Successfully connected to MS SQL Server!")
            return test_engine, "MSSQL"
        except Exception as e:
            logger.warning(f"Could not connect to MSSQL Server ({e}). Falling back to local SQLite database.")

    # SQLite fallback
    sqlite_dir = Path(settings.SQLITE_PATH).parent
    sqlite_dir.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{settings.SQLITE_PATH}"
    logger.info(f"Using local SQLite database at: {settings.SQLITE_PATH}")
    sqlite_engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
    return sqlite_engine, "SQLite"

engine, ACTIVE_DB_DIALECT = create_db_engine()

# Configure SQLite WAL mode for high concurrency and low SD-card wear on Raspberry Pi
if ACTIVE_DB_DIALECT == "SQLite":
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64 MB in-memory query cache
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create tables and ensure master records exist."""
    Base.metadata.create_all(bind=engine)
    from app.database.seed_data import seed_initial_data_if_empty
    seed_initial_data_if_empty()
