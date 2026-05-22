from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://newsuser:newspass@localhost:5432/newsdb"
    debug: bool = True
    scraper_user_agent: str = "NewsAggregatorBot/1.0 (+https://yoursite.com/bot)"
    scraper_delay_min: float = 2.0
    scraper_delay_max: float = 5.0
    scrape_interval_minutes: int = 30
    scrape_cron_expression: str | None = None  # e.g. "0 */6 *" for every 6 hours; overrides interval
    groq_api_key: str | None = None
    admin_user: str = "admin"
    admin_password: str = "changeme"
    admin_secret_key: str = "change-this-to-a-random-secret-in-env"
    admin_token_expire_hours: int = 24
    site_url: str = "http://localhost:8000"
    github_token: str | None = None
    github_watch_interval_minutes: int = 60
    market_cache_ttl_seconds: int = 300

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
