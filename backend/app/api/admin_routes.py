import sys
import secrets
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_

from app.db.database import get_db
from app.models import Article, Source, ScrapeLog, Tag, ArticleTag
from config.settings import get_settings

router = APIRouter()
BASE_DIR = Path(__file__).parent.parent.parent.parent / "frontend"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    settings = get_settings()
    correct_user = secrets.compare_digest(credentials.username, settings.admin_user)
    correct_pass = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class SourceCreate(BaseModel):
    name: str
    domain: str
    rss_url: str
    category: str | None = None
    country_code: str | None = None
    credibility_score: int = 50
    scrape_type: str = "rss"
    scrape_interval_min: int = 30


class SourceUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    rss_url: str | None = None
    category: str | None = None
    country_code: str | None = None
    credibility_score: int | None = None
    scrape_type: str | None = None
    scrape_interval_min: int | None = None


class ScrapeOptions(BaseModel):
    summarize: bool = False
    classify: bool = False
    tags: bool = False


class BulkAction(BaseModel):
    action: str  # "enable" or "disable"
    source_ids: list[int] | None = None  # None = all


class BulkDelete(BaseModel):
    article_ids: list[int]


# ─── Dashboard Page ───

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user: str = Depends(verify_admin)):
    return templates.TemplateResponse("admin.html", {"request": request})


# ─── Stats API ───

@router.get("/admin/stats")
async def admin_stats(db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    total_articles = db.query(Article).filter(Article.deleted_at.is_(None)).count()
    total_sources = db.query(Source).count()
    active_sources = db.query(Source).filter(Source.is_active == True).count()
    total_tags = db.query(Tag).count()

    articles_today = db.query(Article).filter(
        Article.created_at >= today_start, Article.deleted_at.is_(None)
    ).count()
    articles_week = db.query(Article).filter(
        Article.created_at >= week_start, Article.deleted_at.is_(None)
    ).count()

    # Scrape success rate (last 100 logs)
    recent_logs = db.query(ScrapeLog).order_by(desc(ScrapeLog.scraped_at)).limit(100).all()
    success_count = sum(1 for l in recent_logs if not l.errors)
    success_rate = round(success_count / len(recent_logs) * 100) if recent_logs else 0

    # Last scrape time
    last_log = db.query(ScrapeLog).order_by(desc(ScrapeLog.scraped_at)).first()
    last_scrape = last_log.scraped_at.isoformat() if last_log else None

    # Category breakdown
    category_counts = (
        db.query(Article.category, func.count(Article.id))
        .filter(Article.deleted_at.is_(None), Article.category.isnot(None))
        .group_by(Article.category)
        .all()
    )

    return {
        "total_articles": total_articles,
        "total_sources": total_sources,
        "active_sources": active_sources,
        "total_tags": total_tags,
        "articles_today": articles_today,
        "articles_week": articles_week,
        "success_rate": success_rate,
        "last_scrape": last_scrape,
        "category_counts": {cat: count for cat, count in category_counts},
    }


# ─── Sources CRUD ───

@router.get("/admin/sources")
async def list_sources(db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    sources = db.query(Source).order_by(Source.name).all()
    result = []
    for s in sources:
        # Health: check last 3 scrape logs
        recent_logs = (
            db.query(ScrapeLog)
            .filter(ScrapeLog.source_id == s.id)
            .order_by(desc(ScrapeLog.scraped_at))
            .limit(3)
            .all()
        )

        if not recent_logs:
            health = "never"
        elif all(l.errors for l in recent_logs):
            health = "failing"
        elif recent_logs and recent_logs[0].scraped_at:
            hours_since = (datetime.now(timezone.utc) - recent_logs[0].scraped_at).total_seconds() / 3600
            if hours_since < 1:
                health = "healthy"
            elif hours_since < 2:
                health = "stale"
            else:
                health = "old"
        else:
            health = "unknown"

        last_log = recent_logs[0] if recent_logs else None
        article_count = db.query(Article).filter(
            Article.source_id == s.id, Article.deleted_at.is_(None)
        ).count()

        result.append({
            "id": s.id,
            "name": s.name,
            "domain": s.domain,
            "rss_url": s.rss_url,
            "category": s.category,
            "country_code": s.country_code,
            "credibility_score": s.credibility_score,
            "scrape_type": s.scrape_type,
            "scrape_interval_min": s.scrape_interval_min,
            "is_active": s.is_active,
            "health": health,
            "article_count": article_count,
            "last_scrape": last_log.scraped_at.isoformat() if last_log else None,
            "last_found": last_log.articles_found if last_log else 0,
            "last_errors": last_log.errors if last_log else None,
        })

    return result


@router.post("/admin/sources")
async def add_source(source: SourceCreate, request: Request, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    existing = db.query(Source).filter(
        or_(Source.name == source.name, Source.rss_url == source.rss_url)
    ).first()
    if existing:
        raise HTTPException(400, "Source with this name or RSS URL already exists")
    new_source = Source(**source.model_dump())
    db.add(new_source)
    db.commit()
    db.refresh(new_source)

    from app.scheduler import schedule_source_jobs
    schedule_source_jobs(request.app.state.scheduler)

    return {"status": "ok", "source_id": new_source.id}


@router.put("/admin/sources/{source_id}")
async def update_source(source_id: int, data: SourceUpdate, request: Request, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()

    from app.scheduler import schedule_source_jobs
    schedule_source_jobs(request.app.state.scheduler)

    return {"status": "ok"}


@router.delete("/admin/sources/{source_id}")
async def delete_source(source_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")

    article_count = db.query(Article).filter(Article.source_id == source_id).count()
    name = source.name

    db.delete(source)
    db.commit()

    from app.scheduler import schedule_source_jobs
    schedule_source_jobs(request.app.state.scheduler)

    return {"status": "ok", "name": name, "articles_affected": article_count}


@router.post("/admin/sources/{source_id}/toggle")
async def toggle_source(source_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")
    source.is_active = not source.is_active
    db.commit()

    from app.scheduler import schedule_source_jobs
    schedule_source_jobs(request.app.state.scheduler)

    return {"status": "ok", "is_active": source.is_active}


@router.post("/admin/sources/{source_id}/scrape")
async def scrape_single(source_id: int, options: ScrapeOptions = ScrapeOptions(), db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")

    from app.scheduler import scrape_single_source
    thread = threading.Thread(
        target=scrape_single_source,
        args=(source_id,),
        kwargs={"summarize": options.summarize, "classify": options.classify, "tags": options.tags},
        daemon=True,
    )
    thread.start()
    return {"status": "ok", "message": f"Scraping {source.name}"}


@router.post("/admin/sources/bulk")
async def bulk_sources(data: BulkAction, request: Request, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    query = db.query(Source)
    if data.source_ids:
        query = query.filter(Source.id.in_(data.source_ids))

    is_active = data.action == "enable"
    count = query.update({"is_active": is_active})
    db.commit()

    from app.scheduler import schedule_source_jobs
    schedule_source_jobs(request.app.state.scheduler)

    return {"status": "ok", "affected": count}


# ─── Articles ───

@router.get("/admin/articles")
async def list_articles(
    page: int = Query(1, ge=1),
    search: str = Query("", max_length=200),
    category: str = Query("", max_length=50),
    source_id: int = Query(0),
    db: Session = Depends(get_db),
    user: str = Depends(verify_admin),
):
    per_page = 25
    query = db.query(Article).filter(Article.deleted_at.is_(None))

    if search:
        query = query.filter(
            or_(Article.title.ilike(f"%{search}%"), Article.content_text.ilike(f"%{search}%"))
        )
    if category:
        query = query.filter(Article.category == category)
    if source_id:
        query = query.filter(Article.source_id == source_id)

    total = query.count()
    articles = (
        query.order_by(desc(Article.published_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Get source names
    sources = {s.id: s.name for s in db.query(Source).all()}

    result = []
    for a in articles:
        result.append({
            "id": a.id,
            "title": a.title,
            "slug": a.slug,
            "category": a.category,
            "source_name": sources.get(a.source_id, "Unknown"),
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "has_summary": bool(a.summary_ai),
            "image_url": a.image_url,
        })

    total_pages = max(1, (total + per_page - 1) // per_page)
    return {"articles": result, "total": total, "page": page, "total_pages": total_pages}


@router.delete("/admin/articles/{article_id}")
async def delete_article(article_id: int, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404, "Article not found")
    article.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}


@router.post("/admin/articles/bulk-delete")
async def bulk_delete_articles(data: BulkDelete, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    now = datetime.now(timezone.utc)
    count = (
        db.query(Article)
        .filter(Article.id.in_(data.article_ids), Article.deleted_at.is_(None))
        .update({"deleted_at": now})
    )
    db.commit()
    return {"status": "ok", "deleted": count}


# ─── Tags ───

@router.get("/admin/tags")
async def list_tags(db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    tag_counts = (
        db.query(Tag, func.count(ArticleTag.article_id).label("count"))
        .outerjoin(ArticleTag, Tag.id == ArticleTag.tag_id)
        .group_by(Tag.id)
        .order_by(desc("count"))
        .all()
    )
    return [{"id": t.id, "name": t.name, "slug": t.slug, "count": c} for t, c in tag_counts]


@router.delete("/admin/tags/{tag_id}")
async def delete_tag(tag_id: int, db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.query(ArticleTag).filter(ArticleTag.tag_id == tag_id).delete()
    db.delete(tag)
    db.commit()
    return {"status": "ok"}


# ─── Logs ───

@router.get("/admin/logs")
async def list_logs(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: str = Depends(verify_admin)):
    sources = {s.id: s.name for s in db.query(Source).all()}
    logs = db.query(ScrapeLog).order_by(desc(ScrapeLog.scraped_at)).limit(limit).all()

    return [{
        "id": l.id,
        "source_name": sources.get(l.source_id, "Unknown"),
        "articles_found": l.articles_found,
        "articles_inserted": l.articles_inserted,
        "articles_skipped": l.articles_skipped,
        "errors": l.errors,
        "duration_seconds": l.duration_seconds,
        "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
    } for l in logs]


# ─── Trigger Full Scrape ───

@router.post("/admin/scrape/trigger")
async def trigger_scrape(options: ScrapeOptions = ScrapeOptions(), user: str = Depends(verify_admin)):
    from app.scheduler import run_scheduled_scrape

    thread = threading.Thread(
        target=run_scheduled_scrape,
        kwargs={"summarize": options.summarize, "classify": options.classify, "tags": options.tags},
        daemon=True,
    )
    thread.start()

    features = []
    if options.summarize:
        features.append("summarize")
    if options.classify:
        features.append("classify")
    if options.tags:
        features.append("tags")
    msg = "Scrape triggered"
    if features:
        msg += f" with {', '.join(features)}"
    return {"status": "ok", "message": msg}
