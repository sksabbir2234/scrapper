import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from slugify import slugify

logger = logging.getLogger(__name__)


def compute_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def scrape_with_playwright(url: str, source_id: int, source_name: str, category: str = None) -> list[dict]:
    """Scrape a page using Playwright headless browser.

    Returns article dicts in the same format as scrape_rss_feed.
    Designed for JS-heavy sites that don't expose RSS or return empty feeds.
    """
    from playwright.sync_api import sync_playwright

    articles = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()

            # Block images/fonts/stylesheets for speed
            page.route("**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,css}", lambda route: route.abort())

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)  # Let JS render

            # Extract article-like elements
            # Common patterns: article tags, .article, .post, .story, h2/h3 with links
            selectors = [
                "article",
                ".article",
                ".post",
                ".story",
                ".news-item",
                "[data-type='article']",
            ]

            elements = []
            for sel in selectors:
                elements = page.query_selector_all(sel)
                if len(elements) >= 3:
                    break

            # Fallback: grab all h2/h3 links if no article containers found
            if len(elements) < 3:
                elements = page.query_selector_all("h2 a, h3 a")

            for el in elements[:50]:  # Cap at 50
                try:
                    # Try to get title
                    title_el = el.query_selector("h1, h2, h3, .title, .headline")
                    if title_el:
                        title = title_el.inner_text().strip()
                    else:
                        title = el.inner_text().strip()

                    if not title or len(title) < 10:
                        continue

                    # Try to get link
                    link_el = el.query_selector("a") if el.evaluate("el => el.tagName") != "A" else el
                    if not link_el:
                        link_el = el.query_selector("a")

                    href = link_el.get_attribute("href") if link_el else None
                    if not href:
                        continue

                    # Resolve relative URLs
                    if href.startswith("/"):
                        parsed = urlparse(url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"

                    # Get content snippet
                    content_el = el.query_selector("p, .summary, .excerpt, .description")
                    content = content_el.inner_text().strip() if content_el else ""

                    # Get image
                    img_el = el.query_selector("img")
                    img_url = None
                    if img_el:
                        img_url = img_el.get_attribute("src")
                        if img_url and img_url.startswith("/"):
                            parsed = urlparse(url)
                            img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"

                    article = {
                        "source_id": source_id,
                        "title": title[:500],
                        "slug": slugify(title)[:250],
                        "original_url": href,
                        "url_hash": compute_url_hash(href),
                        "content_text": content[:10000],
                        "author": "",
                        "published_at": datetime.now(timezone.utc),
                        "language": "en",
                        "category": category,
                        "image_url": img_url,
                    }
                    articles.append(article)
                except Exception as e:
                    logger.debug(f"Failed to extract element: {e}")
                    continue

            browser.close()

    except Exception as e:
        logger.error(f"Playwright scrape failed for {source_name} ({url}): {e}")
        return []

    logger.info(f"Playwright scraped {len(articles)} articles from {source_name}")
    return articles
