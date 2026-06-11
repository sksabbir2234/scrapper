import sys
import time
import subprocess
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Source, Article, ScrapeLog, GithubUpdate, GithubRepo, GithubRepoSnapshot, GithubWeeklyDigest, GithubScrapeLog, FinanceResource, PromptLibrary
from app.scrapers.rss_scraper import scrape_rss_feed
from app.scrapers.playwright_scraper import scrape_with_playwright
from app.ai.summarizer import summarize_article
from app.ai.classifier import classify_article, classify_and_store
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

                classify_and_store(article.id, article.title, article.content_text, db)

            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Classification batch failed: {e}")
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


def _summarize_new_articles(articles_data: list[dict]):
    """Run Groq summarization on newly inserted articles in a background thread.
    After summarization, feeds results into SEO pipeline."""
    def _run():
        db = SessionLocal()
        processed_ids = []
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
                    processed_ids.append(article.id)
                    logger.info(f"Summarized: {article.title[:50]}...")

            db.commit()

            # Feed summarized articles into SEO pipeline
            if processed_ids:
                try:
                    from app.seo.pipeline import process_article_seo
                    seo_db = SessionLocal()
                    try:
                        for aid in processed_ids:
                            process_article_seo(aid, seo_db)
                    finally:
                        seo_db.close()
                    logger.info(f"SEO pipeline processed {len(processed_ids)} summarized articles")
                except Exception as seo_err:
                    logger.error(f"SEO pipeline after summarization failed: {seo_err}")

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

            seen_urls = set()
            for article_data in articles:
                # Check DB for existing by url_hash OR original_url
                existing = db.query(Article).filter(
                    (Article.url_hash == article_data["url_hash"]) |
                    (Article.original_url == article_data["original_url"])
                ).first()

                if existing:
                    skipped += 1
                    continue

                # Also skip in-batch duplicates
                if article_data["original_url"] in seen_urls:
                    skipped += 1
                    continue
                seen_urls.add(article_data["original_url"])

                try:
                    with db.begin_nested():
                        article = Article(**article_data)
                        db.add(article)
                        db.flush()
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
    """Scrape GitHub repos: update metadata + insert new updates."""
    from app.scrapers.github_scraper import scrape_all_repos
    from config.settings import get_settings
    import time as _time

    settings = get_settings()
    token = settings.github_token
    start = _time.time()
    errors = []

    repo_metadata, updates = scrape_all_repos(token)

    db = SessionLocal()
    try:
        # Phase 1: Update repo metadata
        repos_updated = 0
        for meta in repo_metadata:
            repo = db.query(GithubRepo).filter(GithubRepo.full_name == meta["full_name"]).first()
            if not repo:
                continue
            repo.stars = meta["stars"]
            repo.forks = meta["forks"]
            repo.open_issues = meta["open_issues"]
            repo.watchers = meta["watchers"]
            repo.description = meta.get("description") or repo.description
            repo.language = meta.get("language") or repo.language
            repo.license = meta.get("license") or repo.license
            repo.is_archived = meta.get("is_archived", False)
            repo.stats_updated_at = datetime.now(timezone.utc)
            repos_updated += 1

        # Phase 2: Insert new updates
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

            # Resolve repo_id from repo_name
            repo_name = u.get("repo_name")
            repo_obj = db.query(GithubRepo).filter(GithubRepo.full_name == repo_name).first()
            if repo_obj:
                u["repo_id"] = repo_obj.id

            try:
                with db.begin_nested():
                    # Remove label before creating if it's not a column we set directly
                    update_data = {k: v for k, v in u.items()}
                    db.add(GithubUpdate(**update_data))
                    db.flush()
                inserted += 1
            except Exception as e:
                errors.append(str(e))

        db.commit()

        # Write scrape log
        duration = int(_time.time() - start)
        log = GithubScrapeLog(
            repos_scraped=len(repo_metadata),
            updates_found=len(updates),
            updates_inserted=inserted,
            repos_updated=repos_updated,
            errors="\n".join(errors) if errors else None,
            duration_seconds=duration,
        )
        db.add(log)
        db.commit()

        logger.info(
            f"GitHub scrape: {inserted} new updates, {repos_updated} repos updated, "
            f"{len(updates)} total, {duration}s"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"GitHub scrape failed: {e}")
    finally:
        db.close()


def run_github_daily_snapshot():
    """Take a daily snapshot of all tracked GitHub repos for trend computation."""
    from datetime import date

    db = SessionLocal()
    try:
        today = date.today()
        repos = db.query(GithubRepo).all()
        snapshots_added = 0

        for repo in repos:
            existing = db.query(GithubRepoSnapshot).filter(
                GithubRepoSnapshot.repo_id == repo.id,
                GithubRepoSnapshot.snapshot_date == today,
            ).first()
            if existing:
                continue

            snapshot = GithubRepoSnapshot(
                repo_id=repo.id,
                stars=repo.stars,
                forks=repo.forks,
                open_issues=repo.open_issues,
                watchers=repo.watchers,
                snapshot_date=today,
            )
            db.add(snapshot)
            snapshots_added += 1

        # Compute trending scores
        week_ago = today - timedelta(days=7)
        for repo in repos:
            old_snap = db.query(GithubRepoSnapshot).filter(
                GithubRepoSnapshot.repo_id == repo.id,
                GithubRepoSnapshot.snapshot_date == week_ago,
            ).first()
            if old_snap and old_snap.stars and old_snap.stars > 0:
                growth = (repo.stars - old_snap.stars) / old_snap.stars * 100
                repo.trending_score = round(growth, 2)
            else:
                repo.trending_score = 0.0

        db.commit()
        logger.info(f"GitHub daily snapshot: {snapshots_added} snapshots added")
    except Exception as e:
        db.rollback()
        logger.error(f"GitHub daily snapshot failed: {e}")
    finally:
        db.close()


def run_github_weekly_digest():
    """Generate a weekly digest of GitHub activity."""
    from datetime import date, timedelta
    import json

    db = SessionLocal()
    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)

        # Check if digest already exists
        existing = db.query(GithubWeeklyDigest).filter(
            GithubWeeklyDigest.week_start == week_start
        ).first()
        if existing:
            logger.info(f"Weekly digest for {week_start} already exists, skipping")
            return

        # Count updates from this week
        week_updates = db.query(GithubUpdate).filter(
            GithubUpdate.published_at >= datetime.combine(week_start, datetime.min.time().replace(tzinfo=timezone.utc)),
            GithubUpdate.published_at <= datetime.combine(week_end + timedelta(days=1), datetime.min.time().replace(tzinfo=timezone.utc)),
        ).all()

        total_releases = sum(1 for u in week_updates if u.update_type == "release")
        total_commits = sum(1 for u in week_updates if u.update_type == "commit")
        total_prs = sum(1 for u in week_updates if u.update_type == "pr")
        breaking = sum(1 for u in week_updates if u.is_breaking)

        # Top repos by activity
        from collections import Counter
        repo_counts = Counter(u.repo_name for u in week_updates)
        top_repos = [{"repo": name, "updates": count} for name, count in repo_counts.most_common(5)]

        # Top growers
        repos = db.query(GithubRepo).order_by(GithubRepo.trending_score.desc()).limit(3).all()
        growers = [{"label": r.label, "score": r.trending_score} for r in repos if r.trending_score > 0]

        # Build summary
        summary_parts = [f"This week: {total_releases} releases, {total_commits} commits, {total_prs} PRs across {len(set(u.repo_name for u in week_updates))} repos."]
        if breaking:
            summary_parts.append(f"{breaking} breaking change{'s' if breaking > 1 else ''} detected.")
        if top_repos:
            summary_parts.append(f"Most active: {', '.join(r['repo'] for r in top_repos[:3])}.")
        if growers:
            grower_strs = [f"{g['label']} (+{g['score']}%)" for g in growers]
            summary_parts.append(f"Top growers: {', '.join(grower_strs)}.")

        digest = GithubWeeklyDigest(
            week_start=week_start,
            week_end=week_end,
            total_releases=total_releases,
            total_commits=total_commits,
            total_prs=total_prs,
            breaking_changes=breaking,
            top_repos=json.dumps(top_repos),
            summary_text=" ".join(summary_parts),
        )
        db.add(digest)
        db.commit()
        logger.info(f"Weekly digest generated for {week_start}")
    except Exception as e:
        db.rollback()
        logger.error(f"Weekly digest failed: {e}")
    finally:
        db.close()


def schedule_github_jobs(scheduler: BackgroundScheduler):
    """Schedule all GitHub watch jobs."""
    from apscheduler.triggers.cron import CronTrigger
    from config.settings import get_settings
    settings = get_settings()
    interval = settings.github_watch_interval_minutes

    # Main scrape job
    scheduler.add_job(
        run_github_scrape,
        trigger=IntervalTrigger(minutes=interval),
        id="github_watch",
        name="GitHub AI Watch",
        replace_existing=True,
    )
    logger.info(f"Scheduled GitHub watch job every {interval} min")

    # Daily snapshot at 2 AM
    scheduler.add_job(
        run_github_daily_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id="github_daily_snapshot",
        name="GitHub Daily Snapshot",
        replace_existing=True,
    )
    logger.info("Scheduled GitHub daily snapshot at 2:00 AM")

    # Weekly digest on Sunday at midnight
    scheduler.add_job(
        run_github_weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=0, minute=0),
        id="github_weekly_digest",
        name="GitHub Weekly Digest",
        replace_existing=True,
    )
    logger.info("Scheduled GitHub weekly digest on Sunday 00:00")


def run_finance_scrape():
    """Scrape free financial education RSS feeds and store in FinanceResource."""
    from app.scrapers.finance_scraper import scrape_all_finance_feeds

    db = SessionLocal()
    start = time.time()
    try:
        items = scrape_all_finance_feeds()
        inserted = 0
        skipped = 0

        for item in items:
            existing = db.query(FinanceResource).filter(
                FinanceResource.url == item["url"]
            ).first()
            if existing:
                skipped += 1
                continue

            try:
                with db.begin_nested():
                    resource = FinanceResource(
                        title=item["title"],
                        url=item["url"],
                        resource_type=item["resource_type"],
                        level=item["level"],
                        cost_level=item["cost_level"],
                        topic=item["topic"],
                        description=item["description"],
                    )
                    db.add(resource)
                    db.flush()
                inserted += 1
            except Exception as e:
                logger.error(f"Failed to insert finance resource {item.get('title', 'unknown')}: {e}")
                skipped += 1

        db.commit()
        duration = int(time.time() - start)
        logger.info(
            f"Finance scrape: {inserted} inserted, {skipped} skipped, "
            f"{len(items)} total, {duration}s"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Finance scrape failed: {e}")
    finally:
        db.close()


def run_prompts_scrape():
    """Fetch awesome-chatgpt-prompts CSV and store in PromptLibrary."""
    from app.scrapers.prompts_scraper import scrape_prompts

    db = SessionLocal()
    start = time.time()
    try:
        prompts = scrape_prompts()
        inserted = 0
        skipped = 0

        for p in prompts:
            existing = db.query(PromptLibrary).filter(
                PromptLibrary.title == p["title"]
            ).first()
            if existing:
                skipped += 1
                continue

            try:
                with db.begin_nested():
                    prompt = PromptLibrary(
                        title=p["title"],
                        prompt_text=p["prompt_text"],
                        category=p["category"],
                        tags=p["tags"],
                        difficulty=p["difficulty"],
                    )
                    db.add(prompt)
                    db.flush()
                inserted += 1
            except Exception as e:
                logger.error(f"Failed to insert prompt {p.get('title', 'unknown')}: {e}")
                skipped += 1

        db.commit()
        duration = int(time.time() - start)
        logger.info(
            f"Prompts scrape: {inserted} inserted, {skipped} skipped, "
            f"{len(prompts)} total, {duration}s"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Prompts scrape failed: {e}")
    finally:
        db.close()


def schedule_finance_jobs(scheduler: BackgroundScheduler):
    """Schedule daily finance education scrape at 6 AM."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        run_finance_scrape,
        trigger=CronTrigger(hour=6, minute=0),
        id="finance_daily_scrape",
        name="Finance Education Scrape",
        replace_existing=True,
    )
    logger.info("Scheduled finance education scrape daily at 6:00 AM")


def schedule_prompts_jobs(scheduler: BackgroundScheduler):
    """Schedule weekly prompts scrape on Monday at 3 AM."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        run_prompts_scrape,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="prompts_weekly_scrape",
        name="Prompts CSV Scrape",
        replace_existing=True,
    )
    logger.info("Scheduled prompts CSV scrape weekly on Monday 3:00 AM")


def run_ai_blog_scrape():
    """Scrape AI-focused blog articles from RSS feeds and store in Article table."""
    from app.scrapers.ai_blog_scraper import run_ai_blog_scrape as _run
    _run()


def schedule_ai_blog_jobs(scheduler: BackgroundScheduler):
    """Schedule AI blog scrape every 3 hours."""
    scheduler.add_job(
        run_ai_blog_scrape,
        trigger=IntervalTrigger(hours=3),
        id="ai_blog_scrape",
        name="AI Blog Scrape",
        replace_existing=True,
    )
    logger.info("Scheduled AI blog scrape every 3 hours")


def start_scheduler(interval_minutes: int = 30, cron_expression: str = None):
    """Start the background scheduler with per-source jobs.

    interval_minutes and cron_expression are kept for signature compatibility
    but per-source intervals come from the DB.
    """
    scheduler = BackgroundScheduler()
    schedule_source_jobs(scheduler)
    schedule_github_jobs(scheduler)
    schedule_seo_jobs(scheduler)
    schedule_radar_jobs(scheduler)
    schedule_finance_jobs(scheduler)
    schedule_prompts_jobs(scheduler)
    schedule_ai_blog_jobs(scheduler)
    scheduler.start()
    logger.info("Scheduler started with per-source intervals")
    return scheduler


def _run_seo_pipeline():
    """Sync wrapper for SEO pipeline."""
    try:
        from app.seo.pipeline import run_seo_on_new_articles
        db = SessionLocal()
        try:
            run_seo_on_new_articles(db, limit=50)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"SEO pipeline job failed: {e}")


def schedule_seo_jobs(scheduler):
    """Schedule SEO metadata generation every 30 minutes."""
    scheduler.add_job(
        _run_seo_pipeline,
        trigger=IntervalTrigger(minutes=30),
        id="seo_pipeline",
        name="SEO Pipeline",
        replace_existing=True,
    )
    logger.info("Scheduled SEO pipeline job every 30 min")


def _radar_strategy_job(strategy: str):
    """Sync wrapper for radar strategy — never crashes the scheduler."""
    try:
        from config.settings import get_settings
        from app.scrapers.os_radar import run_discovery_strategy
        settings = get_settings()
        db = SessionLocal()
        try:
            run_discovery_strategy(strategy, settings.github_token, db)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Radar scheduler job [{strategy}] crashed: {e}")


def schedule_radar_jobs(scheduler):
    """Schedule OS Radar discovery strategies staggered across 6h."""
    from config.settings import get_settings
    settings = get_settings()

    if not settings.github_token:
        logger.warning("GITHUB_TOKEN not set — OS Radar disabled")
        return

    strategies = [
        ("trending_languages", 0),
        ("topic_surfing", 60),
        ("star_accelerators", 120),
        ("fresh_active", 180),
        ("fork_signals", 240),
        ("rising_stars", 300),
        ("deep_search", 360),
        ("topic_deep_dive", 420),
    ]

    for name, delay_min in strategies:
        scheduler.add_job(
            _radar_strategy_job,
            kwargs={"strategy": name},
            trigger=IntervalTrigger(hours=8),
            start_date=datetime.now() + timedelta(minutes=delay_min),
            id=f"radar_{name}",
            name=f"Radar: {name}",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"Scheduled radar strategy: {name} (offset {delay_min}min)")
