import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Web Server
    APP_NAME: str = "Air Compressor Management"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # Database Configuration (MSSQL + Auto SQLite Fallback)
    DB_TYPE: str = "mssql"  # "mssql" or "sqlite"
    MSSQL_SERVER: str = "localhost"
    MSSQL_DATABASE: str = "CompressorDB"
    MSSQL_USERNAME: str = ""
    MSSQL_PASSWORD: str = ""
    MSSQL_DRIVER: str = "ODBC Driver 17 for SQL Server"
    MSSQL_TRUSTED_CONNECTION: bool = True  # Windows Auth
    SQLITE_PATH: str = os.path.join(BASE_DIR, "data", "compressor.db")

    # Siemens S7-1200 PLC Configuration
    PLC_ENABLED: bool = False  # Set to True when connected to real physical S7-1200
    PLC_IP: str = "192.168.0.1"
    PLC_RACK: int = 0
    PLC_SLOT: int = 1
    PLC_DB_NUMBER: int = 1
    PLC_POLL_INTERVAL_SEC: float = 2.0

    # Local AI Chatbot (Ollama + Diagnostic Rule Engine)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    LLM_FALLBACK_TO_HEURISTIC: bool = True

    # Compressor Engineering Specifications & Operational Limits
    COMPRESSOR_ID: int = 1
    COMPRESSOR_TAG: str = "CMP-01"
    COMPRESSOR_NAME: str = "Screw Compressor Unit #1 (GA-75 VSD)"
    RATED_POWER_KW: float = 75.0
    RATED_FLOW_CFM: float = 480.0
    TARGET_PRESSURE_MIN_BAR: float = 6.5
    TARGET_PRESSURE_MAX_BAR: float = 7.5
    AIREND_TEMP_NORMAL_MAX_C: float = 92.0
    AIREND_TEMP_WARN_C: float = 98.0
    AIREND_TEMP_TRIP_C: float = 105.0
    SEPARATOR_DP_WARN_BAR: float = 0.8
    MAX_DEWPOINT_WARN_C: float = 3.0

settings = Settings()
