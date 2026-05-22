"""
OS Radar Potential Score — 5-signal formula (0-100 total)

Signal weights:
  star_velocity    : 30 pts  — growth momentum
  community_breadth: 20 pts  — contributor diversity
  commit_recency   : 15 pts  — active development
  issue_engagement : 15 pts  — community health
  documentation    : 10 pts  — adoption readiness
  license          : 10 pts  — ecosystem friendliness
"""

from datetime import datetime, timezone
from typing import Optional
import math


# ── Hard disqualifiers ────────────────────────────────────────────

SPAM_NAME_PREFIXES = [
    "awesome-", "list-of-", "collection-of-", "resources-",
    "awesome_", "lists-", "cheatsheet-", "roadmap-"
]

SPAM_TOPICS = {"awesome", "awesome-list", "resources", "cheatsheet"}


def should_disqualify(repo: dict) -> tuple[bool, str]:
    """Returns (True, reason) if repo should be skipped before scoring."""
    name = (repo.get("name") or "").lower()
    desc = repo.get("description") or ""
    stars = repo.get("stargazers_count", 0) or 0
    topics = set(repo.get("topics") or [])

    if repo.get("fork"):
        return True, "is_fork"
    if repo.get("archived"):
        return True, "archived"
    if stars < 10:
        return True, "too_few_stars"
    if not desc or len(desc) < 10:
        return True, "no_description"
    if any(name.startswith(p) for p in SPAM_NAME_PREFIXES):
        return True, "spam_name"
    if topics & SPAM_TOPICS:
        return True, "spam_topic"
    if repo.get("size", 0) == 0:
        return True, "empty_repo"

    return False, ""


# ── Signal 1: Star Velocity (30 pts) ─────────────────────────────

def score_star_velocity(stars: int, created_at_str: str) -> float:
    """Stars earned per day since creation. Sweet spot: 5-100 stars/day."""
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = max((now - created).days, 1)
        stars_per_day = stars / days
        normalized = min(stars_per_day, 500) / 500
        return round(normalized * 30, 2)
    except Exception:
        return 0.0


# ── Signal 2: Community Breadth (20 pts) ─────────────────────────

def score_community_breadth(contributors: int) -> float:
    """More unique contributors = healthier community."""
    if contributors <= 1:
        return 0.0
    if contributors <= 4:
        return 8.0
    score = min(20.0, 8.0 + math.log(contributors, 2) * 2.5)
    return round(score, 2)


# ── Signal 3: Commit Recency (15 pts) ────────────────────────────

def score_commit_recency(pushed_at_str: Optional[str]) -> float:
    """Decays linearly from 15 to 0 over 90 days since last push."""
    if not pushed_at_str:
        return 0.0
    try:
        pushed = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = (now - pushed).days
        return round(max(0.0, 15.0 * (1 - days / 90)), 2)
    except Exception:
        return 0.0


# ── Signal 4: Issue Engagement (15 pts) ──────────────────────────

def score_issue_engagement(open_issues: int, stars: int) -> float:
    """Healthy projects have 5-15% issue-to-star ratio."""
    if stars <= 0:
        return 4.0
    ratio = open_issues / stars
    if 0.05 <= ratio <= 0.15:
        return 15.0
    elif 0.02 <= ratio < 0.05:
        return 10.0
    elif 0.15 < ratio <= 0.30:
        return 8.0
    elif ratio < 0.02:
        return 4.0
    else:
        return 2.0


# ── Signal 5: Documentation Quality (10 pts) ─────────────────────

def score_documentation(repo: dict) -> float:
    """Checks presence of key documentation signals."""
    score = 0.0
    desc = repo.get("description") or ""
    if len(desc) >= 30:
        score += 3.0
    if repo.get("homepage"):
        score += 2.0
    topics = repo.get("topics") or []
    if len(topics) >= 3:
        score += 2.0
    if repo.get("has_wiki"):
        score += 2.0
    if repo.get("size", 0) > 10:
        score += 1.0
    return min(score, 10.0)


# ── Signal 6: License Friendliness (10 pts) ──────────────────────

PERMISSIVE_LICENSES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause",
    "isc", "unlicense", "cc0-1.0", "wtfpl", "zlib"
}
RESTRICTIVE_LICENSES = {
    "gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0",
    "agpl-3.0", "eupl-1.2", "cc-by-nc-4.0"
}


def score_license(license_data: Optional[dict]) -> float:
    """Permissive = 10, restrictive = 5, none = 0."""
    if not license_data:
        return 0.0
    key = (license_data.get("key") or "").lower()
    if key in PERMISSIVE_LICENSES:
        return 10.0
    elif key in RESTRICTIVE_LICENSES:
        return 5.0
    elif key:
        return 3.0
    return 0.0


# ── Master scorer ─────────────────────────────────────────────────

def calculate_potential_score(repo: dict, contributors: int) -> tuple[float, dict]:
    """Compute total potential score and breakdown. Returns (total, breakdown)."""
    breakdown = {
        "star_velocity":     score_star_velocity(
                                repo.get("stargazers_count", 0),
                                repo.get("created_at", "")
                             ),
        "community_breadth": score_community_breadth(contributors),
        "commit_recency":    score_commit_recency(repo.get("pushed_at")),
        "issue_engagement":  score_issue_engagement(
                                repo.get("open_issues_count", 0),
                                repo.get("stargazers_count", 0)
                             ),
        "documentation":     score_documentation(repo),
        "license":           score_license(repo.get("license")),
    }
    total = min(100.0, sum(breakdown.values()))
    return round(total, 1), breakdown
