import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import httpx
from slugify import slugify

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def compute_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def parse_published_date(entry) -> Optional[datetime]:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


def extract_image_url(entry) -> Optional[str]:
    if hasattr(entry, "media_content") and entry.media_content:
        return entry.media_content[0].get("url")
    if hasattr(entry, "enclosures") and entry.enclosures:
        return entry.enclosures[0].get("href")
    if hasattr(entry, "links"):
        for link in entry.links:
            if hasattr(link, "type") and link.type and link.type.startswith("image"):
                return link.get("href")
    return None


def scrape_rss_feed(rss_url: str, source_id: int, source_name: str, category: str = None) -> list[dict]:
    headers = {"User-Agent": settings.scraper_user_agent}
    
    try:
        response = httpx.get(rss_url, headers=headers, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch {rss_url}: {e}")
        return []

    feed = feedparser.parse(response.content)
    
    if feed.bozo and not feed.entries:
        logger.error(f"Failed to parse feed from {rss_url}: {feed.bozo_exception}")
        return []

    articles = []
    for entry in feed.entries:
        url = entry.get("link", "").strip()
        if not url:
            continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        content_parts = []
        if hasattr(entry, "summary"):
            content_parts.append(entry.summary)
        if hasattr(entry, "description"):
            content_parts.append(entry.description)
        if hasattr(entry, "content") and entry.content:
            content_parts.append(entry.content[0].get("value", ""))
        
        content_text = " ".join(filter(None, content_parts)).strip()

        article = {
            "source_id": source_id,
            "title": title,
            "slug": slugify(title)[:250],
            "original_url": url,
            "url_hash": compute_url_hash(url),
            "content_text": content_text[:10000],
            "author": entry.get("author", ""),
            "published_at": parse_published_date(entry),
            "language": "en",
            "category": category,
            "image_url": extract_image_url(entry),
        }
        articles.append(article)

    logger.info(f"Scraped {len(articles)} articles from {source_name}")
    return articles
