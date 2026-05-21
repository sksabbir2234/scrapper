import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Categories from PLAN.md
CATEGORIES = [
    "World",
    "Politics",
    "Technology",
    "Business",
    "Science",
    "Health",
    "Education",
    "Sports",
    "Entertainment",
]

# Model singleton (loaded once, cached)
_model = None


def _get_model():
    """Lazy-load the cross-encoder model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder("cross-encoder/nli-MiniLM-L2-mnli", max_length=512)
            logger.info("Loaded zero-shot classification model")
        except Exception as e:
            logger.error(f"Failed to load classification model: {e}")
            return None
    return _model


def classify_article(title: str, content: str, top_n: int = 3) -> list[dict]:
    """Classify article into categories using zero-shot cross-encoder.

    Returns list of dicts: [{"category": str, "confidence": float}, ...]
    sorted by confidence descending. Returns empty list on failure.
    """
    model = _get_model()
    if not model:
        return []

    try:
        # Combine title and first 500 chars of content
        text = f"{title}. {content[:500]}" if content else title

        # Create premise-hypothesis pairs for NLI
        # Hypothesis: "This article is about {category}"
        premise = text
        hypotheses = [f"This article is about {cat.lower()}" for cat in CATEGORIES]

        # Score all pairs
        pairs = [(premise, h) for h in hypotheses]
        scores = model.predict(pairs)

        # scores is a 2D array with [contradiction, neutral, entailment] logits
        # Use entailment column (index 2) as confidence
        import numpy as np
        if hasattr(scores, 'shape') and len(scores.shape) == 2:
            entailment_scores = scores[:, 2]  # entailment logit
        else:
            # If scores are already 1D (some model configs)
            entailment_scores = scores

        # Normalize to 0-1 range via softmax
        exp_scores = np.exp(entailment_scores - np.max(entailment_scores))
        probabilities = exp_scores / exp_scores.sum()

        # Build results sorted by confidence
        results = []
        for i, prob in enumerate(probabilities):
            results.append({
                "category": CATEGORIES[i],
                "confidence": round(float(prob), 4),
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:top_n]

    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return []


def get_primary_category(title: str, content: str) -> Optional[str]:
    """Get the single most likely category for an article."""
    results = classify_article(title, content, top_n=1)
    if results and results[0]["confidence"] > 0.3:
        return results[0]["category"]
    return None
