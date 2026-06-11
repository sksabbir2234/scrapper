"""
AI Blog Scraper — Collects AI-focused articles from public RSS feeds,
filters by topic relevance, and stores in the Article table.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from slugify import slugify

from config.settings import get_settings
from app.scrapers import strip_html

logger = logging.getLogger(__name__)
settings = get_settings()

# ── RSS Sources ──────────────────────────────────────────────────

AI_BLOG_SOURCES = [
    {"name": "Towards AI", "url": "https://medium.com/feed/towards-artificial-intelligence", "category": "ai_tutorial", "credibility": 0.82},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "category": "ai_tutorial", "credibility": 0.85},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "ai_research", "credibility": 0.92},
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "category": "ai_news", "credibility": 0.95},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/rss.xml", "category": "ai_news", "credibility": 0.95},
    {"name": "Google AI Blog", "url": "https://blog.research.google/feeds/posts/default", "category": "ai_research", "credibility": 0.93},
    {"name": "The Rundown AI", "url": "https://www.therundown.ai/rss", "category": "ai_news", "credibility": 0.78},
    {"name": "Ben's Bites", "url": "https://www.bensbites.com/feed", "category": "ai_news", "credibility": 0.80},
    {"name": "FutureTools", "url": "https://www.futuretools.io/rss/news", "category": "ai_money", "credibility": 0.75},
    {"name": "The AI Advantage", "url": "https://theaiadvantage.substack.com/feed", "category": "ai_money", "credibility": 0.73},
    {"name": "Every.to", "url": "https://every.to/feed", "category": "ai_business", "credibility": 0.80},
    {"name": "PromptingGuide", "url": "https://www.promptingguide.ai/rss.xml", "category": "prompt_engineering", "credibility": 0.83},
    {"name": "Lil'Log", "url": "https://lilianweng.github.io/index.xml", "category": "ai_research", "credibility": 0.94},
    {"name": "Zapier Blog", "url": "https://zapier.com/blog/feeds/latest/", "category": "ai_automation", "credibility": 0.79},
    {"name": "AI Tool Report", "url": "https://aitoolreport.beehiiv.com/feed", "category": "ai_tools", "credibility": 0.73},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/ai/feed/", "category": "ai_news", "credibility": 0.85},
    {"name": "MIT Tech Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "ai_research", "credibility": 0.91},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss", "category": "ai_news", "credibility": 0.88},
]

# ── Relevance Keywords ──────────────────────────────────────────

_INCLUDE_KEYWORDS = [
    r"\bhow\s+to\s+use\s+ai\b", r"\bai\s+tutorial\b", r"\bai\s+guide\b",
    r"\bai\s+tools?\b", r"\bbest\s+ai\s+tools?\b", r"\bmake\s+money\b",
    r"\bai\s+income\b", r"\bai\s+side\s+hustle\b", r"\bai\s+business\b",
    r"\bfreelance\s+ai\b", r"\bai\s+productivity\b", r"\bai\s+automation\b",
    r"\bautomate\s+with\s+ai\b", r"\bai\s+workflow\b", r"\bprompt\s+engineering\b",
    r"\bsystem\s+prompt\b", r"\bai\s+prompts?\b", r"\bchain\s+of\s+thought\b",
    r"\bchatgpt\s+tutorial\b", r"\bclaude\s+tutorial\b", r"\bgemini\s+tutorial\b",
    r"\bllm\b", r"\bgpt-4\b", r"\blarge\s+language\s+model\b",
    r"\bartificial\s+intelligence\b", r"\bmachine\s+learning\b",
    r"\bdeep\s+learning\b", r"\bneural\s+network\b", r"\btransformer\b",
    r"\bfinetun", r"\braG\b", r"\bretrieval.augmented\b",
    r"\bai\s+agent\b", r"\bautonomous\s+agent\b", r"\bmulti.agent\b",
]

_EXCLUDE_KEYWORDS = [
    r"\bstock\s+market\b", r"\bcryptocurrency\b", r"\bbitcoin\b",
    r"\bnft\b", r"\bsports\b", r"\bcelebrity\b", r"\bentertainment\b",
    r"\bgambling\b", r"\bpoker\b", r"\bdating\b",
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_relevant(title: str, summary: str) -> bool:
    """Return True if the article matches AI inclusion keywords and no exclusion keywords."""
    text = f"{title} {summary}".lower()

    if any(re.search(p, text, re.IGNORECASE) for p in _EXCLUDE_KEYWORDS):
        return False
    if any(re.search(p, text, re.IGNORECASE) for p in _INCLUDE_KEYWORDS):
        return True
    return False


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def _extract_image(entry) -> Optional[str]:
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


def _fetch_feed(url: str) -> Optional[list]:
    """Fetch and parse an RSS feed. Returns list of entries or None on error."""
    headers = {"User-Agent": settings.scraper_user_agent}
    try:
        resp = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return None

    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        logger.error("Failed to parse feed %s: %s", url, feed.bozo_exception)
        return None

    return feed.entries


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


def _scrape_single_feed(feed_cfg: dict) -> list[dict]:
    """Scrape one feed and return raw article dicts (before DB)."""
    entries = _fetch_feed(feed_cfg["url"])
    if entries is None:
        return []

    items = []
    for entry in entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        description_parts = []
        if hasattr(entry, "summary"):
            description_parts.append(entry.summary)
        if hasattr(entry, "description"):
            description_parts.append(entry.description)
        if hasattr(entry, "content") and entry.content:
            description_parts.append(entry.content[0].get("value", ""))
        summary = strip_html(" ".join(filter(None, description_parts)).strip())

        if not _is_relevant(title, summary):
            continue

        url_hash = _hash(link)
        base_slug = slugify(title)[:230]
        short_hash = url_hash[:8]
        slug = f"{base_slug}-{short_hash}"

        items.append({
            "title": title[:500],
            "slug": slug,
            "original_url": link[:1000],
            "url_hash": url_hash,
            "content_text": summary[:10000],
            "author": (entry.get("author") or "")[:150],
            "published_at": _parse_date(entry),
            "language": "en",
            "category": feed_cfg.get("category", "ai_news"),
            "image_url": _extract_image(entry),
            "source_name": feed_cfg["name"],
            "credibility": feed_cfg.get("credibility", 0.75),
        })

    logger.info("AI blog [%s]: %d relevant items from %d entries",
                feed_cfg["name"], len(items), len(entries))
    return items


def scrape_ai_blogs(db, max_per_source: int = 10, dry_run: bool = False) -> dict:
    """
    Scrape all configured AI blog RSS feeds, filter by relevance, and store
    new articles in the Article table.

    Args:
        db: SQLAlchemy Session
        max_per_source: Max articles to keep per source feed
        dry_run: If True, return results without writing to DB

    Returns:
        Summary dict with counts and optionally article list for dry_run
    """
    from app.models import Article

    result = {
        "total_fetched": 0,
        "total_saved": 0,
        "skipped_duplicate": 0,
        "skipped_irrelevant": 0,
        "errors": [],
        "sources_processed": 0,
        "articles": [],
    }

    if not dry_run:
        source_id = _get_or_create_source(db)

    seen_hashes = set()

    for feed_cfg in AI_BLOG_SOURCES:
        try:
            items = _scrape_single_feed(feed_cfg)
            result["total_fetched"] += len(items)
            result["sources_processed"] += 1

            for item in items[:max_per_source]:
                url_hash = item["url_hash"]

                if url_hash in seen_hashes:
                    result["skipped_duplicate"] += 1
                    continue
                seen_hashes.add(url_hash)

                if dry_run:
                    result["articles"].append(item)
                    result["total_saved"] += 1
                    continue

                existing = db.query(Article).filter(
                    (Article.url_hash == url_hash) |
                    (Article.original_url == item["original_url"])
                ).first()
                if existing:
                    result["skipped_duplicate"] += 1
                    continue

                try:
                    with db.begin_nested():
                        article = Article(
                            source_id=source_id,
                            title=item["title"],
                            slug=item["slug"],
                            original_url=item["original_url"],
                            url_hash=item["url_hash"],
                            content_text=item["content_text"],
                            author=item["author"],
                            published_at=item["published_at"],
                            language=item["language"],
                            category=item["category"],
                            image_url=item.get("image_url"),
                        )
                        db.add(article)
                        db.flush()
                    result["total_saved"] += 1
                except Exception as e:
                    result["errors"].append(f"{item['title'][:60]}: {e}")
                    logger.error("Failed to insert article '%s': %s", item["title"][:60], e)

        except Exception as e:
            result["errors"].append(f"{feed_cfg['name']}: {e}")
            logger.error("Error scraping %s: %s", feed_cfg["name"], e)

    if not dry_run:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            result["errors"].append(f"Commit failed: {e}")
            logger.error("Failed to commit AI blog articles: %s", e)

    logger.info(
        "AI blog scrape complete: fetched=%d, saved=%d, duplicates=%d, errors=%d",
        result["total_fetched"], result["total_saved"],
        result["skipped_duplicate"], len(result["errors"]),
    )
    return result


def run_ai_blog_scrape(db=None):
    """Entry point for scheduler. Creates its own DB session if none provided."""
    from app.db.database import SessionLocal

    own_db = db is None
    if own_db:
        db = SessionLocal()

    start = __import__("time").time()
    try:
        result = scrape_ai_blogs(db, max_per_source=10)
        duration = int(__import__("time").time() - start)
        logger.info(
            "AI blog scrape: %d saved, %d duplicates, %d errors, %ds",
            result["total_saved"], result["skipped_duplicate"],
            len(result["errors"]), duration,
        )
    except Exception as e:
        logger.error("AI blog scrape failed: %s", e)
        if not own_db:
            db.rollback()
    finally:
        if own_db:
            db.close()
