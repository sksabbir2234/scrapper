"""
Finance education scraper — pulls free financial education content from RSS feeds
and tags each item with difficulty (beginner/intermediate) and cost_level (zero_cost/low_cost/any).
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

# --- Free financial education RSS feeds ---
FINANCE_FEEDS = [
    {
        "url": "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline",
        "source": "investopedia",
        "topic": "investing",
        "default_level": "beginner",
    },
    {
        "url": "https://www.nerdwallet.com/blog/feed/",
        "source": "nerdwallet",
        "topic": "personal_finance",
        "default_level": "beginner",
    },
    {
        "url": "https://www.thebalancemoney.com/rss",
        "source": "thebalance",
        "topic": "personal_finance",
        "default_level": "beginner",
    },
    {
        "url": "https://feeds.feedburner.com/FatPitchFinancials",
        "source": "fatpitch",
        "topic": "investing",
        "default_level": "intermediate",
    },
    {
        "url": "https://www.morningstar.com/rss",
        "source": "morningstar",
        "topic": "investing",
        "default_level": "intermediate",
    },
    {
        "url": "https://www.investing.com/rss/news.rss",
        "source": "investing_com",
        "topic": "market_news",
        "default_level": "intermediate",
    },
]

# --- Difficulty detection keywords ---
_BEGINNER_KEYWORDS = [
    r"\bbasics?\b", r"\bbeginner", r"\b101\b", r"\bintroduction\b",
    r"\bgetting\s+started\b", r"\bhow\s+to\b", r"\bwhat\s+is\b",
    r"\bsaving\b", r"\bbudgeting\b", r"\bemergency\s+fund\b",
    r"\bcredit\s+score\b", r"\bfirst\s+time\b", r"\bguide\b",
    r"\bexplained\b", r"\bfor\s+newbies?\b", r"\bstarter\b",
    r"\bpaying\s+off\s+debt\b", r"\bsimple\b", r"\beasy\b",
]

_INTERMEDIATE_KEYWORDS = [
    r"\binvesting\b", r"\bportfolio\b", r"\btax\s+strategy\b",
    r"\bretirement\s+plan", r"\basset\s+allocation\b", r"\bdiversif",
    r"\broth\s+ira\b", r"\b401k?\b", r"\bstock\s+market\b",
    r"\bdividend", r"\bbond", r"\bindex\s+fund", r"\betf\b",
    r"\bcapital\s+gain", r"\bfinancial\s+planning\b",
    r"\brisk\s+management\b", r"\bhedge\b", r"\bleverage\b",
    r"\bfundamental\s+analysis\b", r"\btechnical\s+analysis\b",
    r"\bmargin\b", r"\boption", r"\bfuture",
]

# --- Cost-level detection ---
_ZERO_COST_KEYWORDS = [
    r"\bfree\b", r"\bno\s+cost\b", r"\bopen[\s-]source\b",
    r"\bpublic\s+domain\b", r"\$0\b", r"\bwithout\s+cost\b",
    r"\bcomplimentary\b", r"\bgratis\b",
]

_LOW_COST_KEYWORDS = [
    r"\baffordable\b", r"\bbudget[\s-]friendly\b", r"\bcheap\b",
    r"\bunder\s+\$?\d+\b", r"\blow[\s-]cost\b", r"\binexpensive\b",
    r"\bdiscount", r"\bsale\b", r"\bdeal\b",
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _detect_difficulty(title: str, description: str, default: str = "beginner") -> str:
    """Classify difficulty based on title + description keywords."""
    text = f"{title} {description}".lower()

    beginner_hits = sum(1 for p in _BEGINNER_KEYWORDS if re.search(p, text, re.IGNORECASE))
    intermediate_hits = sum(1 for p in _INTERMEDIATE_KEYWORDS if re.search(p, text, re.IGNORECASE))

    if intermediate_hits > beginner_hits:
        return "intermediate"
    if beginner_hits > 0:
        return "beginner"
    return default


def _detect_cost_level(title: str, description: str) -> str:
    """Classify cost level based on title + description keywords."""
    text = f"{title} {description}".lower()

    if any(re.search(p, text, re.IGNORECASE) for p in _ZERO_COST_KEYWORDS):
        return "zero_cost"
    if any(re.search(p, text, re.IGNORECASE) for p in _LOW_COST_KEYWORDS):
        return "low_cost"
    return "any"


def _detect_resource_type(title: str, description: str) -> str:
    """Guess resource type from content."""
    text = f"{title} {description}".lower()
    if re.search(r"\bcourse\b", text):
        return "course"
    if re.search(r"\bvideo\b|\byoutube\b|\btutorial\b", text):
        return "video"
    if re.search(r"\bbook\b", text):
        return "book"
    if re.search(r"\btool\b|\bcalculator\b|\bapp\b", text):
        return "tool"
    return "article"


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def scrape_finance_feed(feed_cfg: dict) -> list[dict]:
    """Scrape a single finance RSS feed and return tagged items."""
    url = feed_cfg["url"]
    headers = {"User-Agent": settings.scraper_user_agent}

    try:
        resp = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Finance feed fetch failed [{feed_cfg['source']}]: {e}")
        return []

    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        logger.error(f"Finance feed parse failed [{feed_cfg['source']}]: {feed.bozo_exception}")
        return []

    items = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        # Combine all text for analysis
        description_parts = []
        if hasattr(entry, "summary"):
            description_parts.append(entry.summary)
        if hasattr(entry, "description"):
            description_parts.append(entry.description)
        if hasattr(entry, "content") and entry.content:
            description_parts.append(entry.content[0].get("value", ""))
        description = strip_html(" ".join(filter(None, description_parts)).strip())

        difficulty = _detect_difficulty(title, description, feed_cfg.get("default_level", "beginner"))
        cost_level = _detect_cost_level(title, description)
        resource_type = _detect_resource_type(title, description)

        items.append({
            "title": title[:200],
            "url": link,
            "resource_type": resource_type,
            "level": difficulty,
            "cost_level": cost_level,
            "topic": feed_cfg.get("topic", "personal_finance"),
            "description": description[:500] if description else None,
            "url_hash": _hash(link),
            "published_at": _parse_date(entry),
            "source": feed_cfg["source"],
        })

    logger.info(f"Finance [{feed_cfg['source']}]: scraped {len(items)} items")
    return items


def scrape_all_finance_feeds() -> list[dict]:
    """Scrape all configured finance RSS feeds."""
    all_items = []
    seen_hashes = set()

    for feed_cfg in FINANCE_FEEDS:
        items = scrape_finance_feed(feed_cfg)
        for item in items:
            if item["url_hash"] not in seen_hashes:
                seen_hashes.add(item["url_hash"])
                all_items.append(item)

    logger.info(f"Finance scraper total: {len(all_items)} unique items from {len(FINANCE_FEEDS)} feeds")
    return all_items
