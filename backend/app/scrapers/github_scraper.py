import hashlib
import time
from datetime import datetime, timezone

import httpx
import yaml
from pathlib import Path

GITHUB_API = "https://api.github.com"
WATCH_FILE = Path(__file__).parent.parent.parent.parent / "config" / "github_watch.yaml"

_rate_remaining = 999


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _headers(token: str | None = None) -> dict:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "NewsAI-Scraper"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check_rate_limit(resp: httpx.Response) -> bool:
    """Check rate limit. Returns True if we should continue, False if we should stop."""
    global _rate_remaining
    _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
    if _rate_remaining < 5:
        return False
    return True


def has_rate_budget() -> bool:
    """Check if we have remaining API budget."""
    return _rate_remaining > 5


def load_watch_list(path: Path = WATCH_FILE) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("repos", [])


def fetch_releases(owner: str, repo: str, token: str | None = None) -> list[dict]:
    if not has_rate_budget():
        return []
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    try:
        resp = httpx.get(url, headers=_headers(token), params={"per_page": 3}, timeout=30)
        if not _check_rate_limit(resp):
            pass  # Continue with this batch, stop after
        if resp.status_code != 200:
            return []
        releases = []
        for r in resp.json():
            releases.append({
                "repo_name": f"{owner}/{repo}",
                "repo_url": f"https://github.com/{owner}/{repo}",
                "update_type": "release",
                "title": r.get("name") or r.get("tag_name", "Unknown Release"),
                "body": (r.get("body") or "")[:5000],
                "external_url": r.get("html_url", ""),
                "url_hash": _hash(r.get("html_url", "")),
                "published_at": _parse_date(r.get("published_at")),
            })
        return releases
    except Exception:
        return []


def fetch_recent_commits(owner: str, repo: str, token: str | None = None) -> list[dict]:
    if not has_rate_budget():
        return []
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    try:
        resp = httpx.get(url, headers=_headers(token), params={"per_page": 3}, timeout=30)
        if not _check_rate_limit(resp):
            pass
        if resp.status_code != 200:
            return []
        commits = []
        for c in resp.json():
            commit_data = c.get("commit", {})
            commits.append({
                "repo_name": f"{owner}/{repo}",
                "repo_url": f"https://github.com/{owner}/{repo}",
                "update_type": "commit",
                "title": commit_data.get("message", "").split("\n")[0][:200],
                "body": commit_data.get("message", ""),
                "external_url": c.get("html_url", ""),
                "url_hash": _hash(c.get("html_url", "")),
                "published_at": _parse_date(commit_data.get("committer", {}).get("date")),
            })
        return commits
    except Exception:
        return []


def fetch_repo_info(owner: str, repo: str, token: str | None = None) -> dict | None:
    if not has_rate_budget():
        return None
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        resp = httpx.get(url, headers=_headers(token), timeout=30)
        if not _check_rate_limit(resp):
            pass
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "stars": data.get("stargazers_count", 0),
            "language": data.get("language", ""),
        }
    except Exception:
        return None


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def scrape_all_repos(token: str | None = None) -> list[dict]:
    global _rate_remaining
    _rate_remaining = 999  # Reset
    repos = load_watch_list()
    all_updates = []

    for r in repos:
        if not has_rate_budget():
            break

        owner, repo = r["owner"], r["repo"]

        # Fetch releases
        releases = fetch_releases(owner, repo, token)
        all_updates.extend(releases)

        # Fetch commits
        commits = fetch_recent_commits(owner, repo, token)
        all_updates.extend(commits)

        # Fetch repo info only if we have budget
        if has_rate_budget():
            info = fetch_repo_info(owner, repo, token)
            if info and (releases or commits):
                for u in all_updates[-len(releases) - len(commits):]:
                    u["stars"] = info["stars"]
                    u["language"] = info["language"]

    return all_updates
