import sys
import secrets
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, text

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from app.db.database import get_db
from app.models import Article, Source, ScrapeLog, Tag, ArticleTag, ArticleViewDaily, SiteViewDaily, Category, ArticleCategory, DiscoveredProject, GithubRepo
from config.settings import get_settings

router = APIRouter()
BASE_DIR = Path(__file__).parent.parent.parent.parent / "frontend"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

security = HTTPBearer()


def _create_token(username: str) -> str:
    settings = get_settings()
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.admin_token_expire_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.admin_secret_key, algorithm="HS256")


def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.admin_secret_key, algorithms=["HS256"])
        return payload.get("sub", "admin")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/admin/login")
async def admin_login(body: LoginRequest):
    settings = get_settings()
    correct_user = secrets.compare_digest(body.username, settings.admin_user)
    correct_pass = secrets.compare_digest(body.password, settings.admin_password)
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token(body.username)
    return JSONResponse({"token": token, "expires_hours": settings.admin_token_expire_hours})


@router.get("/admin/verify")
async def admin_verify(user: str = Depends(verify_admin)):
    return JSONResponse({"valid": True, "user": user})


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
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


# ─── Feature Status ───

@router.get("/admin/status")
async def feature_status(user: str = Depends(verify_admin)):
    """Check which features are configured and available."""
    settings = get_settings()
    status = {}

    # Groq API
    status["groq"] = {
        "configured": bool(settings.groq_api_key),
        "available": False,
    }
    if settings.groq_api_key:
        try:
            import groq
            status["groq"]["available"] = True
        except ImportError:
            status["groq"]["error"] = "groq package not installed"

    # Playwright
    status["playwright"] = {
        "configured": False,
        "available": False,
    }
    try:
        import playwright
        status["playwright"]["configured"] = True
        # Check if browser is installed
        from pathlib import Path
        cache_dir = Path.home() / ".cache" / "ms-playwright"
        if cache_dir.exists() and any(cache_dir.iterdir()):
            status["playwright"]["available"] = True
        else:
            status["playwright"]["error"] = "Run: playwright install chromium"
    except ImportError:
        status["playwright"]["error"] = "playwright package not installed"

    # Classifier
    status["classifier"] = {
        "configured": False,
        "available": False,
    }
    try:
        from sentence_transformers import CrossEncoder
        status["classifier"]["configured"] = True
        # Check if model is cached
        from pathlib import Path
        model_cache = Path.home() / ".cache" / "huggingface" / "hub"
        if model_cache.exists():
            model_dirs = list(model_cache.glob("*nli-deberta*"))
            if not model_dirs:
                model_dirs = list(model_cache.glob("*nli*MiniLM*"))
            if model_dirs:
                status["classifier"]["available"] = True
            else:
                status["classifier"]["error"] = "Model not downloaded yet"
        else:
            status["classifier"]["error"] = "Model not downloaded yet"
    except ImportError:
        status["classifier"]["error"] = "sentence-transformers package not installed"

    # SEO Pipeline
    status["seo"] = {
        "configured": True,
        "available": True,
        "note": "Rule-based, no external dependencies",
    }

    # Site URL
    status["site_url"] = settings.site_url

    return status


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


@router.post("/admin/scrape/finance")
async def trigger_finance_scrape(user: str = Depends(verify_admin)):
    """Manually trigger finance education scrape."""
    from app.scheduler import run_finance_scrape

    thread = threading.Thread(target=run_finance_scrape, daemon=True)
    thread.start()
    return {"status": "ok", "message": "Finance education scrape triggered"}


@router.post("/admin/scrape/prompts")
async def trigger_prompts_scrape(user: str = Depends(verify_admin)):
    """Manually trigger awesome-chatgpt-prompts scrape."""
    from app.scheduler import run_prompts_scrape

    thread = threading.Thread(target=run_prompts_scrape, daemon=True)
    thread.start()
    return {"status": "ok", "message": "Prompts CSV scrape triggered"}


# ─── Analytics Endpoints ───

@router.get("/admin/analytics/views")
async def analytics_views(days: int = 7, user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Daily site views for the last N days. Used for the line chart."""
    from datetime import date as date_type, timedelta
    since = date_type.today() - timedelta(days=days)
    rows = (
        db.query(SiteViewDaily)
        .filter(SiteViewDaily.view_date >= since)
        .order_by(SiteViewDaily.view_date)
        .all()
    )
    data = [{
        "view_date": str(r.view_date),
        "total_views": r.total_views or 0,
        "desktop": r.desktop or 0,
        "mobile": r.mobile or 0,
        "bot": r.bot or 0,
    } for r in rows]
    return JSONResponse({"data": data, "days": days})


@router.get("/admin/analytics/sources")
async def analytics_sources(days: int = 7, user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Article count per source per day. Used for stacked bar chart."""
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            Source.name,
            func.date(Article.created_at).label("day"),
            func.count(Article.id).label("count"),
        )
        .join(Source, Article.source_id == Source.id)
        .filter(Article.created_at >= since, Article.deleted_at.is_(None))
        .group_by(Source.name, func.date(Article.created_at))
        .order_by(func.date(Article.created_at))
        .all()
    )
    data = [{"name": r[0], "day": str(r[1]), "count": r[2]} for r in rows]
    return JSONResponse({"data": data})


@router.get("/admin/analytics/categories")
async def analytics_categories(user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Article count per category. Used for doughnut chart."""
    rows = (
        db.query(Category.name, func.count(ArticleCategory.article_id).label("count"))
        .outerjoin(ArticleCategory, Category.id == ArticleCategory.category_id)
        .group_by(Category.name)
        .order_by(desc("count"))
        .limit(12)
        .all()
    )
    data = [{"name": r[0] or "Uncategorized", "count": r[1]} for r in rows]
    return JSONResponse({"data": data})


@router.get("/admin/analytics/activity")
async def analytics_activity(limit: int = 30, user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Recent scrape logs + new articles for live activity feed."""
    sources_map = {s.id: s.name for s in db.query(Source).all()}

    logs = (
        db.query(ScrapeLog)
        .order_by(desc(ScrapeLog.scraped_at))
        .limit(limit)
        .all()
    )
    articles = (
        db.query(Article)
        .filter(Article.deleted_at.is_(None))
        .order_by(desc(Article.created_at))
        .limit(limit)
        .all()
    )

    events = []
    for l in logs:
        events.append({
            "type": "scrape",
            "label": sources_map.get(l.source_id, "Unknown"),
            "value": l.articles_found,
            "status": "error" if l.errors else "success",
            "ts": l.scraped_at.isoformat() if l.scraped_at else None,
        })
    for a in articles:
        events.append({
            "type": "article",
            "label": a.title,
            "value": None,
            "status": "new",
            "ts": a.created_at.isoformat() if a.created_at else None,
        })

    events.sort(key=lambda x: x["ts"] or "", reverse=True)
    return JSONResponse({"data": events[:limit]})


@router.get("/admin/analytics/engagement")
async def analytics_engagement(days: int = 7, user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Top articles by views and top tags."""
    from datetime import date as date_type, timedelta
    since = date_type.today() - timedelta(days=days)

    top_articles = (
        db.query(
            Article.title,
            Article.slug,
            func.sum(ArticleViewDaily.view_count).label("views"),
        )
        .join(ArticleViewDaily, Article.id == ArticleViewDaily.article_id)
        .filter(ArticleViewDaily.view_date >= since)
        .group_by(Article.title, Article.slug)
        .order_by(desc("views"))
        .limit(10)
        .all()
    )

    week_ago = datetime.now(timezone.utc) - timedelta(days=days)
    top_tags = (
        db.query(Tag.name, func.count(ArticleTag.article_id).label("count"))
        .join(ArticleTag, Tag.id == ArticleTag.tag_id)
        .join(Article, ArticleTag.article_id == Article.id)
        .filter(Article.created_at >= week_ago, Article.deleted_at.is_(None))
        .group_by(Tag.name)
        .order_by(desc("count"))
        .limit(10)
        .all()
    )

    return JSONResponse({
        "top_articles": [{"title": r[0], "slug": r[1], "views": r[2]} for r in top_articles],
        "top_tags": [{"name": r[0], "count": r[1]} for r in top_tags],
        "days": days,
    })


# ── OS Radar Admin ───────────────────────────────────────────────

@router.post("/admin/radar/run")
def admin_radar_run(
    strategy: str = "star_accelerators",
    user: str = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """Trigger immediate radar strategy run in background thread."""
    settings = get_settings()
    if not settings.github_token:
        raise HTTPException(400, "GITHUB_TOKEN not set")

    valid = [
        "trending_languages", "topic_surfing", "star_accelerators",
        "fresh_active", "fork_signals",
    ]
    if strategy not in valid:
        raise HTTPException(400, f"Unknown strategy. Valid: {valid}")

    def run():
        from app.db.database import SessionLocal
        from app.scrapers.os_radar import run_discovery_strategy
        bg_db = SessionLocal()
        try:
            run_discovery_strategy(strategy, settings.github_token, bg_db)
        finally:
            bg_db.close()

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"status": "started", "strategy": strategy})


@router.post("/admin/radar/promote/{project_id}")
def admin_radar_promote(
    project_id: int,
    user: str = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """Promote a discovered project to the GitHub watch list."""
    project = db.query(DiscoveredProject).get(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.promoted_to_watch:
        raise HTTPException(400, "Already promoted to watch list")

    existing = db.query(GithubRepo).filter_by(full_name=project.full_name).first()
    if not existing:
        db.add(GithubRepo(
            owner=project.owner,
            name=project.repo,
            full_name=project.full_name,
            description=project.description,
            stars=project.stars,
            language=project.language or "General",
            category=project.language or "General",
            is_active=True,
        ))

    project.promoted_to_watch = True
    db.commit()
    return JSONResponse({"status": "promoted", "full_name": project.full_name})


@router.get("/admin/radar/stats")
def admin_radar_stats(user: str = Depends(verify_admin), db: Session = Depends(get_db)):
    """Radar health and coverage stats."""
    stats = db.execute(text(
        "SELECT COUNT(*) as total_discovered, "
        "COUNT(*) FILTER (WHERE is_active) as active, "
        "COUNT(*) FILTER (WHERE potential_score > 70 AND stars < 5000) as hidden_gems, "
        "COUNT(*) FILTER (WHERE promoted_to_watch) as promoted, "
        "ROUND(AVG(potential_score)::numeric, 1) as avg_score, "
        "COUNT(DISTINCT language) as languages_covered, "
        "COUNT(DISTINCT discovery_source) as strategies_used, "
        "MAX(last_scored) as last_scored "
        "FROM discovered_projects"
    )).fetchone()

    from app.models import RadarRunLog
    recent_runs = db.query(RadarRunLog).order_by(
        RadarRunLog.started_at.desc()
    ).limit(10).all()

    return JSONResponse({
        "stats": dict(stats._mapping) if stats else {},
        "recent_runs": [
            {
                "strategy": r.strategy,
                "status": r.status,
                "repos_found": r.repos_found,
                "repos_new": r.repos_new,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in recent_runs
        ],
    })


# ── Scheduler Jobs ─────────────────────────────────────────────

def _format_trigger(trigger) -> tuple[str, str]:
    """Return (type, human-readable schedule) for an APScheduler trigger."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    if isinstance(trigger, CronTrigger):
        field_map = {f.name: str(f) for f in trigger.fields}
        parts = []
        hour = field_map.get("hour", "*")
        minute = field_map.get("minute", "*")
        dow = field_map.get("day_of_week", "*")

        if hour != "*":
            parts.append(f"at {hour.zfill(2)}:{minute.zfill(2)}")
        if dow != "*":
            days = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat"}
            parts.append(f"on {days.get(dow, dow)}")

        if not parts:
            return "cron", field_map.get("hour", "*") + ":" + field_map.get("minute", "*")
        return "cron", " ".join(parts)

    elif isinstance(trigger, IntervalTrigger):
        interval = trigger.interval
        total_seconds = int(interval.total_seconds())
        if total_seconds >= 86400:
            days = total_seconds // 86400
            return "interval", f"every {days}d"
        elif total_seconds >= 3600:
            hours = total_seconds // 3600
            return "interval", f"every {hours}h"
        elif total_seconds >= 60:
            minutes = total_seconds // 60
            return "interval", f"every {minutes}m"
        else:
            return "interval", f"every {total_seconds}s"
    return "unknown", str(trigger)


def _categorize_job(job_id: str) -> str:
    """Categorize a job by its ID prefix."""
    if job_id.startswith("radar_"):
        return "radar"
    if job_id.startswith("github_"):
        return "github"
    if job_id.startswith("source_"):
        return "sources"
    if job_id.startswith("seo"):
        return "seo"
    if job_id.startswith("finance"):
        return "finance"
    if job_id.startswith("prompt"):
        return "prompts"
    return "other"


@router.get("/admin/scheduler/jobs")
async def scheduler_jobs(request: Request, user: str = Depends(verify_admin)):
    """List all registered APScheduler jobs with their status."""
    scheduler = request.app.state.scheduler
    jobs = scheduler.get_jobs()

    result = []
    for job in jobs:
        trigger_type, trigger_detail = _format_trigger(job.trigger)
        result.append({
            "id": job.id,
            "name": job.name or job.id,
            "category": _categorize_job(job.id),
            "trigger_type": trigger_type,
            "schedule": trigger_detail,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "running": getattr(job, "pending", False),
        })

    # Sort: by category then name
    order = {"sources": 0, "github": 1, "finance": 2, "prompts": 3, "seo": 4, "radar": 5, "other": 6}
    result.sort(key=lambda x: (order.get(x["category"], 9), x["name"]))

    return JSONResponse({"jobs": result, "total": len(result)})


@router.post("/admin/scheduler/jobs/{job_id}/run")
async def run_scheduler_job(job_id: str, request: Request, user: str = Depends(verify_admin)):
    """Trigger any scheduler job immediately by its ID."""
    scheduler = request.app.state.scheduler
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    try:
        job.func(*job.args, **job.kwargs)
        return JSONResponse({"status": "ok", "message": f"Job '{job_id}' triggered"})
    except Exception as e:
        raise HTTPException(500, f"Job failed: {e}")
