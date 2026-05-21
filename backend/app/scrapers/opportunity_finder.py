"""GitHub Opportunity Finder — search repos by keyword and rank by opportunity signals."""
import time
from datetime import datetime, timezone

import httpx

GITHUB_API = "https://api.github.com"


def _headers(token: str | None = None) -> dict:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "NewsAI-Scraper"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search_repos(keyword: str, token: str | None = None, limit: int = 30) -> list[dict]:
    """Search GitHub repos by keyword."""
    url = f"{GITHUB_API}/search/repositories"
    params = {"q": keyword, "sort": "stars", "order": "desc", "per_page": limit}
    try:
        resp = httpx.get(url, headers=_headers(token), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception:
        return []


def get_contributor_count(owner: str, repo: str, token: str | None = None) -> int:
    """Get total contributor count using Link header trick."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contributors"
    params = {"per_page": 1, "anon": "true"}
    try:
        resp = httpx.get(url, headers=_headers(token), params=params, timeout=15)
        if resp.status_code != 200:
            return 0
        link = resp.headers.get("Link", "")
        if 'rel="last"' in link:
            last_page = link.split("page=")[-1].split(">")[0]
            return int(last_page)
        return len(resp.json())
    except Exception:
        return 0


def _recency_score(pushed_at: str | None) -> float:
    """Score 1.0 if committed in last 7 days, decays to 0 over 6 months."""
    if not pushed_at:
        return 0.0
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days_ago = (datetime.now(timezone.utc) - pushed).total_seconds() / 86400
        if days_ago <= 7:
            return 1.0
        elif days_ago >= 180:
            return 0.0
        else:
            return 1.0 - (days_ago - 7) / 173  # linear decay over ~6 months
    except (ValueError, AttributeError):
        return 0.0


def _normalize(values: list[float]) -> list[float]:
    """Normalize values to 0-1 range."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def score_repos(repos: list[dict], contributor_counts: list[int]) -> list[dict]:
    """Score repos using opportunity signals. Returns sorted list."""
    if not repos:
        return []

    stars_list = [r.get("stargazers_count", 0) for r in repos]
    issues_list = [r.get("open_issues_count", 0) for r in repos]
    recency_list = [_recency_score(r.get("pushed_at")) for r in repos]

    norm_stars = _normalize(stars_list)
    norm_issues = _normalize(issues_list)
    norm_contribs = _normalize([float(c) for c in contributor_counts])

    scored = []
    for i, repo in enumerate(repos):
        score = (
            norm_stars[i] * 0.25
            + recency_list[i] * 0.30
            + norm_issues[i] * 0.25
            + norm_contribs[i] * 0.20
        ) * 100

        owner = repo.get("owner", {}).get("login", "")
        full_name = repo.get("full_name", f"{owner}/{repo.get('name', '')}")

        scored.append({
            "rank": 0,
            "name": full_name,
            "url": repo.get("html_url", ""),
            "description": (repo.get("description") or "")[:200],
            "stars": repo.get("stargazers_count", 0),
            "open_issues": repo.get("open_issues_count", 0),
            "language": repo.get("language") or "",
            "last_commit": repo.get("pushed_at", ""),
            "contributors": contributor_counts[i] if i < len(contributor_counts) else 0,
            "topics": repo.get("topics", []),
            "score": round(score, 1),
            "forks": repo.get("forks_count", 0),
            "license": (repo.get("license") or {}).get("spdx_id", ""),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(scored):
        r["rank"] = i + 1

    return scored


def find_opportunities(keyword: str, token: str | None = None, limit: int = 30) -> list[dict]:
    """Full pipeline: search, fetch contributors, score, rank."""
    repos = search_repos(keyword, token, limit)
    if not repos:
        return []

    # Fetch contributor counts with rate limit awareness
    contributor_counts = []
    for r in repos:
        owner = r.get("owner", {}).get("login", "")
        name = r.get("name", "")
        count = get_contributor_count(owner, name, token)
        contributor_counts.append(count)
        time.sleep(0.5)  # Respect rate limits

    return score_repos(repos, contributor_counts)
