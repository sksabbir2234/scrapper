import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta

import httpx
import yaml
from pathlib import Path

GITHUB_API = "https://api.github.com"
WATCH_FILE = Path(__file__).parent.parent.parent.parent / "config" / "github_watch.yaml"

logger = logging.getLogger(__name__)
_rate_remaining = 999

_BREAKING_PATTERNS = [
    re.compile(r"BREAKING[-_ ]CHANGE", re.IGNORECASE),
    re.compile(r"^[a-z]+!:", re.MULTILINE),  # conventional commit breaking
    re.compile(r"\bbreaking\b", re.IGNORECASE),
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _headers(token: str | None = None) -> dict:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "NewsAI-Scraper"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check_rate_limit(resp: httpx.Response) -> bool:
    global _rate_remaining
    _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
    return _rate_remaining > 50


def has_rate_budget() -> bool:
    return _rate_remaining > 50


def _is_breaking(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _BREAKING_PATTERNS)


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def load_watch_list(path: Path = WATCH_FILE) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("repos", [])


def fetch_repo_metadata(owner: str, repo: str, token: str | None = None) -> dict | None:
    """Fetch full repo metadata from GitHub API."""
    if not has_rate_budget():
        return None
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        resp = httpx.get(url, headers=_headers(token), timeout=30)
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "watchers": data.get("subscribers_count", 0),
            "description": data.get("description", ""),
            "homepage": data.get("homepage", ""),
            "language": data.get("language", ""),
            "license": (data.get("license") or {}).get("spdx_id", ""),
            "is_archived": data.get("archived", False),
        }
    except Exception:
        logger.exception("fetch_repo_metadata failed for %s/%s", owner, repo)
        return None


def fetch_releases(owner: str, repo: str, token: str | None = None) -> list[dict]:
    if not has_rate_budget():
        return []
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    try:
        resp = httpx.get(url, headers=_headers(token), params={"per_page": 10}, timeout=30)
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return []
        releases = []
        for r in resp.json():
            body = (r.get("body") or "")[:5000]
            releases.append({
                "repo_name": f"{owner}/{repo}",
                "repo_url": f"https://github.com/{owner}/{repo}"[:1000],
                "update_type": "release",
                "title": r.get("name") or r.get("tag_name", "Unknown Release"),
                "body": body,
                "external_url": (r.get("html_url", ""))[:1000],
                "url_hash": _hash(r.get("html_url", "")),
                "published_at": _parse_date(r.get("published_at")),
                "is_breaking": _is_breaking(body),
            })
        return releases
    except Exception:
        logger.exception("fetch_releases failed for %s/%s", owner, repo)
        return []


def fetch_recent_commits(owner: str, repo: str, token: str | None = None) -> list[dict]:
    if not has_rate_budget():
        return []
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        resp = httpx.get(url, headers=_headers(token), params={"per_page": 20, "since": since}, timeout=30)
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return []
        commits = []
        for c in resp.json():
            commit_data = c.get("commit", {})
            msg = commit_data.get("message", "")
            commits.append({
                "repo_name": f"{owner}/{repo}",
                "repo_url": f"https://github.com/{owner}/{repo}",
                "update_type": "commit",
                "title": msg.split("\n")[0][:200],
                "body": msg,
                "external_url": (c.get("html_url", ""))[:1000],
                "url_hash": _hash(c.get("html_url", "")),
                "published_at": _parse_date(commit_data.get("committer", {}).get("date")),
                "is_breaking": _is_breaking(msg),
            })
        return commits
    except Exception:
        logger.exception("fetch_recent_commits failed for %s/%s", owner, repo)
        return []


def fetch_merged_prs(owner: str, repo: str, token: str | None = None) -> list[dict]:
    if not has_rate_budget():
        return []
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    try:
        resp = httpx.get(url, headers=_headers(token),
                         params={"state": "closed", "per_page": 10, "sort": "updated", "direction": "desc"},
                         timeout=30)
        _check_rate_limit(resp)
        if resp.status_code != 200:
            return []
        prs = []
        for pr in resp.json():
            if not pr.get("merged_at"):
                continue
            title = pr.get("title", "")
            prs.append({
                "repo_name": f"{owner}/{repo}",
                "repo_url": f"https://github.com/{owner}/{repo}"[:1000],
                "update_type": "pr",
                "title": title,
                "body": (pr.get("body") or "")[:2000],
                "external_url": (pr.get("html_url", ""))[:1000],
                "url_hash": _hash(pr.get("html_url", "")),
                "published_at": _parse_date(pr.get("merged_at")),
                "is_breaking": _is_breaking(title),
            })
        return prs
    except Exception:
        logger.exception("fetch_merged_prs failed for %s/%s", owner, repo)
        return []


def scrape_all_repos(token: str | None = None) -> tuple[list[dict], list[dict]]:
    """Scrape all repos. Returns (repo_metadata_list, updates_list).

    repo_metadata_list: [{full_name, metadata}, ...]
    updates_list: [{repo_name, update_type, title, ...}, ...]
    """
    global _rate_remaining
    _rate_remaining = 999
    repos = load_watch_list()
    all_updates = []
    repo_metadata = []

    for r in repos:
        if not has_rate_budget():
            break

        owner, repo_name = r["owner"], r["repo"]
        full_name = f"{owner}/{repo_name}"

        # Phase 1: Repo metadata
        meta = fetch_repo_metadata(owner, repo_name, token)
        if meta:
            repo_metadata.append({"full_name": full_name, **meta})

        # Phase 2: Releases
        releases = fetch_releases(owner, repo_name, token)
        for u in releases:
            u["label"] = r.get("label", full_name)
        all_updates.extend(releases)

        # Phase 3: Commits
        commits = fetch_recent_commits(owner, repo_name, token)
        for u in commits:
            u["label"] = r.get("label", full_name)
        all_updates.extend(commits)

        # Phase 4: Merged PRs
        if has_rate_budget():
            prs = fetch_merged_prs(owner, repo_name, token)
            for u in prs:
                u["label"] = r.get("label", full_name)
            all_updates.extend(prs)

        # Stamp stars/language from metadata onto updates
        if meta:
            for u in all_updates[-len(releases) - len(commits):]:
                u["stars"] = meta["stars"]
                u["language"] = meta["language"]

    return repo_metadata, all_updates
