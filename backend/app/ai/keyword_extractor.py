import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
import threading

logger = logging.getLogger(__name__)


def extract_keywords(title: str, content: str, max_keywords: int = 5) -> list[str]:
    """Extract keywords from article title + content using YAKE.

    Returns list of keyword strings (lowercased, deduplicated).
    """
    try:
        import yake

        text = f"{title}. {content[:2000]}" if content else title
        if not text or len(text.strip()) < 20:
            return []

        kw_extractor = yake.KeywordExtractor(
            lan="en",
            n=2,           # up to 2-word phrases
            top=max_keywords,
            dedupLim=0.7,  # dedup threshold
            dedupFunc="seqm",
        )

        keywords = kw_extractor.extract_keywords(text)
        # YAKE returns (keyword, score) tuples — lower score = more relevant
        return list(dict.fromkeys(kw[0].lower().strip() for kw in keywords if kw[0].strip()))

    except Exception as e:
        logger.error(f"Keyword extraction failed: {e}")
        return []


def extract_and_store_tags(db, article, Tag, ArticleTag):
    """Extract keywords for an article and store as tags.

    Creates Tag records if they don't exist, links via ArticleTag.
    Also stores as array on article.tags column.
    """
    from slugify import slugify
    from sqlalchemy import text

    keywords = extract_keywords(article.title, article.content_text)
    if not keywords:
        return []

    tag_names = []
    for kw in keywords:
        slug = slugify(kw)[:100]
        if not slug:
            continue

        # Find or create tag
        tag = db.query(Tag).filter(Tag.slug == slug).first()
        if not tag:
            tag = Tag(name=kw[:100], slug=slug)
            db.add(tag)
            db.flush()

        # Link article to tag (skip if exists)
        existing_link = db.query(ArticleTag).filter(
            ArticleTag.article_id == article.id,
            ArticleTag.tag_id == tag.id,
        ).first()

        if not existing_link:
            db.add(ArticleTag(article_id=article.id, tag_id=tag.id))

        tag_names.append(kw)

    # Store as TEXT[] array on article
    if tag_names:
        try:
            db.execute(
                text("UPDATE articles SET tags = :tags WHERE id = :id"),
                {"tags": tag_names, "id": article.id},
            )
        except Exception as e:
            logger.debug(f"Could not update tags array: {e}")

    return tag_names


def _extract_tags_batch(articles_data: list[dict]):
    """Run tag extraction on newly inserted articles in a background thread."""
    from sqlalchemy import text
    from app.db.database import SessionLocal
    from app.models import Article, Tag, ArticleTag

    def _run():
        db = SessionLocal()
        try:
            for article_data in articles_data:
                url_hash = article_data.get("url_hash")
                if not url_hash:
                    continue
                article = db.query(Article).filter(Article.url_hash == url_hash).first()
                if not article:
                    continue

                # Skip if already has tags
                existing_tags = db.query(ArticleTag).filter(ArticleTag.article_id == article.id).count()
                if existing_tags > 0:
                    continue

                tags = extract_and_store_tags(db, article, Tag, ArticleTag)
                if tags:
                    logger.info(f"Tagged '{article.title[:40]}...' with: {', '.join(tags)}")

            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Tag extraction batch failed: {e}")
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
