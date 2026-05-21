import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.db.database import get_db
from app.models import (
    Article, Source, ScrapeLog, Category, Tag, ArticleTag,
    GithubUpdate, FinanceResource, FinanceQuizQuestion,
    PromptPattern, AIModelCard, AITool, AITip, OSSAlternative,
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
        "request": request, "articles": articles, "categories": categories
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
    })


@router.get("/articles/{slug}", response_class=HTMLResponse)
async def article_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.slug == slug).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    article.view_count += 1
    db.commit()

    article_tags = (
        db.query(Tag)
        .join(ArticleTag, Tag.id == ArticleTag.tag_id)
        .filter(ArticleTag.article_id == article.id)
        .all()
    )

    return templates.TemplateResponse("article.html", {
        "request": request, "article": article, "article_tags": article_tags
    })


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request, db: Session = Depends(get_db)):
    categories = db.query(Category).filter(Category.is_active == True).all()
    category_counts = []
    for cat in categories:
        count = db.query(Article).filter(Article.category == cat.slug, Article.deleted_at.is_(None)).count()
        category_counts.append({"category": cat, "count": count})
    return templates.TemplateResponse("categories.html", {
        "request": request, "category_counts": category_counts
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
    })


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query(default=""), page: int = 1, db: Session = Depends(get_db)):
    per_page = 20
    offset = (page - 1) * per_page

    if not q.strip():
        return templates.TemplateResponse("search.html", {
            "request": request, "articles": [], "query": "", "total": 0, "page": 1, "total_pages": 0
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

    return templates.TemplateResponse("trending.html", {"request": request, "articles": articles})


@router.get("/tags", response_class=HTMLResponse)
async def tag_list(request: Request, db: Session = Depends(get_db)):
    tag_counts = (
        db.query(Tag, func.count(ArticleTag.article_id).label("count"))
        .join(ArticleTag, Tag.id == ArticleTag.tag_id)
        .group_by(Tag.id)
        .order_by(desc("count"))
        .all()
    )
    return templates.TemplateResponse("tags.html", {"request": request, "tags": tag_counts})


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
async def github_page(request: Request, update_type: str = "", repo: str = "", db: Session = Depends(get_db)):
    query = db.query(GithubUpdate).order_by(desc(GithubUpdate.published_at))
    if update_type:
        query = query.filter(GithubUpdate.update_type == update_type)
    if repo:
        query = query.filter(GithubUpdate.repo_name == repo)
    updates = query.limit(100).all()
    repos = db.query(GithubUpdate.repo_name).distinct().all()
    return templates.TemplateResponse("github_updates.html", {
        "request": request, "updates": updates,
        "repos": [r[0] for r in repos],
        "current_type": update_type, "current_repo": repo,
    })


@router.get("/github/api/updates")
async def github_api_updates(update_type: str = "", repo: str = "", db: Session = Depends(get_db)):
    query = db.query(GithubUpdate).order_by(desc(GithubUpdate.published_at))
    if update_type:
        query = query.filter(GithubUpdate.update_type == update_type)
    if repo:
        query = query.filter(GithubUpdate.repo_name == repo)
    updates = query.limit(100).all()
    return [{
        "id": u.id, "repo_name": u.repo_name, "update_type": u.update_type,
        "title": u.title, "body": (u.body or "")[:500], "external_url": u.external_url,
        "published_at": str(u.published_at) if u.published_at else None,
        "stars": u.stars, "language": u.language,
    } for u in updates]


# ── Finance Learning Hub ─────────────────────────────────────────

@router.get("/finance", response_class=HTMLResponse)
async def finance_page(request: Request):
    return templates.TemplateResponse("finance.html", {"request": request})


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
    return templates.TemplateResponse("ai_tips.html", {"request": request})


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
