import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from slugify import slugify

logger = logging.getLogger(__name__)


def compute_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# Common non-article link text to skip
_NAV_TEXT_PATTERNS = re.compile(
    r"^(skip to|sign in|sign up|register|log in|login|logout|subscribe|"
    r"newsletter|menu|close|open|search|home|back|next|prev|more|"
    r"loading|advertisement|cookie|accept|decline|agree|"
    r"follow us|share|print|email to|related|trending|popular|"
    r"read more|view all|show more|see all|load more|"
    r"copyright|all rights|terms|privacy|contact us|about us|"
    r"advertisement|sponsored|promoted)",
    re.IGNORECASE,
)

# Paths that are definitely not articles
_SKIP_PATH_PATTERN = re.compile(
    r"^/(tag|tags|category|categories|author|authors|page|search|login|"
    r"signup|register|about|contact|terms|privacy|policy|faq|help|"
    r"support|sitemap|rss|feed|xml|json|api|admin|wp-admin|wp-content|"
    r"wp-includes|cdn-cgi|static|assets|media|images|css|js|fonts|"
    r"next|prev|older|newer|more|subscribe|newsletter|account|profile|"
    r"settings|dashboard|auth|oauth|callback|redirect)/?",
    re.IGNORECASE,
)


def _is_article_link(href: str, text: str, base_domain: str) -> bool:
    """Decide if a link looks like an article worth scraping."""
    if not text or len(text) < 15:
        return False

    # Skip common nav/UI text
    if _NAV_TEXT_PATTERNS.match(text):
        return False

    # Skip very short text that's likely a button or label
    if len(text.split()) < 3:
        return False

    parsed = urlparse(href)
    path = parsed.path.rstrip("/")

    # Skip empty or root paths
    if not path or path in ("/", ""):
        return False

    # Skip known non-article paths
    if _SKIP_PATH_PATTERN.match(path):
        return False

    # Must have at least 2 path segments
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return False

    # Last segment should look like an article slug (long, has hyphens or mixed case)
    last_segment = segments[-1]
    if len(last_segment) < 10:
        return False

    # Article slugs usually contain hyphens or numbers
    if "-" not in last_segment and not re.search(r"\d", last_segment):
        # Some sites use numeric IDs
        if not re.match(r"^\d+$", last_segment):
            return False

    # Skip if path ends with common non-article extensions
    if re.search(r"\.(xml|json|rss|atom|pdf|zip|gz|css|js)$", path, re.IGNORECASE):
        return False

    return True


def _extract_image(media: dict, base_url: str) -> str | None:
    """Get the first meaningful image from page media."""
    for img in media.get("images", []):
        src = img.get("src", "")
        if not src or not src.startswith(("http://", "https://", "/")):
            continue

        # Skip tiny images (icons, tracking pixels)
        w = img.get("width") or 0
        h = img.get("height") or 0
        if (w and w < 80) or (h and h < 80):
            continue

        # Skip obvious non-content images
        lower_src = src.lower()
        if any(x in lower_src for x in [
            "icon", "logo", "favicon", "pixel", "spacer", "1x1",
            "avatar", "badge", "button", "arrow", "sprite",
        ]):
            continue

        # Resolve relative URLs
        if src.startswith("/"):
            parsed = urlparse(base_url)
            src = f"{parsed.scheme}://{parsed.netloc}{src}"

        return src[:1000]

    return None


def _extract_snippet(title: str, markdown: str) -> str:
    """Try to find a content snippet near the article title in the markdown."""
    if not markdown:
        return ""

    # Look for the title in markdown and grab text after it
    escaped = re.escape(title[:50])
    match = re.search(escaped, markdown, re.IGNORECASE)
    if not match:
        return ""

    # Get text after the title (likely the article description/summary)
    start = match.end()
    end = min(len(markdown), start + 500)
    snippet = markdown[start:end]

    # Clean markdown syntax
    snippet = re.sub(r"[#\*\[\]!\(\)]", " ", snippet)
    snippet = re.sub(r"\s+", " ", snippet).strip()

    # Stop at the next link or heading
    cut = snippet.find("[")
    if cut > 20:
        snippet = snippet[:cut].strip()
    cut = snippet.find("\n")
    if cut > 20:
        snippet = snippet[:cut].strip()

    return snippet[:500]


async def _crawl_page(url: str) -> list[dict]:
    """Use Crawl4AI to fetch a page and extract article links."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        wait_until="domcontentloaded",
        page_timeout=30000,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not result.success:
        logger.error(f"Crawl4AI failed for {url}: {result.error_message}")
        return []

    base_domain = urlparse(url).netloc
    articles = []
    seen_urls = set()
    md = str(result.markdown) if result.markdown else ""

    for link in result.links.get("internal", []):
        href = (link.get("href") or "").strip()
        text = re.sub(r"\s+", " ", (link.get("text") or "")).strip()

        if not href or href in seen_urls:
            continue

        # Resolve relative URLs
        if href.startswith("/"):
            href = f"https://{base_domain}{href}"
        if not href.startswith("http"):
            continue

        if not _is_article_link(href, text, base_domain):
            continue

        seen_urls.add(href)

        articles.append({
            "title": text[:500],
            "original_url": href[:1000],
            "content_text": _extract_snippet(text, md),
            "image_url": _extract_image(result.media, url),
        })

    return articles


def scrape_with_playwright(url: str, source_id: int, source_name: str, category: str = None) -> list[dict]:
    """Scrape a page using Crawl4AI (managed Playwright with anti-bot, caching, retry).

    Returns article dicts in the same format as scrape_rss_feed.
    Designed for JS-heavy sites that don't expose RSS or return empty feeds.
    """
    try:
        raw_articles = asyncio.run(_crawl_page(url))
    except Exception as e:
        logger.error(f"Crawl4AI scrape failed for {source_name} ({url}): {e}")
        return []

    articles = []
    for raw in raw_articles:
        href = raw["original_url"]
        title = raw["title"]

        url_hash = compute_url_hash(href)
        base_slug = slugify(title)[:230]
        slug = f"{base_slug}-{url_hash[:8]}"

        article = {
            "source_id": source_id,
            "title": title,
            "slug": slug,
            "original_url": href,
            "url_hash": url_hash,
            "content_text": raw.get("content_text", "")[:10000],
            "author": "",
            "published_at": datetime.now(timezone.utc),
            "language": "en",
            "category": category,
            "image_url": raw.get("image_url"),
        }
        articles.append(article)

    logger.info(f"Crawl4AI scraped {len(articles)} articles from {source_name}")
    return articles
