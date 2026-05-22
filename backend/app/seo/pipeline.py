"""
SEO Pipeline — processes articles for SEO metadata.
Called from scheduler, never from scrape_single_source() directly.
"""

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from sqlalchemy import text

from app.seo.engine import (
    generate_rule_based_seo, generate_schema_json,
    score_seo, compute_reading_time,
)
from app.models import Article, ArticleSEO

logger = logging.getLogger("seo_pipeline")

def _get_site_url():
    from config.settings import get_settings
    return get_settings().site_url


def process_article_seo(article_id: int, db: Session) -> bool:
    """Generate and store SEO metadata for a single article."""
    try:
        article = db.query(Article).filter_by(id=article_id).first()
        if not article:
            return False

        existing = db.query(ArticleSEO).filter_by(article_id=article_id).first()
        if existing and existing.seo_score >= 70:
            return True

        # Rule-based generation (always works, no API needed)
        seo_data = generate_rule_based_seo(article)

        # JSON-LD schema
        site_url = _get_site_url()
        schema = generate_schema_json(article, site_url)

        # Score
        word_count = len((article.content_text or "").split())
        score, breakdown, issues = score_seo(seo_data, word_count, article.slug or "")

        # Upsert
        if existing:
            existing.seo_title = seo_data.get("seo_title")
            existing.seo_description = seo_data.get("seo_description")
            existing.seo_keywords = seo_data.get("seo_keywords", [])
            existing.og_title = seo_data.get("og_title")
            existing.og_description = seo_data.get("og_description")
            existing.og_image_url = seo_data.get("og_image_url")
            existing.canonical_url = f"{site_url}/articles/{article.slug}"
            existing.schema_json = schema
            existing.reading_time = compute_reading_time(article.content_text or "")
            existing.seo_score = score
            existing.score_breakdown = breakdown
            existing.issues = issues
            existing.updated_at = datetime.utcnow()
            existing.generation_method = seo_data.get("generation_method", "rule_based")
        else:
            db.add(ArticleSEO(
                article_id=article_id,
                seo_title=seo_data.get("seo_title"),
                seo_description=seo_data.get("seo_description"),
                seo_keywords=seo_data.get("seo_keywords", []),
                og_title=seo_data.get("og_title"),
                og_description=seo_data.get("og_description"),
                og_image_url=seo_data.get("og_image_url"),
                canonical_url=f"{site_url}/articles/{article.slug}",
                schema_json=schema,
                reading_time=compute_reading_time(article.content_text or ""),
                seo_score=score,
                score_breakdown=breakdown,
                issues=issues,
                generation_method=seo_data.get("generation_method", "rule_based"),
            ))

        db.commit()
        logger.info(f"SEO processed article {article_id}: score={score}")
        return True

    except Exception as e:
        logger.error(f"SEO pipeline failed for article {article_id}: {e}")
        db.rollback()
        return False


def run_seo_on_new_articles(db: Session, limit: int = 50):
    """Find articles missing SEO data and process them."""
    rows = db.execute(text(
        """
        SELECT a.id FROM articles a
        LEFT JOIN article_seo s ON a.id = s.article_id
        WHERE s.id IS NULL OR s.seo_score < 60
        ORDER BY a.created_at DESC
        LIMIT :lim
        """
    ), {"lim": limit}).fetchall()

    if not rows:
        return

    processed = 0
    for row in rows:
        if process_article_seo(row[0], db):
            processed += 1

    logger.info(f"SEO batch complete: {processed}/{len(rows)} articles processed")
