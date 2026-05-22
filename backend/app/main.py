import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import routes
from app.api import admin_routes
from app.db.database import engine, SessionLocal
from app.models import Base, Source, GithubRepo
from app.scheduler import start_scheduler
from config.source_loader import load_and_upsert_sources
from config.github_repo_loader import load_and_upsert_github_repos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent / "frontend"

app = FastAPI(title="NewsAI Scraper", version="0.2.0")

Base.metadata.create_all(bind=engine)

# Lightweight column migration for new fields
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE finance_resources ADD COLUMN IF NOT EXISTS cost_level VARCHAR(20) DEFAULT 'any'"))
        conn.execute(text("ALTER TABLE articles ALTER COLUMN original_url TYPE VARCHAR(1000)"))
        conn.execute(text("ALTER TABLE articles ALTER COLUMN image_url TYPE VARCHAR(1000)"))
        conn.execute(text("ALTER TABLE github_updates ALTER COLUMN repo_url TYPE VARCHAR(1000)"))
        conn.execute(text("ALTER TABLE github_updates ALTER COLUMN external_url TYPE VARCHAR(1000)"))
        conn.execute(text("ALTER TABLE sources ALTER COLUMN rss_url TYPE VARCHAR(500)"))
        conn.commit()
    except Exception:
        pass  # Column already exists or SQLite (SQLite doesn't support IF NOT EXISTS on ALTER)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(routes.router)
app.include_router(admin_routes.router)

# Sync sources from YAML into DB on startup
db = SessionLocal()
try:
    inserted, updated, skipped = load_and_upsert_sources(db, Source)
    logger.info(f"Source sync: {inserted} inserted, {updated} updated, {skipped} skipped")

    # Sync GitHub repos from YAML
    gh_inserted, gh_updated = load_and_upsert_github_repos(db, GithubRepo)
    logger.info(f"GitHub repo sync: {gh_inserted} inserted, {gh_updated} updated")
finally:
    db.close()

# Start background scheduler with per-source intervals
app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    app.state.scheduler.shutdown()
