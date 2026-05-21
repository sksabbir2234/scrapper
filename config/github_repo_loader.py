import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GITHUB_WATCH_YAML_PATH = Path(__file__).parent / "github_watch.yaml"


def load_yaml_repos(path: Path = GITHUB_WATCH_YAML_PATH) -> list[dict]:
    """Read github_watch.yaml and return a list of dicts."""
    if not path.exists():
        logger.warning(f"GitHub watch YAML not found at {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "repos" not in data:
        logger.warning("No 'repos' key found in github_watch.yaml")
        return []

    return data["repos"]


def upsert_github_repos(db: Session, repos: list[dict], GithubRepo) -> tuple[int, int]:
    """Upsert GitHub repos into DB. Returns (inserted, updated) counts."""
    inserted = 0
    updated = 0

    for entry in repos:
        owner = entry.get("owner")
        repo_name = entry.get("repo")
        if not owner or not repo_name:
            continue

        full_name = f"{owner}/{repo_name}"
        existing = db.query(GithubRepo).filter(GithubRepo.full_name == full_name).first()

        if existing:
            # Update config fields
            existing.label = entry.get("label", existing.label)
            existing.category = entry.get("category", existing.category)
            existing.tags = entry.get("tags", existing.tags)
            updated += 1
        else:
            new_repo = GithubRepo(
                owner=owner,
                repo=repo_name,
                label=entry.get("label", full_name),
                full_name=full_name,
                repo_url=f"https://github.com/{full_name}",
                category=entry.get("category"),
                tags=entry.get("tags"),
            )
            db.add(new_repo)
            inserted += 1

    db.commit()
    return inserted, updated


def load_and_upsert_github_repos(db: Session, GithubRepo) -> tuple[int, int]:
    """Load YAML and upsert. Called at startup."""
    repos = load_yaml_repos()
    if not repos:
        return 0, 0
    return upsert_github_repos(db, repos, GithubRepo)
