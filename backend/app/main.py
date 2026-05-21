import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import routes
from app.api import admin_routes
from app.db.database import engine, SessionLocal
from app.models import Base, Source
from app.scheduler import start_scheduler
from config.source_loader import load_and_upsert_sources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent / "frontend"

app = FastAPI(title="NewsAI Scraper", version="0.2.0")

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(routes.router)
app.include_router(admin_routes.router)

# Sync sources from YAML into DB on startup
db = SessionLocal()
try:
    inserted, updated, skipped = load_and_upsert_sources(db, Source)
    logger.info(f"Source sync: {inserted} inserted, {updated} updated, {skipped} skipped")
finally:
    db.close()

# Start background scheduler with per-source intervals
app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    app.state.scheduler.shutdown()
