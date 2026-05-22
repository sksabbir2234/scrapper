import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone, date as date_cls

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text

from app.db.database import get_db
from app.models import (
    Article, Source, ScrapeLog, Category, Tag, ArticleTag,
    GithubUpdate, GithubRepo, GithubRepoSnapshot, GithubWeeklyDigest,
    FinanceResource, FinanceQuizQuestion,
    PromptPattern, AIModelCard, AITool, AITip, OSSAlternative,
    ArticleView, ArticleViewDaily, SiteViewDaily,
    PromptLibrary, ArticleSEO,
)

BASE_DIR = Path(__file__).parent.parent.parent.parent / "frontend"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    articles = (
        db.query(Article)
        .filter(Article.deleted_at.is_(None))
        .order_by(desc(Article.published_at))
        .limit(50)
        .all()
    )
    categories = db.query(Category).filter(Category.is_active == True).all()
    return templates.TemplateResponse("index.html", {
        "request": request, "articles": articles, "categories": categories,
        "active_page": "home",
    })


@router.get("/articles", response_class=HTMLResponse)
async def articles_list(request: Request, page: int = 1, db: Session = Depends(get_db)):
    per_page = 20
    offset = (page - 1) * per_page

    total = db.query(Article).filter(Article.deleted_at.is_(None)).count()
    articles = (
        db.query(Article)
        .filter(Article.deleted_at.is_(None))
        .order_by(desc(Article.published_at))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_pages = (total + per_page - 1) // per_page
    categories = db.query(Category).filter(Category.is_active == True).all()

    return templates.TemplateResponse("articles.html", {
        "request": request, "articles": articles, "page": page,
        "total_pages": total_pages, "total": total, "categories": categories,
        "active_page": "",
    })


@router.get("/articles/{slug}", response_class=HTMLResponse)
async def article_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.slug == slug).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    article.view_count += 1

    # View tracking — non-blocking, never breaks article loading
    try:
        raw_ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(raw_ip.encode()).hexdigest()[:16]
        ua = request.headers.get("user-agent", "").lower()
        ua_type = (
            "bot" if any(b in ua for b in ["bot", "crawler", "spider", "slurp", "bytespider"])
            else "mobile" if "mobile" in ua
            else "desktop"
        )

        db.add(ArticleView(article_id=article.id, ip_hash=ip_hash, ua_type=ua_type))

        today = date_cls.today()
        db.execute(
            ArticleViewDaily.__table__.insert().values(
                article_id=article.id, view_date=today, view_count=1
            ).on_conflict_do_update(
                index_elements=["article_id", "view_date"],
                set_={"view_count": ArticleViewDaily.view_count + 1}
            )
        )
        db.execute(
            SiteViewDaily.__table__.insert().values(
                view_date=today, total_views=1, **{ua_type: 1}
            ).on_conflict_do_update(
                index_elements=["view_date"],
                set_={
                    "total_views": SiteViewDaily.total_views + 1,
                    ua_type: getattr(SiteViewDaily, ua_type) + 1,
                }
            )
        )
        db.commit()
    except Exception:
        db.rollback()

    article_tags = (
        db.query(Tag)
        .join(ArticleTag, Tag.id == ArticleTag.tag_id)
        .filter(ArticleTag.article_id == article.id)
        .all()
    )

    return templates.TemplateResponse("article.html", {
        "request": request, "article": article, "article_tags": article_tags,
        "active_page": "",
    })


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request, db: Session = Depends(get_db)):
    categories = db.query(Category).filter(Category.is_active == True).all()
    category_counts = []
    for cat in categories:
        count = db.query(Article).filter(Article.category == cat.slug, Article.deleted_at.is_(None)).count()
        category_counts.append({"category": cat, "count": count})
    return templates.TemplateResponse("categories.html", {
        "request": request, "category_counts": category_counts,
        "active_page": "categories",
    })


@router.get("/categories/{slug}", response_class=HTMLResponse)
async def category_detail(request: Request, slug: str, page: int = 1, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.slug == slug).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    per_page = 20
    total = db.query(Article).filter(Article.category == slug, Article.deleted_at.is_(None)).count()
    articles = (
        db.query(Article)
        .filter(Article.category == slug, Article.deleted_at.is_(None))
        .order_by(desc(Article.published_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse("category.html", {
        "request": request, "category": category, "articles": articles,
        "page": page, "total_pages": total_pages, "total": total,
        "active_page": "categories",
    })


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query(default=""), page: int = 1, db: Session = Depends(get_db)):
    per_page = 20
    offset = (page - 1) * per_page

    if not q.strip():
        return templates.TemplateResponse("search.html", {
            "request": request, "articles": [], "query": "", "total": 0, "page": 1, "total_pages": 0,
            "active_page": "",
        })

    ts_query = " & ".join(q.strip().split())
    fts_filter = func.to_tsvector("english", func.coalesce(Article.title, "") + " " + func.coalesce(Article.content_text, "")).match(ts_query)

    total = db.query(Article).filter(fts_filter, Article.deleted_at.is_(None)).count()
    articles = (
        db.query(Article)
        .filter(fts_filter, Article.deleted_at.is_(None))
        .order_by(desc(Article.published_at))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse("search.html", {
        "request": request, "articles": articles, "query": q,
        "total": total, "page": page, "total_pages": total_pages,
        "active_page": "",
    })


@router.get("/trending", response_class=HTMLResponse)
async def trending(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    hours_since_epoch = (now - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() / 3600

    # Score in SQL: (view_count * credibility/100) / (hours_old + 2)^1.5
    hours_old = func.greatest(
        (func.extract('epoch', now) - func.extract('epoch', Article.published_at)) / 3600.0,
        0.1
    )
    score_expr = (
        (func.coalesce(Article.view_count, 0) * (func.coalesce(Source.credibility_score, 50) / 100.0))
        / func.power(hours_old + 2, 1.5)
    ).label("trend_score")

    top_articles = (
        db.query(Article, score_expr)
        .join(Source, Article.source_id == Source.id)
        .filter(Article.deleted_at.is_(None), Article.published_at.isnot(None))
        .order_by(desc("trend_score"))
        .limit(30)
        .all()
    )
    articles = [a for a, _ in top_articles]

    return templates.TemplateResponse("trending.html", {
        "request": request, "articles": articles, "active_page": "trending",
    })


@router.get("/tags", response_class=HTMLResponse)
async def tag_list(request: Request, db: Session = Depends(get_db)):
    tag_rows = (
        db.query(Tag, func.count(ArticleTag.article_id).label("count"))
        .join(ArticleTag, Tag.id == ArticleTag.tag_id)
        .group_by(Tag.id)
        .order_by(desc("count"))
        .all()
    )
    tag_counts = [{"tag": row[0], "count": row[1]} for row in tag_rows]
    return templates.TemplateResponse("tags.html", {
        "request": request, "tags": tag_counts, "active_page": "",
    })


@router.get("/tags/{slug}", response_class=HTMLResponse)
async def tag_detail(slug: str, request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.slug == slug).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    per_page = 20
    query = (
        db.query(Article)
        .join(ArticleTag, Article.id == ArticleTag.article_id)
        .filter(ArticleTag.tag_id == tag.id, Article.deleted_at.is_(None))
    )
    total = query.count()
    articles = query.order_by(desc(Article.published_at)).offset((page - 1) * per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("tag_detail.html", {
        "request": request, "tag": tag, "articles": articles,
        "total": total, "page": page, "total_pages": total_pages,
        "active_page": "",
    })


@router.get("/health/scraper")
async def scraper_health(db: Session = Depends(get_db)):
    last_log = db.query(ScrapeLog).order_by(desc(ScrapeLog.scraped_at)).first()
    if not last_log:
        return {"status": "unknown", "message": "No scrape logs yet"}
    return {
        "status": "healthy",
        "last_scrape": str(last_log.scraped_at),
        "articles_found": last_log.articles_found,
        "articles_inserted": last_log.articles_inserted,
    }


# ── GitHub AI Watch ──────────────────────────────────────────────

@router.get("/github", response_class=HTMLResponse)
async def github_page(
    request: Request,
    category: str = "",
    sort: str = "stars",
    search: str = "",
    update_type: str = "",
    db: Session = Depends(get_db),
):
    # Repo query
    repo_query = db.query(GithubRepo)
    if category:
        repo_query = repo_query.filter(GithubRepo.category == category)
    if search:
        repo_query = repo_query.filter(
            GithubRepo.label.ilike(f"%{search}%")
            | GithubRepo.description.ilike(f"%{search}%")
            | GithubRepo.full_name.ilike(f"%{search}%")
        )
    if sort == "trending":
        repo_query = repo_query.order_by(desc(GithubRepo.trending_score))
    elif sort == "recent":
        repo_query = repo_query.order_by(desc(GithubRepo.stats_updated_at))
    elif sort == "name":
        repo_query = repo_query.order_by(GithubRepo.label)
    else:  # stars (default)
        repo_query = repo_query.order_by(desc(GithubRepo.stars))
    repos = repo_query.all()

    # Category counts
    cat_counts = {}
    for r in db.query(GithubRepo.category, func.count()).group_by(GithubRepo.category).all():
        if r[0]:
            cat_counts[r[0]] = r[1]

    # Latest weekly digest
    digest = db.query(GithubWeeklyDigest).order_by(desc(GithubWeeklyDigest.week_start)).first()

    # Recent updates (for feed section)
    update_query = db.query(GithubUpdate).order_by(desc(GithubUpdate.published_at))
    if update_type:
        update_query = update_query.filter(GithubUpdate.update_type == update_type)
    recent_updates = update_query.limit(30).all()

    # Global stats
    total_stars = db.query(func.sum(GithubRepo.stars)).scalar() or 0
    updates_this_week = db.query(GithubUpdate).filter(
        GithubUpdate.published_at >= datetime.now(timezone.utc) - __import__('datetime').timedelta(days=7)
    ).count()
    breaking_count = db.query(GithubUpdate).filter(GithubUpdate.is_breaking == True).count()
    trending_count = db.query(GithubRepo).filter(GithubRepo.trending_score > 0).count()

    return templates.TemplateResponse("github_updates.html", {
        "request": request, "repos": repos,
        "cat_counts": cat_counts, "current_category": category,
        "current_sort": sort, "current_search": search,
        "current_type": update_type,
        "digest": digest,
        "recent_updates": recent_updates,
        "total_stars": total_stars,
        "updates_this_week": updates_this_week,
        "breaking_count": breaking_count,
        "trending_count": trending_count,
        "active_page": "github",
    })


@router.get("/github/api/repos")
async def github_api_repos(category: str = "", sort: str = "stars", db: Session = Depends(get_db)):
    query = db.query(GithubRepo)
    if category:
        query = query.filter(GithubRepo.category == category)
    if sort == "trending":
        query = query.order_by(desc(GithubRepo.trending_score))
    else:
        query = query.order_by(desc(GithubRepo.stars))
    repos = query.all()
    return [{
        "id": r.id, "full_name": r.full_name, "label": r.label,
        "category": r.category, "description": r.description,
        "stars": r.stars, "forks": r.forks, "open_issues": r.open_issues,
        "language": r.language, "trending_score": r.trending_score,
        "repo_url": r.repo_url,
    } for r in repos]


@router.get("/github/api/repos/{repo_id}/history")
async def github_api_repo_history(repo_id: int, days: int = 30, db: Session = Depends(get_db)):
    from datetime import date, timedelta
    since = date.today() - timedelta(days=days)
    snapshots = db.query(GithubRepoSnapshot).filter(
        GithubRepoSnapshot.repo_id == repo_id,
        GithubRepoSnapshot.snapshot_date >= since,
    ).order_by(GithubRepoSnapshot.snapshot_date).all()
    return [{
        "date": str(s.snapshot_date), "stars": s.stars,
        "forks": s.forks, "open_issues": s.open_issues,
    } for s in snapshots]


@router.get("/github/api/trending")
async def github_api_trending(db: Session = Depends(get_db)):
    repos = db.query(GithubRepo).filter(
        GithubRepo.trending_score > 0
    ).order_by(desc(GithubRepo.trending_score)).limit(10).all()
    return [{
        "id": r.id, "label": r.label, "full_name": r.full_name,
        "stars": r.stars, "trending_score": r.trending_score,
    } for r in repos]


@router.get("/github/api/digest/latest")
async def github_api_digest_latest(db: Session = Depends(get_db)):
    digest = db.query(GithubWeeklyDigest).order_by(desc(GithubWeeklyDigest.week_start)).first()
    if not digest:
        return {"message": "No digest yet"}
    return {
        "week_start": str(digest.week_start), "week_end": str(digest.week_end),
        "total_releases": digest.total_releases, "total_commits": digest.total_commits,
        "total_prs": digest.total_prs, "breaking_changes": digest.breaking_changes,
        "top_repos": digest.top_repos, "summary_text": digest.summary_text,
    }


@router.get("/github/api/updates")
async def github_api_updates(
    update_type: str = "", repo: str = "", page: int = 1, per_page: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(GithubUpdate)
    if update_type:
        query = query.filter(GithubUpdate.update_type == update_type)
    if repo:
        query = query.filter(GithubUpdate.repo_name == repo)
    total = query.count()
    updates = query.order_by(desc(GithubUpdate.published_at)).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total, "page": page, "per_page": per_page,
        "items": [{
            "id": u.id, "repo_name": u.repo_name, "label": u.label,
            "update_type": u.update_type, "title": u.title,
            "body": (u.body or "")[:500], "external_url": u.external_url,
            "published_at": str(u.published_at) if u.published_at else None,
            "stars": u.stars, "language": u.language, "is_breaking": u.is_breaking,
        } for u in updates],
    }


# ── Opportunity Finder ───────────────────────────────────────────

@router.get("/opportunities", response_class=HTMLResponse)
async def opportunities_page(request: Request, q: str = ""):
    return templates.TemplateResponse("opportunities.html", {
        "request": request, "query": q, "results": [],
        "active_page": "",
    })


@router.get("/opportunities/search", response_class=HTMLResponse)
async def opportunities_search(request: Request, q: str = ""):
    from app.scrapers.opportunity_finder import find_opportunities
    from config.settings import get_settings
    settings = get_settings()
    results = []
    if q.strip():
        results = find_opportunities(q.strip(), settings.github_token)
    return templates.TemplateResponse("opportunities.html", {
        "request": request, "query": q, "results": results,
        "active_page": "",
    })


@router.get("/opportunities/api/search")
async def opportunities_api(q: str = "", limit: int = 30):
    from app.scrapers.opportunity_finder import find_opportunities
    from config.settings import get_settings
    settings = get_settings()
    if not q.strip():
        return {"results": []}
    results = find_opportunities(q.strip(), settings.github_token, limit)
    return {"results": results}


@router.get("/opportunities/export")
async def opportunities_export(q: str = ""):
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from app.scrapers.opportunity_finder import find_opportunities
    from config.settings import get_settings

    settings = get_settings()
    if not q.strip():
        return {"error": "No query provided"}

    results = find_opportunities(q.strip(), settings.github_token)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "rank", "name", "url", "stars", "open_issues", "language",
        "last_commit", "contributors", "score"
    ])
    writer.writeheader()
    for r in results:
        writer.writerow({k: r[k] for k in writer.fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=opportunities_{q.replace(' ', '_')}.csv"},
    )


# ── Finance Learning Hub ─────────────────────────────────────────

@router.get("/finance", response_class=HTMLResponse)
async def finance_page(request: Request):
    return templates.TemplateResponse("finance.html", {
        "request": request, "active_page": "finance",
    })


@router.get("/finance/api/concept-of-day")
async def finance_concept_of_day(db: Session = Depends(get_db)):
    import json
    concepts_path = Path(__file__).parent.parent.parent.parent / "config" / "seed" / "finance_concepts.json"
    if not concepts_path.exists():
        return {"error": "No concepts data"}
    with open(concepts_path, "r", encoding="utf-8") as f:
        concepts = json.load(f)
    day_index = datetime.now(timezone.utc).toordinal() % len(concepts)
    return concepts[day_index]


@router.get("/finance/api/market")
async def finance_market():
    from app.scrapers.market_data import fetch_market_snapshot
    from config.settings import get_settings
    settings = get_settings()
    return fetch_market_snapshot(ttl=settings.market_cache_ttl_seconds)


@router.get("/finance/api/quiz")
async def finance_quiz(db: Session = Depends(get_db)):
    import random
    questions = db.query(FinanceQuizQuestion).all()
    if not questions:
        return []
    selected = random.sample(questions, min(10, len(questions)))
    return [{
        "id": q.id, "question": q.question,
        "option_a": q.option_a, "option_b": q.option_b,
        "option_c": q.option_c, "option_d": q.option_d,
        "correct_answer": q.correct_answer, "explanation": q.explanation,
        "difficulty": q.difficulty, "topic": q.topic,
    } for q in selected]


@router.get("/finance/api/resources")
async def finance_resources(level: str = "", topic: str = "", db: Session = Depends(get_db)):
    query = db.query(FinanceResource).filter(FinanceResource.is_active == True)
    if level:
        query = query.filter(FinanceResource.level == level)
    if topic:
        query = query.filter(FinanceResource.topic == topic)
    resources = query.all()
    return [{
        "id": r.id, "title": r.title, "url": r.url,
        "resource_type": r.resource_type, "level": r.level,
        "topic": r.topic, "description": r.description,
    } for r in resources]


@router.get("/finance/api/glossary")
async def finance_glossary():
    import json
    concepts_path = Path(__file__).parent.parent.parent.parent / "config" / "seed" / "finance_concepts.json"
    if not concepts_path.exists():
        return []
    with open(concepts_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── AI Tips & Tricks ─────────────────────────────────────────────

@router.get("/ai-tips", response_class=HTMLResponse)
async def ai_tips_page(request: Request):
    return templates.TemplateResponse("ai_tips.html", {
        "request": request, "active_page": "ai_tips",
    })


@router.get("/ai-tips/api/patterns")
async def ai_tips_patterns(category: str = "", search: str = "", db: Session = Depends(get_db)):
    query = db.query(PromptPattern)
    if category:
        query = query.filter(PromptPattern.category == category)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (PromptPattern.name.ilike(search_term)) |
            (PromptPattern.pattern_text.ilike(search_term))
        )
    patterns = query.all()
    return [{
        "id": p.id, "name": p.name, "slug": p.slug,
        "category": p.category, "pattern_text": p.pattern_text,
        "example_input": p.example_input, "example_output": p.example_output,
        "tips": p.tips, "difficulty": p.difficulty,
    } for p in patterns]


@router.get("/ai-tips/api/models")
async def ai_tips_models(db: Session = Depends(get_db)):
    cards = db.query(AIModelCard).filter(AIModelCard.is_active == True).all()
    return [{
        "id": c.id, "name": c.name, "provider": c.provider,
        "model_type": c.model_type, "context_window": c.context_window,
        "pricing_note": c.pricing_note, "strengths": c.strengths,
        "weaknesses": c.weaknesses, "best_for": c.best_for,
    } for c in cards]


@router.get("/ai-tips/api/tools")
async def ai_tips_tools(db: Session = Depends(get_db)):
    tools = db.query(AITool).filter(AITool.is_active == True).all()
    return [{
        "id": t.id, "name": t.name, "url": t.url,
        "category": t.category, "description": t.description,
        "is_tool_of_week": t.is_tool_of_week,
    } for t in tools]


@router.get("/ai-tips/api/feed")
async def ai_tips_feed(page: int = 1, db: Session = Depends(get_db)):
    per_page = 20
    tips = db.query(AITip).order_by(desc(AITip.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    return [{
        "id": t.id, "title": t.title, "content": t.content,
        "category": t.category, "likes": t.likes,
        "is_featured": t.is_featured,
        "created_at": str(t.created_at) if t.created_at else None,
    } for t in tips]


@router.post("/ai-tips/api/tips/{tip_id}/like")
async def ai_tips_like(tip_id: int, db: Session = Depends(get_db)):
    tip = db.query(AITip).filter(AITip.id == tip_id).first()
    if not tip:
        raise HTTPException(status_code=404, detail="Tip not found")
    tip.likes = (tip.likes or 0) + 1
    db.commit()
    return {"likes": tip.likes}


@router.get("/ai-tips/api/digest")
async def ai_tips_digest(limit: int = 30, db: Session = Depends(get_db)):
    articles = (
        db.query(Article)
        .filter(Article.deleted_at.is_(None), Article.category == "ai_updates")
        .order_by(desc(Article.published_at))
        .limit(limit)
        .all()
    )
    return [{
        "id": a.id, "title": a.title, "slug": a.slug,
        "content": (a.content_text or "")[:300],
        "source": a.source.name if a.source else "Unknown",
        "image_url": a.image_url,
        "published_at": a.published_at.strftime("%b %d, %Y") if a.published_at else "",
        "original_url": a.original_url,
        "summary_ai": a.summary_ai,
    } for a in articles]


# ── Finance Digest ───────────────────────────────────────────────

@router.get("/finance/api/digest")
async def finance_digest(limit: int = 30, db: Session = Depends(get_db)):
    articles = (
        db.query(Article)
        .filter(Article.deleted_at.is_(None), Article.category == "finance")
        .order_by(desc(Article.published_at))
        .limit(limit)
        .all()
    )
    return [{
        "id": a.id, "title": a.title, "slug": a.slug,
        "content": (a.content_text or "")[:300],
        "source": a.source.name if a.source else "Unknown",
        "image_url": a.image_url,
        "published_at": a.published_at.strftime("%b %d, %Y") if a.published_at else "",
        "original_url": a.original_url,
        "summary_ai": a.summary_ai,
    } for a in articles]


# ── OSS Alternatives ─────────────────────────────────────────────

@router.get("/oss", response_class=HTMLResponse)
async def oss_page(request: Request, category: str = "", search: str = "", sort: str = "stars", db: Session = Depends(get_db)):
    query = db.query(OSSAlternative)
    if category:
        query = query.filter(OSSAlternative.category == category)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (OSSAlternative.oss_name.ilike(term)) |
            (OSSAlternative.paid_name.ilike(term)) |
            (OSSAlternative.oss_description.ilike(term))
        )
    if sort == "stars":
        query = query.order_by(desc(OSSAlternative.gh_stars))
    elif sort == "upvotes":
        query = query.order_by(desc(OSSAlternative.upvotes))
    else:
        query = query.order_by(desc(OSSAlternative.created_at))
    alternatives = query.all()
    categories = db.query(OSSAlternative.category, func.count()).group_by(OSSAlternative.category).all()
    total = db.query(OSSAlternative).count()
    return templates.TemplateResponse("oss.html", {
        "request": request, "alternatives": alternatives,
        "categories": categories, "total": total,
        "current_category": category, "current_search": search, "current_sort": sort,
        "active_page": "oss",
    })


@router.get("/oss/{slug}", response_class=HTMLResponse)
async def oss_detail_page(request: Request, slug: str, db: Session = Depends(get_db)):
    alt = db.query(OSSAlternative).filter(OSSAlternative.slug == slug).first()
    if not alt:
        raise HTTPException(status_code=404, detail="Not found")
    alt.views = (alt.views or 0) + 1
    db.commit()
    # Same paid tool alternatives
    related = db.query(OSSAlternative).filter(
        OSSAlternative.paid_name == alt.paid_name, OSSAlternative.id != alt.id
    ).limit(5).all()
    # Same category
    same_cat = db.query(OSSAlternative).filter(
        OSSAlternative.category == alt.category, OSSAlternative.id != alt.id
    ).limit(3).all()
    return templates.TemplateResponse("oss_detail.html", {
        "request": request, "alt": alt, "related": related, "same_cat": same_cat,
        "active_page": "oss",
    })


@router.get("/oss/api/list")
async def oss_api_list(category: str = "", search: str = "", sort: str = "stars", db: Session = Depends(get_db)):
    query = db.query(OSSAlternative)
    if category:
        query = query.filter(OSSAlternative.category == category)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (OSSAlternative.oss_name.ilike(term)) |
            (OSSAlternative.paid_name.ilike(term))
        )
    if sort == "stars":
        query = query.order_by(desc(OSSAlternative.gh_stars))
    elif sort == "upvotes":
        query = query.order_by(desc(OSSAlternative.upvotes))
    else:
        query = query.order_by(desc(OSSAlternative.created_at))
    alts = query.limit(100).all()
    return [{
        "id": a.id, "slug": a.slug, "oss_name": a.oss_name, "paid_name": a.paid_name,
        "category": a.category, "gh_stars": a.gh_stars, "gh_forks": a.gh_forks,
        "why_better": a.why_better, "difficulty": a.difficulty,
        "self_hostable": a.self_hostable, "upvotes": a.upvotes, "featured": a.featured,
    } for a in alts]


@router.post("/oss/api/{slug}/upvote")
async def oss_upvote(slug: str, db: Session = Depends(get_db)):
    alt = db.query(OSSAlternative).filter(OSSAlternative.slug == slug).first()
    if not alt:
        raise HTTPException(status_code=404, detail="Not found")
    alt.upvotes = (alt.upvotes or 0) + 1
    db.commit()
    return {"upvotes": alt.upvotes}


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return templates.TemplateResponse("jobs.html", {
        "request": request, "active_page": "jobs",
    })


@router.get("/jobs/api/list")
async def jobs_api_list(
    keyword: str = "",
    location: str = "",
    remote: str = "",
    source: str = "",
    page: int = 1,
    per_page: int = 20,
):
    from app.scrapers.job_scraper import fetch_live_jobs
    remote_only = remote.lower() in ("1", "true", "yes")
    jobs = fetch_live_jobs(keyword=keyword, location=location, remote_only=remote_only, source=source)
    total = len(jobs)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": jobs[start:end],
    }


@router.get("/jobs/api/stats")
async def jobs_api_stats(keyword: str = "", location: str = ""):
    from app.scrapers.job_scraper import fetch_job_stats
    return fetch_job_stats(keyword=keyword, location=location)


# ── SEO Endpoints ────────────────────────────────────────────────

from fastapi.responses import Response, PlainTextResponse
from datetime import timedelta

SITEMAP_CACHE = {"xml": None, "generated_at": None}
SITEMAP_TTL = 1800  # 30 minutes


@router.get("/sitemap.xml")
def sitemap_xml(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    if (SITEMAP_CACHE["xml"] and SITEMAP_CACHE["generated_at"]
            and (now - SITEMAP_CACHE["generated_at"]).total_seconds() < SITEMAP_TTL):
        return Response(SITEMAP_CACHE["xml"], media_type="application/xml")

    site_url = "http://localhost:8000"

    static_pages = [
        {"url": site_url, "priority": "1.0", "changefreq": "always"},
        {"url": f"{site_url}/trending", "priority": "0.9", "changefreq": "hourly"},
        {"url": f"{site_url}/categories", "priority": "0.8", "changefreq": "daily"},
        {"url": f"{site_url}/finance", "priority": "0.8", "changefreq": "hourly"},
        {"url": f"{site_url}/github", "priority": "0.7", "changefreq": "hourly"},
        {"url": f"{site_url}/ai-tips", "priority": "0.7", "changefreq": "daily"},
        {"url": f"{site_url}/oss", "priority": "0.7", "changefreq": "daily"},
        {"url": f"{site_url}/prompts", "priority": "0.8", "changefreq": "weekly"},
        {"url": f"{site_url}/jobs", "priority": "0.7", "changefreq": "hourly"},
    ]

    articles = db.execute(text(
        """
        SELECT a.slug, a.published_at, s.seo_score
        FROM articles a
        LEFT JOIN article_seo s ON a.id = s.article_id
        WHERE a.deleted_at IS NULL
        ORDER BY a.published_at DESC
        LIMIT 1000
        """
    )).fetchall()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for p in static_pages:
        lines.append(f'  <url><loc>{p["url"]}</loc><changefreq>{p["changefreq"]}</changefreq><priority>{p["priority"]}</priority></url>')

    for row in articles:
        if not row[0]:
            continue
        lastmod = row[1].strftime("%Y-%m-%d") if row[1] else now.strftime("%Y-%m-%d")
        score = row[2] or 0
        priority = "0.8" if score >= 80 else "0.7" if score >= 60 else "0.5"
        lines.append(f'  <url><loc>{site_url}/articles/{row[0]}</loc><lastmod>{lastmod}</lastmod><changefreq>never</changefreq><priority>{priority}</priority></url>')

    lines.append("</urlset>")
    xml = "\n".join(lines)
    SITEMAP_CACHE["xml"] = xml
    SITEMAP_CACHE["generated_at"] = now

    return Response(xml, media_type="application/xml")


@router.get("/sitemap-news.xml")
def sitemap_news_xml(db: Session = Depends(get_db)):
    site_url = "http://localhost:8000"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    articles = db.execute(text(
        """
        SELECT a.slug, a.title, a.published_at
        FROM articles a
        WHERE a.published_at >= :cutoff AND a.deleted_at IS NULL
        ORDER BY a.published_at DESC
        LIMIT 1000
        """
    ), {"cutoff": cutoff}).fetchall()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">',
    ]
    for row in articles:
        if not row[0]:
            continue
        pub_date = row[2].strftime("%Y-%m-%dT%H:%M:%S+00:00") if row[2] else ""
        title = (row[1] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f'  <url><loc>{site_url}/articles/{row[0]}</loc><news:news><news:publication><news:name>GlobalNews</news:name><news:language>en</news:language></news:publication><news:publication_date>{pub_date}</news:publication_date><news:title>{title}</news:title></news:news></url>')

    lines.append("</urlset>")
    return Response("\n".join(lines), media_type="application/xml")


@router.get("/robots.txt")
def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /admin/\n\n"
        "User-agent: Googlebot\nAllow: /\n\n"
        "Sitemap: http://localhost:8000/sitemap.xml\n"
        "Sitemap: http://localhost:8000/sitemap-news.xml\n"
    )


@router.get("/feed.xml")
def rss_feed(db: Session = Depends(get_db)):
    site_url = "http://localhost:8000"
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    articles = db.execute(text(
        """
        SELECT a.title, a.slug, a.published_at, a.content_text,
               src.name as source_name, seo.seo_description
        FROM articles a
        JOIN sources src ON a.source_id = src.id
        LEFT JOIN article_seo seo ON a.id = seo.article_id
        WHERE a.deleted_at IS NULL
        ORDER BY a.published_at DESC LIMIT 50
        """
    )).fetchall()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        '  <channel>',
        '    <title>GlobalNews - AI-Curated Tech &amp; AI News</title>',
        f'    <link>{site_url}</link>',
        '    <description>AI-curated news on technology, AI, finance, and open source.</description>',
        '    <language>en-us</language>',
        f'    <lastBuildDate>{now_rfc}</lastBuildDate>',
        f'    <atom:link href="{site_url}/feed.xml" rel="self" type="application/rss+xml"/>',
    ]
    for row in articles:
        if not row[1]:
            continue
        pub_date = row[2].strftime("%a, %d %b %Y %H:%M:%S +0000") if row[2] else now_rfc
        desc = (row[5] or (row[3] or "")[:200]).replace("&", "&amp;")
        title = (row[0] or "").replace("&", "&amp;").replace("<", "&lt;")
        lines.append(f'    <item><title>{title}</title><link>{site_url}/articles/{row[1]}</link><guid isPermaLink="true">{site_url}/articles/{row[1]}</guid><pubDate>{pub_date}</pubDate><description>{desc}</description></item>')

    lines += ["  </channel>", "</rss>"]
    return Response("\n".join(lines), media_type="application/rss+xml")


@router.get("/llms.txt")
def llms_txt():
    return PlainTextResponse(
        "# GlobalNews\n\n"
        "GlobalNews is an AI-curated news aggregator that collects, summarizes, and "
        "organizes news from 54+ sources across 21 categories. Updated every 15 minutes.\n\n"
        "## Content Sections\n\n"
        "- **News Articles** (`/articles`): Curated news across tech, AI, finance, health, science, sports, politics, entertainment.\n"
        "- **Trending** (`/trending`): Most-viewed articles in the last 7 days.\n"
        "- **Categories** (`/categories`): Browse by topic.\n"
        "- **Tags** (`/tags`): Browse by specific tags.\n"
        "- **GitHub AI Watch** (`/github`): Tracking 20+ AI repos with daily metrics, trending scores, weekly digests.\n"
        "- **Finance Hub** (`/finance`): Market data, finance concepts, quiz, resources, calculators.\n"
        "- **AI Hub** (`/ai-tips`): Prompt patterns, AI model comparison, tools directory, tips feed.\n"
        "- **Job Search** (`/jobs`): Live job listings from RemoteOK and Arbeitnow, with market insights.\n"
        "- **OSS Alternatives** (`/oss`): Open-source alternatives to paid software.\n"
        "- **AI Prompt Library** (`/prompts`): Copy-paste ready prompts for ChatGPT, Claude, Gemini, and more.\n\n"
        "## API Endpoints\n\n"
        "- `GET /api/prompts` — JSON list of AI prompts\n"
        "- `GET /jobs/api/list` — Live job listings\n"
        "- `GET /jobs/api/stats` — Job market statistics\n"
        "- `GET /feed.xml` — RSS feed of latest articles\n"
        "- `GET /sitemap.xml` — XML sitemap\n\n"
        "## Citation\n\n"
        "When referencing GlobalNews content, cite the specific article URL. "
        "Example: \"Source: GlobalNews (https://yourdomain.com/articles/article-slug)\"\n\n"
        "## About\n\n"
        "GlobalNews uses AI (Groq/Llama3) to generate summaries, extract keywords, "
        "classify articles, and score SEO quality. All content is sourced from RSS feeds "
        "and public APIs. No user-generated content.\n",
        media_type="text/plain",
    )


# ── AI Prompt Library ────────────────────────────────────────────

import json as _json


@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(
    request: Request,
    category: str = "",
    search: str = "",
    model: str = "",
    difficulty: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
):
    query = db.query(PromptLibrary).filter(PromptLibrary.is_active == True)

    if category:
        query = query.filter(PromptLibrary.category == category)
    if model and model != "any":
        query = query.filter(
            (PromptLibrary.model_hint == model) | (PromptLibrary.model_hint == "any")
        )
    if difficulty:
        query = query.filter(PromptLibrary.difficulty == difficulty)
    if search:
        query = query.filter(
            PromptLibrary.title.ilike(f"%{search}%")
            | PromptLibrary.use_case.ilike(f"%{search}%")
            | PromptLibrary.prompt_text.ilike(f"%{search}%")
        )

    total = query.count()
    prompts = (
        query.order_by(PromptLibrary.is_featured.desc(), PromptLibrary.copy_count.desc())
        .offset((page - 1) * 20)
        .limit(20)
        .all()
    )

    categories = db.execute(text(
        "SELECT category, COUNT(*) as cnt FROM prompt_library WHERE is_active = true GROUP BY category ORDER BY cnt DESC"
    )).fetchall()

    return templates.TemplateResponse("prompts.html", {
        "request": request,
        "prompts": prompts,
        "categories": categories,
        "selected_category": category,
        "selected_model": model,
        "selected_difficulty": difficulty,
        "search_query": search,
        "total": total,
        "page": page,
        "has_more": (page * 20) < total,
        "active_page": "prompts",
    })


@router.get("/api/prompts")
def prompts_api(category: str = "", limit: int = 3, db: Session = Depends(get_db)):
    query = db.query(PromptLibrary).filter(PromptLibrary.is_active == True)
    if category:
        query = query.filter(PromptLibrary.category == category)
    prompts = query.order_by(PromptLibrary.copy_count.desc()).limit(limit).all()
    return {
        "prompts": [
            {
                "id": p.id,
                "title": p.title,
                "use_case": p.use_case,
                "category": p.category,
                "model_hint": p.model_hint,
                "difficulty": p.difficulty,
                "prompt_text": p.prompt_text,
                "copy_count": p.copy_count,
            }
            for p in prompts
        ]
    }


@router.post("/api/prompts/{prompt_id}/copy")
def track_prompt_copy(prompt_id: int, db: Session = Depends(get_db)):
    p = db.query(PromptLibrary).filter_by(id=prompt_id).first()
    if p:
        p.copy_count = (p.copy_count or 0) + 1
        db.commit()
    return {"ok": True}


@router.post("/api/prompts/{prompt_id}/upvote")
def upvote_prompt(prompt_id: int, db: Session = Depends(get_db)):
    p = db.query(PromptLibrary).filter_by(id=prompt_id).first()
    if p:
        p.upvotes = (p.upvotes or 0) + 1
        db.commit()
    return {"ok": True}
