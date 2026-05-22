"""
OS Radar — Hidden Gem Discovery Engine
Finds open-source projects gaining momentum before mainstream attention.

5 Discovery Strategies:
  1. trending_languages  — new repos by language, sorted by stars
  2. topic_surfing       — repos matching hot tech topics
  3. star_accelerators   — fast-growing repos created in last 30 days
  4. fresh_active        — recently pushed repos created in last 60 days
  5. fork_signals        — high fork-to-star ratio (people using, not just starring)
"""

import httpx
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.scrapers.github_scraper import _check_rate_limit, has_rate_budget
from app.scrapers.os_radar_scorer import calculate_potential_score, should_disqualify

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 10

# ── Discovery configuration ───────────────────────────────────────

TARGET_LANGUAGES = [
    "python", "typescript", "rust", "go",
    "java", "cpp", "javascript", "csharp"
]

HOT_TOPICS = [
    "ai", "llm", "machine-learning", "webassembly",
    "cli", "database", "devtools", "kubernetes",
    "mcp", "agent", "rag", "vector-database"
]

WATCHED_REPO_CACHE: set[str] = set()


# ── HTTP helpers ──────────────────────────────────────────────────

def _headers(token: Optional[str] = None) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _search_repos(query: str, sort: str, order: str,
                  per_page: int, token: str) -> list[dict]:
    """GitHub search with rate limit check. Returns list of repo items."""
    if not has_rate_budget():
        logger.warning("Radar: rate budget low — skipping search")
        return []

    url = f"{GITHUB_API}/search/repositories"
    params = {"q": query, "sort": sort, "order": order, "per_page": per_page}

    for attempt in range(2):
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.get(url, headers=_headers(token), params=params)

            _check_rate_limit(resp)

            if resp.status_code == 200:
                return resp.json().get("items", [])
            elif resp.status_code == 429:
                logger.warning("Radar: 429 rate limited — sleeping 60s")
                time.sleep(60)
                if attempt == 1:
                    logger.warning("Radar: second 429 — aborting this search")
                    return []
            elif resp.status_code == 422:
                logger.warning(f"Radar: bad search query: {query}")
                return []
            else:
                logger.warning(f"Radar: search returned {resp.status_code}")
                return []
        except Exception as e:
            logger.error(f"Radar: search error: {e}")
            return []

    return []


def _get_contributor_count(owner: str, repo: str, token: str) -> int:
    """Get contributor count using Link header trick."""
    if not has_rate_budget():
        return 1
    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contributors"
        params = {"per_page": 1, "anon": "true"}
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(url, headers=_headers(token), params=params)
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return 1
        link = resp.headers.get("link", "")
        if 'rel="last"' in link:
            match = re.search(r'page=(\d+)>; rel="last"', link)
            if match:
                return int(match.group(1))
        items = resp.json()
        return len(items) if isinstance(items, list) else 1
    except Exception:
        return 1


# ── Strategy 1: Trending Languages ───────────────────────────────

def discover_trending_languages(token: str, db) -> dict:
    """Find repos created in last 90 days, sorted by stars, per language."""
    log = {"strategy": "trending_languages", "found": 0, "new": 0, "updated": 0, "skipped": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    for lang in TARGET_LANGUAGES:
        query = f"language:{lang} created:>{cutoff} stars:>20"
        repos = _search_repos(query, "stars", "desc", 10, token)

        for repo in repos:
            log["found"] += 1
            result = _process_repo(repo, "trending_languages", token, db)
            log[result] = log.get(result, 0) + 1

        time.sleep(2)

    return log


# ── Strategy 2: Topic Surfing ─────────────────────────────────────

def discover_by_topics(token: str, db) -> dict:
    """Search repos by hot tech topics."""
    log = {"strategy": "topic_surfing", "found": 0, "new": 0, "updated": 0, "skipped": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")

    for topic in HOT_TOPICS:
        query = f"topic:{topic} created:>{cutoff} stars:>30 pushed:>{cutoff}"
        repos = _search_repos(query, "stars", "desc", 8, token)

        for repo in repos:
            log["found"] += 1
            result = _process_repo(repo, "topic_surfing", token, db)
            log[result] = log.get(result, 0) + 1

        time.sleep(2)

    return log


# ── Strategy 3: Star Accelerators ────────────────────────────────

def discover_star_accelerators(token: str, db) -> dict:
    """Find repos created in last 30 days with 100-5000 stars."""
    log = {"strategy": "star_accelerators", "found": 0, "new": 0, "updated": 0, "skipped": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    query = f"created:>{cutoff} stars:100..5000"
    repos = _search_repos(query, "stars", "desc", 30, token)

    for repo in repos:
        log["found"] += 1
        result = _process_repo(repo, "star_accelerators", token, db)
        log[result] = log.get(result, 0) + 1

    return log


# ── Strategy 4: Fresh & Active ────────────────────────────────────

def discover_fresh_active(token: str, db) -> dict:
    """Repos created in last 60 days AND pushed in last 7 days with 50+ stars."""
    log = {"strategy": "fresh_active", "found": 0, "new": 0, "updated": 0, "skipped": 0}
    created_cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    pushed_cutoff  = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    query = f"created:>{created_cutoff} pushed:>{pushed_cutoff} stars:>50"
    repos = _search_repos(query, "updated", "desc", 25, token)

    for repo in repos:
        log["found"] += 1
        result = _process_repo(repo, "fresh_active", token, db)
        log[result] = log.get(result, 0) + 1

    return log


# ── Strategy 5: Fork Signals ──────────────────────────────────────

def discover_fork_signals(token: str, db) -> dict:
    """High fork-to-star ratio (>20%) means people are actively building on it."""
    log = {"strategy": "fork_signals", "found": 0, "new": 0, "updated": 0, "skipped": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
    query = f"created:>{cutoff} forks:>20 stars:50..10000"
    repos = _search_repos(query, "forks", "desc", 30, token)

    for repo in repos:
        stars = repo.get("stargazers_count", 0) or 1
        forks = repo.get("forks_count", 0) or 0
        fork_ratio = forks / stars

        if fork_ratio < 0.20:
            log["skipped"] = log.get("skipped", 0) + 1
            continue

        log["found"] += 1
        result = _process_repo(repo, "fork_signals", token, db)
        log[result] = log.get(result, 0) + 1

    return log


# ── Core processing function ──────────────────────────────────────

def _process_repo(repo: dict, source: str, token: str, db) -> str:
    """Process a single repo. Returns: 'new', 'updated', 'skipped', or 'error'."""
    from app.models import DiscoveredProject, DiscoveredProjectScore

    full_name = repo.get("full_name", "")
    if not full_name:
        return "skipped"

    disqualified, reason = should_disqualify(repo)
    if disqualified:
        return "skipped"

    if full_name in WATCHED_REPO_CACHE:
        return "skipped"

    try:
        owner, repo_name = full_name.split("/", 1)
    except ValueError:
        return "skipped"

    contributors = _get_contributor_count(owner, repo_name, token)
    score, breakdown = calculate_potential_score(repo, contributors)

    def parse_dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    try:
        existing = db.query(DiscoveredProject).filter_by(full_name=full_name).first()

        if existing:
            existing.stars           = repo.get("stargazers_count", 0)
            existing.forks           = repo.get("forks_count", 0)
            existing.open_issues     = repo.get("open_issues_count", 0)
            existing.watchers        = repo.get("watchers_count", 0)
            existing.contributors    = contributors
            existing.repo_pushed_at  = parse_dt(repo.get("pushed_at"))
            existing.potential_score = score
            existing.score_breakdown = breakdown
            existing.last_scored     = datetime.utcnow()

            if score < 20:
                existing.consecutive_low_score_days += 1
                if existing.consecutive_low_score_days >= 7:
                    existing.is_active = False
            else:
                existing.consecutive_low_score_days = 0

            result = "updated"
        else:
            db.add(DiscoveredProject(
                full_name        = full_name,
                repo_url         = repo.get("html_url", f"https://github.com/{full_name}"),
                owner            = owner,
                repo             = repo_name,
                description      = (repo.get("description") or "")[:500],
                language         = repo.get("language"),
                license_name     = (repo.get("license") or {}).get("spdx_id"),
                topics           = repo.get("topics") or [],
                stars            = repo.get("stargazers_count", 0),
                forks            = repo.get("forks_count", 0),
                open_issues      = repo.get("open_issues_count", 0),
                watchers         = repo.get("watchers_count", 0),
                contributors     = contributors,
                repo_created_at  = parse_dt(repo.get("created_at")),
                repo_pushed_at   = parse_dt(repo.get("pushed_at")),
                potential_score  = score,
                score_breakdown  = breakdown,
                discovery_source = source,
            ))
            result = "new"

        db.flush()

        # Insert daily score snapshot
        project_id = existing.id if existing else (
            db.query(DiscoveredProject).filter_by(full_name=full_name).first().id
        )
        from datetime import date
        today = date.today()
        existing_score_row = db.query(DiscoveredProjectScore).filter_by(
            project_id=project_id, scored_at=today
        ).first()

        if existing_score_row:
            existing_score_row.score = score
            existing_score_row.stars = repo.get("stargazers_count", 0)
        else:
            db.add(DiscoveredProjectScore(
                project_id = project_id,
                scored_at  = today,
                score      = score,
                stars      = repo.get("stargazers_count", 0),
            ))

        db.commit()
        return result

    except Exception as e:
        logger.error(f"Radar: error processing {full_name}: {e}")
        db.rollback()
        return "error"


# ── Orchestrator ──────────────────────────────────────────────────

def run_discovery_strategy(strategy_name: str, token: str, db) -> dict:
    """Run a single named strategy. Called by scheduler with staggered timing."""
    from app.models import RadarRunLog, GithubRepo

    if not token:
        logger.warning("Radar: GITHUB_TOKEN not set — skipping strategy")
        return {"status": "skipped", "reason": "no_token"}

    global WATCHED_REPO_CACHE
    watched = db.query(GithubRepo.full_name).all()
    WATCHED_REPO_CACHE = {r[0] for r in watched}

    log_row = RadarRunLog(strategy=strategy_name, status="running")
    db.add(log_row)
    db.commit()

    strategy_map = {
        "trending_languages": discover_trending_languages,
        "topic_surfing":      discover_by_topics,
        "star_accelerators":  discover_star_accelerators,
        "fresh_active":       discover_fresh_active,
        "fork_signals":       discover_fork_signals,
    }

    fn = strategy_map.get(strategy_name)
    if not fn:
        log_row.status = "error"
        log_row.error_message = f"Unknown strategy: {strategy_name}"
        log_row.finished_at = datetime.utcnow()
        db.commit()
        return {"status": "error"}

    try:
        result = fn(token, db)
        log_row.repos_found   = result.get("found", 0)
        log_row.repos_new     = result.get("new", 0)
        log_row.repos_updated = result.get("updated", 0)
        log_row.repos_skipped = result.get("skipped", 0)
        log_row.status        = "success"
        log_row.finished_at   = datetime.utcnow()
        db.commit()
        logger.info(f"Radar [{strategy_name}]: {result}")
        return result

    except Exception as e:
        log_row.status        = "error"
        log_row.error_message = str(e)
        log_row.finished_at   = datetime.utcnow()
        db.commit()
        logger.error(f"Radar [{strategy_name}] failed: {e}")
        return {"status": "error", "error": str(e)}
