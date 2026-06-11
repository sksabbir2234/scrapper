import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
import time
import threading
from collections import deque

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Rate limiter: 30 requests per minute (Groq free tier)
_RATE_LIMIT = 30
_RATE_WINDOW = 60  # seconds
_request_times = deque()
_rate_lock = threading.Lock()


def _wait_for_rate_limit():
    """Block until a request slot is available."""
    with _rate_lock:
        now = time.time()
        # Remove timestamps older than the window
        while _request_times and _request_times[0] < now - _RATE_WINDOW:
            _request_times.popleft()

        if len(_request_times) >= _RATE_LIMIT:
            # Wait until the oldest request expires
            sleep_time = _request_times[0] + _RATE_WINDOW - now + 0.1
            if sleep_time > 0:
                logger.info(f"Rate limit hit, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
                # Clean up again after sleeping
                now = time.time()
                while _request_times and _request_times[0] < now - _RATE_WINDOW:
                    _request_times.popleft()

        _request_times.append(time.time())


def summarize_article(title: str, content: str) -> dict | None:
    """Generate SEO title, SEO description, and AI summary using Groq.

    Returns dict with keys: seo_title, seo_description, summary_ai
    Returns None if Groq is unavailable or rate limit exceeded.
    """
    if not settings.groq_api_key:
        logger.debug("No GROQ_API_KEY configured, skipping summarization")
        return None

    try:
        from groq import Groq

        _wait_for_rate_limit()

        client = Groq(api_key=settings.groq_api_key)

        # Truncate content to avoid token limits
        text = content[:3000] if content else ""

        prompt = f"""Analyze this news article and return a JSON object with exactly these 3 fields:
- "seo_title": SEO-optimized title (max 60 chars, compelling, keyword-rich)
- "seo_description": Meta description (max 155 chars, summarizes the article for search engines)
- "summary_ai": 2-3 sentence summary of the key points (max 300 chars)

Article title: {title}
Article content: {text}

Return ONLY valid JSON, no other text."""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )

        import json
        result = json.loads(response.choices[0].message.content)

        # Validate and truncate fields
        return {
            "seo_title": str(result.get("seo_title", ""))[:60],
            "seo_description": str(result.get("seo_description", ""))[:155],
            "summary_ai": str(result.get("summary_ai", ""))[:500],
        }

    except ImportError:
        logger.error("groq package not installed")
        return None
    except Exception as e:
        logger.error(f"Groq summarization failed: {e}")
        return None


def summarize_batch(articles: list[dict]) -> list[dict | None]:
    """Summarize a batch of articles. Returns list of results (None for failures)."""
    results = []
    for article in articles:
        result = summarize_article(
            article.get("title", ""),
            article.get("content_text", ""),
        )
        results.append(result)
    return results
