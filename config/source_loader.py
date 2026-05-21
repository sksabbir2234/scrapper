import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SOURCES_YAML_PATH = Path(__file__).parent / "sources.yaml"

# YAML key -> Model column mapping
FIELD_MAP = {
    "rss": "rss_url",
    "country": "country_code",
}


def load_yaml_sources(path: Path = SOURCES_YAML_PATH) -> list[dict]:
    """Read sources.yaml and return a list of dicts with model-column keys."""
    if not path.exists():
        logger.warning(f"Sources YAML not found at {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "sources" not in data:
        logger.warning("No 'sources' key found in YAML")
        return []

    sources = []
    for entry in data["sources"]:
        mapped = {}
        for key, value in entry.items():
            model_key = FIELD_MAP.get(key, key)
            mapped[model_key] = value
        sources.append(mapped)

    return sources


def upsert_sources(db: Session, sources: list[dict], Source) -> tuple[int, int, int]:
    """Upsert sources into DB. Returns (inserted, updated, skipped) counts.

    Args:
        db: SQLAlchemy session
        sources: list of dicts from load_yaml_sources()
        Source: the Source model class (passed in to avoid import path issues)
    """
    inserted = 0
    updated = 0
    skipped = 0

    CONFIG_FIELDS = [
        "domain", "rss_url", "category", "country_code",
        "credibility_score", "scrape_type", "scrape_interval_min",
    ]

    for source_data in sources:
        name = source_data.get("name")
        if not name:
            logger.warning(f"Skipping source with no name: {source_data}")
            skipped += 1
            continue

        existing = db.query(Source).filter(Source.name == name).first()

        if existing:
            for field in CONFIG_FIELDS:
                if field in source_data:
                    setattr(existing, field, source_data[field])
            updated += 1
            logger.info(f"Updated source: {name}")
        else:
            new_source = Source(**source_data)
            db.add(new_source)
            inserted += 1
            logger.info(f"Inserted source: {name}")

    db.commit()
    return inserted, updated, skipped


def load_and_upsert_sources(db: Session, Source, path: Path = SOURCES_YAML_PATH) -> tuple[int, int, int]:
    """Convenience: load YAML then upsert. Returns (inserted, updated, skipped)."""
    sources = load_yaml_sources(path)
    if not sources:
        return 0, 0, 0
    return upsert_sources(db, sources, Source)
