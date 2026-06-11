"""
AI Blog Scraper — Collects AI-focused articles from public RSS feeds,
filters by topic relevance, and stores in the Article table.

Topics: "how to use AI", "make money with AI", "AI tools", "AI tutorials",
        "prompt engineering", "AI productivity", "AI side hustle", "AI automation"
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from slugify import slugify
from sqlalchemy.orm import Session

from config.settings import get_settings
from app.scrapers import strip_html

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# AI Blog Sources — RSS-first, all free/public
# ---------------------------------------------------------------------------
AI_BLOG_SOURCES = [
    # ── How to Use AI / Tutorials ────────────────────────────────────────
    {"name": "Towards AI", "url": "https://medium.com/feed/towards-artificial-intelligence", "category": "ai_tutorial", "credibility": 0.82},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "category": "ai_tutorial", "credibility": 0.85},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "ai_research", "credibility": 0.92},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "category": "ai_news", "credibility": 0.95},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/rss.xml", "category": "ai_news", "credibility": 0.95},
    {"name": "Google AI Blog", "url": "https://blog.research.google/feeds/posts/default", "category": "ai_research", "credibility": 0.93},
    {"name": "The Rundown AI", "url": "https://www.therundown.ai/rss", "category": "ai_news", "credibility": 0.78},
    {"name": "Ben's Bites", "url": "https://www.bensbites.com/feed", "category": "ai_news", "credibility": 0.80},
    # ── Make Money With AI / Business ───────────────────────────────────
    {"name": "Matt Wolfe (FutureTools)", "url": "https://www.futuretools.io/rss/news", "category": "ai_money", "credibility": 0.75},
    {"name": "The AI Advantage", "url": "https://theaiadvantage.substack.com/feed", "category": "ai_money", "credibility": 0.73},
    {"name": "AI Solopreneur", "url": "https://www.aisolopreneur.com/rss", "category": "ai_money", "credibility": 0.72},
    {"name": "Every.to (AI Writing & Business)", "url": "https://every.to/feed", "category": "ai_business", "credibility": 0.80},
    # ── Prompt Engineering ───────────────────────────────────────────────
    {"name": "PromptEngineering.guide", "url": "https://www.promptingguide.ai/rss.xml", "category": "prompt_engineering", "credibility": 0.83},
    {"name": "Lil'Log (Lilian Weng / OpenAI)", "url": "https://lilianweng.github.io/index.xml", "category": "ai_research", "credibility": 0.94},
    # ── AI Productivity / Automation ─────────────────────────────────────
    {"name": "Zapier Blog (AI Automation)", "url": "https://zapier.com/blog/feeds/latest/", "category": "ai_automation", "credibility": 0.79},
    {"name": "Make.com Blog", "url": "https://www.make.com/en/blog/feed", "category": "ai_automation", "credibility": 0.77},
    {"name": "AI Tool Report", "url": "https://aitoolreport.beehiiv.com/feed", "category": "ai_tools", "credibility": 0.73},
    # ── General AI Tech News ─────────────────────────────────────────────
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/ai/feed/", "category": "ai_news", "credibility": 0.85},
    {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "ai_research", "credibility": 0.91},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss", "category": "ai_news", "credibility": 0.88},
]

# ---------------------------------------------------------------------------
# Topic filter — keep only AI-relevant articles
# ---------------------------------------------------------------------------
RELEVANCE_KEYWORDS = [
    # How to use AI
    "how to use ai", "ai tutorial", "ai guide", "getting started with ai",
    "beginners guide", "ai for beginners", "learn ai", "ai tips",
    "chatgpt tutorial", "claude tutorial", "gemini tutorial",
    # Tools
    "ai tools", "best ai tools", "ai software", "ai apps", "top ai",
    "new ai tool", "free ai tool", "ai generator",
    # Make money
    "make money", "earn money", "ai income", "ai business", "ai side hustle",
    "passive income ai", "freelance ai", "sell ai", "ai revenue",
    "monetize ai", "ai entrepreneur", "ai solopreneur",
    # Productivity / Automation
    "ai productivity", "ai workflow", "ai automation", "automate with ai",
    "save time ai", "ai assistant", "ai agent",
    # Prompt engineering
    "prompt engineering", "prompt design", "system prompt", "ai prompts",
    "chain of thought", "few-shot", "zero-shot",
    # General relevance (broad)
    "artificial intelligence", "machine learning", "large language model",
    "llm", "gpt-4", "claude", "gemini", "mistral", "llama",
]

EXCLUDE_KEYWORDS = [
    "stock market", "cryptocurrency", "bitcoin", "ethereum", "nft",
    "sports", "football", "cricket", "entertainment", "celebrity",
]


def _is_relevant(title: str, summary: str) -> bool:
    """Check if an article is relevant to AI topics."""
    text = (title + " " + summary).lower()
    if any(kw in text for kw in EXCLUDE_KEYWORDS):
        return False
    return any(kw in text for kw in RELEVANCE_KEYWORDS)


def _compute_url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _parse_date(entry) -> Optional[datetime]:
    """Parse published date from feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _extract_image(entry) -> Optional[str]:
    """Extract image URL from feed entry."""
    if hasattr(entry, "media_content") and entry.media_content:
        return entry.media_content[0].get("url")
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href")
    if hasattr(entry, "links"):
        for link in entry.links:
            if hasattr(link, "type") and link.type and link.type.startswith("image"):
                return link.get("href")
    return None


def _get_or_create_source(db) -> int:
    """Find or create the 'AI Blog Aggregator' source. Returns source_id."""
    from app.models import Source

    source_name = "AI Blog Aggregator"
    source = db.query(Source).filter(Source.name == source_name).first()
    if source:
        return source.id

    source = Source(
        name=source_name,
        domain="ai-blogs-aggregator",
        rss_url="internal://ai-blog-scraper",
        category="ai_news",
        credibility_score=85,
        scrape_type="rss",
        is_active=True,
    )
    db.add(source)
    db.flush()
    logger.info("Created AI Blog Aggregator source (id=%d)", source.id)
    return source.id


# ---------------------------------------------------------------------------
# Main scraper function
# ---------------------------------------------------------------------------
def scrape_ai_blogs(
    db: Session,
    max_per_source: int = 10,
    dry_run: bool = False,
) -> dict:
    """
    Scrape AI blog articles from all configured sources.

    Returns a summary dict:
      {
        "total_fetched": int,
        "total_saved": int,
        "skipped_duplicate": int,
        "skipped_irrelevant": int,
        "errors": list[str],
        "articles": list[dict]   # populated if dry_run=True
      }
    """
    from app.models import Article

    summary = {
        "total_fetched": 0,
        "total_saved": 0,
        "skipped_duplicate": 0,
        "skipped_irrelevant": 0,
        "errors": [],
        "articles": [],
    }

    if not dry_run:
        source_id = _get_or_create_source(db)

    seen_hashes = set()
    headers = {"User-Agent": settings.scraper_user_agent}

    for feed_cfg in AI_BLOG_SOURCES:
        try:
            resp = httpx.get(feed_cfg["url"], headers=headers, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                logger.error("Failed to parse feed %s: %s", feed_cfg["url"], feed.bozo_exception)
                continue

            entries = feed.entries[:max_per_source]
            logger.info("[ai_blog] %s → %d entries", feed_cfg["name"], len(entries))

            for entry in entries:
                summary["total_fetched"] += 1

                url = getattr(entry, "link", None) or ""
                title = (getattr(entry, "title", None) or "Untitled").strip()
                if not url or not title:
                    continue

                # Build summary from available content fields
                description_parts = []
                if hasattr(entry, "summary"):
                    description_parts.append(entry.summary)
                if hasattr(entry, "description"):
                    description_parts.append(entry.description)
                if hasattr(entry, "content") and entry.content:
                    description_parts.append(entry.content[0].get("value", ""))
                summary_text = strip_html(" ".join(filter(None, description_parts)).strip())

                # Relevance filter
                if not _is_relevant(title, summary_text):
                    summary["skipped_irrelevant"] += 1
                    continue

                url_hash = _compute_url_hash(url)
                published_at = _parse_date(entry)

                if dry_run:
                    summary["articles"].append({
                        "title": title,
                        "url": url,
                        "source": feed_cfg["name"],
                        "category": feed_cfg["category"],
                        "published_at": published_at.isoformat() if published_at else None,
                    })
                    summary["total_saved"] += 1
                    continue

                # In-batch dedup
                if url_hash in seen_hashes:
                    summary["skipped_duplicate"] += 1
                    continue
                seen_hashes.add(url_hash)

                # DB dedup
                existing = db.query(Article).filter(
                    (Article.url_hash == url_hash) |
                    (Article.original_url == url)
                ).first()
                if existing:
                    summary["skipped_duplicate"] += 1
                    continue

                # Build slug
                base_slug = slugify(title)[:230]
                slug = f"{base_slug}-{url_hash[:8]}"

                try:
                    with db.begin_nested():
                        article = Article(
                            source_id=source_id,
                            title=title[:500],
                            slug=slug,
                            original_url=url[:1000],
                            url_hash=url_hash,
                            content_text=summary_text[:10000],
                            author=(getattr(entry, "author", None) or "")[:150],
                            published_at=published_at or datetime.now(timezone.utc),
                            language="en",
                            category=feed_cfg.get("category", "ai_news"),
                            image_url=_extract_image(entry),
                        )
                        db.add(article)
                        db.flush()
                    summary["total_saved"] += 1
                except Exception as exc:
                    err = f"{title[:60]}: {exc}"
                    logger.error("Failed to insert article '%s': %s", title[:60], exc)
                    summary["errors"].append(err)

        except Exception as exc:
            err = f"[{feed_cfg['name']}] {exc}"
            logger.error(err)
            summary["errors"].append(err)

    if not dry_run:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            summary["errors"].append(f"Commit failed: {exc}")
            logger.error("Failed to commit AI blog articles: %s", exc)

    logger.info(
        "[ai_blog] Done. saved=%d skipped_dup=%d skipped_irrelevant=%d errors=%d",
        summary["total_saved"], summary["skipped_duplicate"],
        summary["skipped_irrelevant"], len(summary["errors"]),
    )
    return summary


# ---------------------------------------------------------------------------
# Scheduler hook
# ---------------------------------------------------------------------------
def run_ai_blog_scrape(db: Session = None) -> None:
    """APScheduler job entry point. Creates its own DB session if none provided."""
    from app.db.database import SessionLocal

    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        result = scrape_ai_blogs(db, max_per_source=15)
        logger.info("[scheduler] ai_blog_scrape: saved=%d errors=%d",
                    result["total_saved"], len(result["errors"]))
    except Exception as exc:
        logger.error("[scheduler] ai_blog_scrape failed: %s", exc)
        if not own_db:
            db.rollback()
    finally:
        if own_db:
            db.close()
