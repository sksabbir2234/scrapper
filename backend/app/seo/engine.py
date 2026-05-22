"""
GlobalNews SEO Engine
Generates and scores SEO metadata for articles.

Scoring rubric (total 100 points):
  Title quality        : 25 pts  (length 50-70, contains primary keyword)
  Meta description     : 20 pts  (length 140-165, contains keyword)
  Keywords             : 15 pts  (3-8 keywords)
  Content length       : 15 pts  (>=300 words = 10pts, >=600 = 15pts)
  Structured data      : 10 pts  (JSON-LD present)
  Image + alt text     : 10 pts  (OG image set)
  URL structure        :  5 pts  (slug is clean)
"""

import re
from datetime import datetime

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
}

SCORE_WEIGHTS = {
    "title_length": 25,
    "meta_description": 20,
    "keywords": 15,
    "content_length": 15,
    "structured_data": 10,
    "og_image": 10,
    "url_slug": 5,
}

SEO_ISSUES = {
    "title_too_short": {"severity": "error", "msg": "SEO title under 50 chars"},
    "title_too_long": {"severity": "warning", "msg": "SEO title over 70 chars"},
    "desc_too_short": {"severity": "error", "msg": "Meta description under 140 chars"},
    "desc_too_long": {"severity": "warning", "msg": "Meta description over 165 chars"},
    "no_keywords": {"severity": "error", "msg": "No SEO keywords set"},
    "keyword_stuffing": {"severity": "warning", "msg": "More than 8 keywords"},
    "content_too_short": {"severity": "error", "msg": "Article under 300 words"},
    "no_structured_data": {"severity": "warning", "msg": "Missing JSON-LD schema"},
    "no_og_image": {"severity": "info", "msg": "No Open Graph image set"},
    "slug_has_stopwords": {"severity": "info", "msg": "URL slug contains stop words"},
}


def compute_reading_time(text: str) -> int:
    if not text:
        return 1
    return max(1, round(len(text.split()) / 200))


def clean_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if len(slug.split("-")) > 5:
        parts = [p for p in slug.split("-") if p not in STOP_WORDS]
        slug = "-".join(parts[:8])
    return slug[:80]


def score_seo(seo_data: dict, article_word_count: int, article_slug: str) -> tuple:
    """Returns (total_score, breakdown_dict, issues_list)."""
    breakdown = {}
    issues = []
    total = 0

    # Title
    title = seo_data.get("seo_title", "") or ""
    tlen = len(title)
    if 50 <= tlen <= 70:
        breakdown["title_length"] = SCORE_WEIGHTS["title_length"]
    elif 40 <= tlen < 50 or 70 < tlen <= 80:
        breakdown["title_length"] = int(SCORE_WEIGHTS["title_length"] * 0.6)
        issues.append({"code": "title_too_short" if tlen < 50 else "title_too_long",
                        **SEO_ISSUES["title_too_short" if tlen < 50 else "title_too_long"]})
    else:
        breakdown["title_length"] = 0
        issues.append({"code": "title_too_short" if tlen < 50 else "title_too_long",
                        **SEO_ISSUES["title_too_short" if tlen < 50 else "title_too_long"]})
    total += breakdown["title_length"]

    # Description
    desc = seo_data.get("seo_description", "") or ""
    dlen = len(desc)
    if 140 <= dlen <= 165:
        breakdown["meta_description"] = SCORE_WEIGHTS["meta_description"]
    elif 100 <= dlen < 140 or 165 < dlen <= 200:
        breakdown["meta_description"] = int(SCORE_WEIGHTS["meta_description"] * 0.6)
        issues.append({"code": "desc_too_short" if dlen < 140 else "desc_too_long",
                        **SEO_ISSUES["desc_too_short" if dlen < 140 else "desc_too_long"]})
    else:
        breakdown["meta_description"] = 0
        issues.append({"code": "desc_too_short", **SEO_ISSUES["desc_too_short"]})
    total += breakdown["meta_description"]

    # Keywords
    kws = seo_data.get("seo_keywords", []) or []
    kw_count = len(kws)
    if 3 <= kw_count <= 8:
        breakdown["keywords"] = SCORE_WEIGHTS["keywords"]
    elif kw_count > 8:
        breakdown["keywords"] = int(SCORE_WEIGHTS["keywords"] * 0.5)
        issues.append({"code": "keyword_stuffing", **SEO_ISSUES["keyword_stuffing"]})
    else:
        breakdown["keywords"] = 0
        issues.append({"code": "no_keywords", **SEO_ISSUES["no_keywords"]})
    total += breakdown["keywords"]

    # Content length
    if article_word_count >= 600:
        breakdown["content_length"] = SCORE_WEIGHTS["content_length"]
    elif article_word_count >= 300:
        breakdown["content_length"] = int(SCORE_WEIGHTS["content_length"] * 0.67)
    else:
        breakdown["content_length"] = 0
        issues.append({"code": "content_too_short", **SEO_ISSUES["content_too_short"]})
    total += breakdown["content_length"]

    # Structured data
    if seo_data.get("schema_json"):
        breakdown["structured_data"] = SCORE_WEIGHTS["structured_data"]
    else:
        breakdown["structured_data"] = 0
        issues.append({"code": "no_structured_data", **SEO_ISSUES["no_structured_data"]})
    total += breakdown["structured_data"]

    # OG image
    if seo_data.get("og_image_url"):
        breakdown["og_image"] = SCORE_WEIGHTS["og_image"]
    else:
        breakdown["og_image"] = 0
        issues.append({"code": "no_og_image", **SEO_ISSUES["no_og_image"]})
    total += breakdown["og_image"]

    # Slug
    slug_parts = article_slug.split("-") if article_slug else []
    stop_count = sum(1 for p in slug_parts if p in STOP_WORDS)
    if stop_count <= 2 and len(slug_parts) <= 8:
        breakdown["url_slug"] = SCORE_WEIGHTS["url_slug"]
    else:
        breakdown["url_slug"] = int(SCORE_WEIGHTS["url_slug"] * 0.5)
        if stop_count > 2:
            issues.append({"code": "slug_has_stopwords", **SEO_ISSUES["slug_has_stopwords"]})
    total += breakdown["url_slug"]

    return min(total, 100), breakdown, issues


def generate_rule_based_seo(article) -> dict:
    """Rule-based SEO generation — no AI needed. Fallback when Groq unavailable."""
    title = article.title or ""
    source_name = article.source.name if hasattr(article, "source") and article.source else "GlobalNews"
    category = article.source.category if hasattr(article, "source") and article.source else "News"
    date_str = ""
    if hasattr(article, "published_at") and article.published_at:
        try:
            date_str = article.published_at.strftime("%B %d, %Y")
        except Exception:
            date_str = "Today"
    else:
        date_str = "Today"

    # SEO title
    seo_title = title
    if len(title) > 60:
        seo_title = title[:57] + "..."
    elif len(title) < 40:
        seo_title = f"{title} | {category} News"
    if len(seo_title) > 70:
        seo_title = seo_title[:67] + "..."

    # SEO description
    headline_short = title[:80] + "..." if len(title) > 80 else title
    seo_desc = (
        f"{headline_short} - Reported by {source_name} on {date_str}. "
        f"Stay up to date with GlobalNews: AI-curated {category} news updated every 15 minutes."
    )
    if len(seo_desc) > 165:
        seo_desc = seo_desc[:162] + "..."

    # Keywords from tags
    keywords = []
    if hasattr(article, "article_tags") and article.article_tags:
        keywords = [at.tag.name for at in article.article_tags[:6] if at.tag]
    if not keywords:
        keywords = [category.lower(), source_name.lower(), "news", "latest"]

    og_title = title[:95] if len(title) <= 95 else title[:92] + "..."
    og_image = getattr(article, "image_url", None)

    return {
        "seo_title": seo_title,
        "seo_description": seo_desc,
        "seo_keywords": keywords[:8],
        "og_title": og_title,
        "og_description": seo_desc[:200],
        "og_image_url": og_image,
        "generation_method": "rule_based",
    }


def generate_schema_json(article, site_url: str = "http://localhost:8000") -> dict:
    """Generate JSON-LD NewsArticle structured data."""
    published = ""
    if hasattr(article, "published_at") and article.published_at:
        try:
            published = article.published_at.isoformat()
        except Exception:
            published = datetime.utcnow().isoformat()
    else:
        published = datetime.utcnow().isoformat()

    source_name = "GlobalNews"
    source_domain = site_url
    category = "News"
    if hasattr(article, "source") and article.source:
        source_name = article.source.name
        source_domain = f"https://{article.source.domain}" if article.source.domain else site_url
        category = article.source.category or "News"

    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": (article.title or "")[:110],
        "url": f"{site_url}/articles/{article.slug}",
        "datePublished": published,
        "dateModified": published,
        "author": {
            "@type": "Organization",
            "name": source_name,
            "url": source_domain,
        },
        "publisher": {
            "@type": "Organization",
            "name": "GlobalNews",
            "url": site_url,
        },
        "articleSection": category,
    }

    image_url = getattr(article, "image_url", None)
    if image_url:
        schema["image"] = image_url

    return schema
