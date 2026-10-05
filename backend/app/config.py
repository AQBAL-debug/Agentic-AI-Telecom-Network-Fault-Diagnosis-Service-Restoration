"""
config.py
---------
WHAT IT DOES:
    Central place for all settings (database URL, OpenRouter key, model name ...).
    Values are read from environment variables or from the backend/.env file,
    so nothing secret is hard-coded in the source.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # -> backend/
DATA_DIR = BASE_DIR / "data"                            # synthetic datasets + SOP docs
MODEL_DIR = BASE_DIR / "models"                         # trained anomaly model is saved here
MODEL_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    DATABASE_URL: str = ""                               # empty -> SQLite fallback
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    LLM_ENABLED: bool = True
    CORS_ORIGINS: str = "*"

    # Alarm-correlation tuning
    CORRELATION_WINDOW_SEC: int = 120                    # alarms within 2 min may be related
    STORM_THRESHOLD: int = 50                            # >50 alarms in window = alarm storm

    @property
    def db_url(self) -> str:
        """Return a SQLAlchemy URL. Render gives 'postgres://', SQLAlchemy needs 'postgresql://'."""
        url = self.DATABASE_URL.strip()
        if not url:
            return f"sqlite:///{BASE_DIR / 'noc.db'}"
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


settings = Settings()
