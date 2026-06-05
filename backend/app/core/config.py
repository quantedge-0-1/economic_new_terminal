from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Economic News Terminal"
    environment: str = "development"
    debug: bool = False

    # SQLite — simplified local setup
    database_url: str = "sqlite+aiosqlite:///./economic_terminal.db"

    # External APIs
    fred_api_key: str = ""
    twelve_data_api_key: str = ""
    anthropic_api_key: str = ""
    polygon_api_key: str = ""

    # Cache TTLs (seconds) — in-memory
    calendar_cache_ttl: int = 300     # 5 min
    surprise_cache_ttl: int = 600     # 10 min
    reaction_cache_ttl: int = 3600    # 1 h
    news_cache_ttl: int = 180         # 3 min
    alerts_cache_ttl: int = 60        # 1 min
    prices_cache_ttl: int = 45        # 45 sec — Twelve Data free tier: 8 calls/min

    # AI Analysis
    ai_model: str = "claude-opus-4-8"
    ai_max_tokens: int = 220

    # Ports
    backend_port: int = 8001
    frontend_port: int = 3000


settings = Settings()
