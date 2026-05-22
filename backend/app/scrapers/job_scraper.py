import time
import re
from datetime import datetime, timezone

import httpx

_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 600  # 10 minutes


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    clean = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", clean).strip()


def _fetch_remoteok() -> list[dict]:
    """Fetch jobs from RemoteOK public API."""
    try:
        resp = httpx.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for item in data:
            # First element is metadata/legal, skip non-job entries
            if not item.get("position") or not item.get("company"):
                continue
            salary = ""
            if item.get("salary_min") and item.get("salary_max"):
                salary = f"${item['salary_min']:,} - ${item['salary_max']:,}"
            jobs.append({
                "title": item["position"],
                "company": item["company"],
                "location": item.get("location", "Remote"),
                "salary": salary,
                "tags": item.get("tags", []),
                "url": item.get("apply_url") or item.get("url", ""),
                "source": "RemoteOK",
                "remote": True,
                "posted_at": item.get("date", ""),
                "logo": item.get("company_logo") or item.get("logo", ""),
                "description": _strip_html(item.get("description", ""))[:300],
            })
        return jobs
    except Exception:
        return []


def _fetch_arbeitnow() -> list[dict]:
    """Fetch jobs from Arbeitnow public API."""
    try:
        resp = httpx.get(
            "https://www.arbeitnow.com/api/job-board-api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", [])
        jobs = []
        for item in data:
            posted = ""
            if item.get("created_at"):
                try:
                    posted = datetime.fromtimestamp(
                        item["created_at"], tz=timezone.utc
                    ).isoformat()
                except Exception:
                    pass
            jobs.append({
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("location", ""),
                "salary": "",
                "tags": item.get("tags", []),
                "url": item.get("url", ""),
                "source": "Arbeitnow",
                "remote": bool(item.get("remote")),
                "posted_at": posted,
                "logo": "",
                "description": _strip_html(item.get("description", ""))[:300],
            })
        return jobs
    except Exception:
        return []


def fetch_live_jobs(
    keyword: str = "",
    location: str = "",
    remote_only: bool = False,
    source: str = "",
    cache_ttl: int = CACHE_TTL,
) -> list[dict]:
    """Fetch and merge jobs from all sources. Cached in memory."""
    global _cache, _cache_ts
    now = time.time()
    if not _cache or (now - _cache_ts) >= cache_ttl:
        jobs = _fetch_remoteok() + _fetch_arbeitnow()
        _cache = {"data": jobs}
        _cache_ts = now

    jobs = list(_cache.get("data", []))

    # Filter
    if keyword:
        kw = keyword.lower()
        jobs = [
            j for j in jobs
            if kw in j["title"].lower()
            or kw in j["company"].lower()
            or any(kw in t.lower() for t in j["tags"])
            or kw in j.get("description", "").lower()
        ]
    if location:
        loc = location.lower()
        jobs = [j for j in jobs if loc in j["location"].lower()]
    if remote_only:
        jobs = [j for j in jobs if j["remote"]]
    if source:
        jobs = [j for j in jobs if j["source"].lower() == source.lower()]

    return jobs


def fetch_job_stats(keyword: str = "", location: str = "", cache_ttl: int = CACHE_TTL) -> dict:
    """Aggregate stats from all cached jobs."""
    jobs = fetch_live_jobs(keyword=keyword, location=location, cache_ttl=cache_ttl)

    if not jobs:
        return {
            "total": 0, "remote_pct": 0, "top_skills": [],
            "sources": {}, "locations": [],
        }

    # Remote %
    remote_count = sum(1 for j in jobs if j["remote"])
    remote_pct = round(remote_count / len(jobs) * 100) if jobs else 0

    # Top skills (tag frequency)
    tag_counts: dict[str, int] = {}
    for j in jobs:
        for t in j["tags"]:
            tag = t.strip().lower()
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_skills = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    # Source breakdown
    sources: dict[str, int] = {}
    for j in jobs:
        sources[j["source"]] = sources.get(j["source"], 0) + 1

    # Top locations
    loc_counts: dict[str, int] = {}
    for j in jobs:
        loc = j["location"].strip()
        if loc:
            loc_counts[loc] = loc_counts.get(loc, 0) + 1
    top_locations = sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total": len(jobs),
        "remote_pct": remote_pct,
        "top_skills": [{"name": s[0], "count": s[1]} for s in top_skills],
        "sources": sources,
        "locations": [{"name": l[0], "count": l[1]} for l in top_locations],
    }
