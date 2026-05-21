import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Source, Article, ScrapeLog, GithubUpdate
from app.scrapers.rss_scraper import scrape_rss_feed
from app.scrapers.playwright_scraper import scrape_with_playwright
from app.ai.summarizer import summarize_article
from app.ai.classifier import classify_article, CATEGORIES
from app.ai.keyword_extractor import _extract_tags_batch

logger = logging.getLogger(__name__)


def _classify_new_articles(articles_data: list[dict]):
    """Run zero-shot classification on newly inserted articles in a background thread."""
    def _run():
        db = SessionLocal()
        try:
            for article_data in articles_data:
                url_hash = article_data.get("url_hash")
                if not url_hash:
                    continue
                article = db.query(Article).filter(Article.url_hash == url_hash).first()
                if not article or article.category:
                    continue

                results = classify_article(article.title, article.content_text, top_n=1)
                if results and results[0]["confidence"] > 0.3:
                    article.category = results[0]["category"].lower()
                    logger.info(f"Classified '{article.title[:40]}...' as {article.category}")

            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Classification batch failed: {e}")
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


def _summarize_new_articles(articles_data: list[dict]):
    """Run Groq summarization on newly inserted articles in a background thread."""
    def _run():
        db = SessionLocal()
        try:
            for article_data in articles_data:
                url_hash = article_data.get("url_hash")
                if not url_hash:
                    continue
                article = db.query(Article).filter(Article.url_hash == url_hash).first()
                if not article or article.summary_ai:
                    continue

                result = summarize_article(article.title, article.content_text)
                if result:
                    article.summary_ai = result["summary_ai"]
                    article.seo_title = result["seo_title"]
                    article.seo_description = result["seo_description"]
                    logger.info(f"Summarized: {article.title[:50]}...")

            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Summarization batch failed: {e}")
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


def _get_articles(source) -> list[dict]:
    """Get articles using the appropriate scraper for the source type.
    Falls back to Playwright if RSS returns no articles."""
    cat = source.category if source.category else None

    if source.scrape_type == "playwright":
        return scrape_with_playwright(source.rss_url, source.id, source.name, category=cat)

    articles = scrape_rss_feed(source.rss_url, source.id, source.name, category=cat)
    if not articles:
        logger.info(f"RSS returned 0 articles for {source.name}, trying Playwright fallback")
        articles = scrape_with_playwright(source.rss_url, source.id, source.name, category=cat)
    return articles


def scrape_single_source(source_id: int, summarize: bool = False, classify: bool = False, tags: bool = False):
    """Scrape one source by ID. Used as the per-source job target."""
    db: Session = SessionLocal()
    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            logger.warning(f"Source ID {source_id} not found, removing job")
            return

        if not source.is_active:
            logger.info(f"Source {source.name} is inactive, skipping")
            return

        start_time = time.time()
        try:
            articles = _get_articles(source)
            found = len(articles)
            inserted = 0
            skipped = 0
            errors = []
            new_articles = []

            for article_data in articles:
                existing = db.query(Article).filter(
                    Article.url_hash == article_data["url_hash"]
                ).first()

                if existing:
                    skipped += 1
                    continue

                try:
                    article = Article(**article_data)
                    db.add(article)
                    inserted += 1
                    new_articles.append(article_data)
                except Exception as e:
                    errors.append(
                        f"Failed to insert {article_data.get('title', 'unknown')}: {str(e)}"
                    )

            duration = int(time.time() - start_time)

            log = ScrapeLog(
                source_id=source.id,
                articles_found=found,
                articles_inserted=inserted,
                articles_skipped=skipped,
                errors="\n".join(errors) if errors else None,
                duration_seconds=duration,
            )
            db.add(log)
            db.commit()

            # Summarize, classify, and tag new articles in background (non-blocking)
            if new_articles and summarize:
                _summarize_new_articles(new_articles)
            if new_articles and classify:
                _classify_new_articles(new_articles)
            if new_articles and tags:
                _extract_tags_batch(new_articles)

            logger.info(
                f"Scraped {source.name}: found={found}, inserted={inserted}, "
                f"skipped={skipped}, duration={duration}s"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error scraping {source.name}: {e}")
            # Write failure to ScrapeLog so admin panel can see it
            try:
                fail_db = SessionLocal()
                try:
                    fail_log = ScrapeLog(
                        source_id=source_id,
                        articles_found=0,
                        articles_inserted=0,
                        articles_skipped=0,
                        errors=str(e),
                        duration_seconds=int(time.time() - start_time),
                    )
                    fail_db.add(fail_log)
                    fail_db.commit()
                finally:
                    fail_db.close()
            except Exception as log_err:
                logger.error(f"Failed to write error ScrapeLog: {log_err}")
    finally:
        db.close()


def run_scheduled_scrape(summarize: bool = False, classify: bool = False, tags: bool = False):
    """Scrape all active sources sequentially. Used by admin trigger."""
    db: Session = SessionLocal()
    try:
        source_ids = [
            s.id for s in db.query(Source).filter(Source.is_active == True).all()
        ]
    finally:
        db.close()

    for sid in source_ids:
        scrape_single_source(sid, summarize=summarize, classify=classify, tags=tags)


def schedule_source_jobs(scheduler: BackgroundScheduler):
    """Read active sources from DB and create one APScheduler job per source
    using each source's scrape_interval_min."""
    db: Session = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.is_active == True).all()
    finally:
        db.close()

    active_job_ids = set()

    for source in sources:
        job_id = f"source_{source.id}"
        interval = source.scrape_interval_min or 30
        active_job_ids.add(job_id)

        scheduler.add_job(
            scrape_single_source,
            trigger=IntervalTrigger(minutes=interval),
            id=job_id,
            name=f"Scrape: {source.name}",
            replace_existing=True,
            kwargs={"source_id": source.id},
        )
        logger.info(f"Scheduled job '{job_id}' every {interval} min for {source.name}")

    # Remove jobs for sources that no longer exist or are inactive
    for job in scheduler.get_jobs():
        if job.id.startswith("source_") and job.id not in active_job_ids:
            scheduler.remove_job(job.id)
            logger.info(f"Removed stale job: {job.id}")


def run_github_scrape():
    """Scrape GitHub repos and upsert updates."""
    from app.scrapers.github_scraper import scrape_all_repos
    from config.settings import get_settings

    settings = get_settings()
    token = settings.github_token

    updates = scrape_all_repos(token)
    if not updates:
        logger.info("GitHub scrape returned 0 updates")
        return

    db = SessionLocal()
    try:
        inserted = 0
        seen = set()
        for u in updates:
            url_hash = u.get("url_hash")
            if not url_hash or url_hash in seen:
                continue
            seen.add(url_hash)

            existing = db.query(GithubUpdate).filter(GithubUpdate.url_hash == url_hash).first()
            if existing:
                continue

            try:
                db.add(GithubUpdate(**u))
                inserted += 1
            except Exception:
                pass

        db.commit()
        logger.info(f"GitHub scrape: {inserted} new updates from {len(updates)} total")
    except Exception as e:
        db.rollback()
        logger.error(f"GitHub scrape failed: {e}")
    finally:
        db.close()


def schedule_github_job(scheduler: BackgroundScheduler):
    """Schedule the GitHub watch job."""
    from config.settings import get_settings
    settings = get_settings()
    interval = settings.github_watch_interval_minutes

    scheduler.add_job(
        run_github_scrape,
        trigger=IntervalTrigger(minutes=interval),
        id="github_watch",
        name="GitHub AI Watch",
        replace_existing=True,
    )
    logger.info(f"Scheduled GitHub watch job every {interval} min")


def start_scheduler(interval_minutes: int = 30, cron_expression: str = None):
    """Start the background scheduler with per-source jobs.

    interval_minutes and cron_expression are kept for signature compatibility
    but per-source intervals come from the DB.
    """
    scheduler = BackgroundScheduler()
    schedule_source_jobs(scheduler)
    schedule_github_job(scheduler)
    scheduler.start()
    logger.info("Scheduler started with per-source intervals")
    return scheduler
