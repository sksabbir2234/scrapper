import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import SessionLocal
from app.models import Article, ScrapeLog

logger = logging.getLogger(__name__)


def cleanup_old_articles(days: int = 30) -> int:
    """Soft-delete articles older than N days. Returns count archived."""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = (
            db.query(Article)
            .filter(
                Article.published_at < cutoff,
                Article.deleted_at.is_(None),
            )
            .update({"deleted_at": datetime.now(timezone.utc)})
        )
        db.commit()
        logger.info(f"Archived {count} articles older than {days} days")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"Article cleanup failed: {e}")
        return 0
    finally:
        db.close()


def cleanup_old_logs(days: int = 30) -> int:
    """Delete scrape logs older than N days. Returns count deleted."""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = (
            db.query(ScrapeLog)
            .filter(ScrapeLog.scraped_at < cutoff)
            .delete()
        )
        db.commit()
        logger.info(f"Deleted {count} scrape logs older than {days} days")
        return count
    except Exception as e:
        db.rollback()
        logger.error(f"Log cleanup failed: {e}")
        return 0
    finally:
        db.close()


def run_cleanup(article_days: int = 30, log_days: int = 30):
    """Run all cleanup tasks."""
    archived = cleanup_old_articles(article_days)
    deleted = cleanup_old_logs(log_days)
    return {"articles_archived": archived, "logs_deleted": deleted}
