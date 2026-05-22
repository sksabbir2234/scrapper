import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Model singleton (loaded once, cached)
_model = None
# Category cache: [(db_id, slug, name), ...]
_category_cache = None


def _get_categories_from_db():
    """Load categories from DB. Returns list of (id, slug, name) tuples."""
    global _category_cache
    if _category_cache is not None:
        return _category_cache

    try:
        from app.db.database import SessionLocal
        from app.models import Category
        db = SessionLocal()
        try:
            cats = db.query(Category).filter(Category.is_active == True).all()
            _category_cache = [(c.id, c.slug, c.name) for c in cats]
            logger.info(f"Loaded {len(_category_cache)} categories from DB")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to load categories from DB: {e}")
        # Fallback to defaults matching schema_v1.sql
        _category_cache = [
            (1, "world", "World"),
            (2, "politics", "Politics"),
            (3, "tech", "Technology"),
            (4, "business", "Business"),
            (5, "science", "Science"),
            (6, "health", "Health"),
            (7, "sports", "Sports"),
            (8, "entertainment", "Entertainment"),
        ]
    return _category_cache


def _get_model():
    """Lazy-load the cross-encoder model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder("cross-encoder/nli-deberta-v3-small", max_length=512)
            logger.info("Loaded zero-shot classification model")
        except Exception as e:
            logger.error(f"Failed to load classification model: {e}")
            return None
    return _model


def classify_article(title: str, content: str, top_n: int = 3) -> list[dict]:
    """Classify article into categories using zero-shot cross-encoder.

    Returns list of dicts: [{"category_id": int, "slug": str, "name": str, "confidence": float}, ...]
    sorted by confidence descending. Returns empty list on failure.
    """
    model = _get_model()
    if not model:
        return []

    categories = _get_categories_from_db()
    if not categories:
        return []

    try:
        import numpy as np

        # Combine title and first 500 chars of content
        text = f"{title}. {content[:500]}" if content else title

        # Create premise-hypothesis pairs for NLI using category names
        premise = text
        hypotheses = [f"This article is about {cat[2].lower()}" for cat in categories]

        # Score all pairs
        pairs = [(premise, h) for h in hypotheses]
        scores = model.predict(pairs)

        # scores is a 2D array with [contradiction, neutral, entailment] logits
        if hasattr(scores, 'shape') and len(scores.shape) == 2:
            entailment_scores = scores[:, 2]
        else:
            entailment_scores = scores

        # Normalize to 0-1 range via softmax
        exp_scores = np.exp(entailment_scores - np.max(entailment_scores))
        probabilities = exp_scores / exp_scores.sum()

        # Build results sorted by confidence
        results = []
        for i, prob in enumerate(probabilities):
            cat_id, slug, name = categories[i]
            results.append({
                "category_id": cat_id,
                "slug": slug,
                "name": name,
                "confidence": round(float(prob), 4),
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:top_n]

    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return []


def get_primary_category(title: str, content: str) -> Optional[dict]:
    """Get the single most likely category for an article.

    Returns dict with category_id, slug, name, confidence or None.
    """
    results = classify_article(title, content, top_n=1)
    if results and results[0]["confidence"] > 0.3:
        return results[0]
    return None


def classify_and_store(article_id: int, title: str, content: str, db) -> bool:
    """Classify article and store result in article_categories join table.

    Also sets article.category string field for backward compatibility.
    Returns True if classification was stored.
    """
    from app.models import Article, Category, ArticleCategory

    results = classify_article(title, content, top_n=1)
    if not results or results[0]["confidence"] <= 0.3:
        return False

    top = results[0]
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        return False

    # Set the flat category string (backward compat)
    article.category = top["slug"]

    # Store in join table
    existing = db.query(ArticleCategory).filter(
        ArticleCategory.article_id == article_id,
        ArticleCategory.category_id == top["category_id"],
    ).first()

    if not existing:
        db.add(ArticleCategory(
            article_id=article_id,
            category_id=top["category_id"],
            is_primary=True,
            confidence=int(top["confidence"] * 100),
        ))

    logger.info(f"Classified article {article_id} as {top['name']} ({top['confidence']:.2%})")
    return True
