"""
OS Radar Gemstone Algorithm v2 — 8-signal formula (0-100 total)

Signal weights:
  quality_index    : 25 pts  — README, CI, tests, docs, changelog
  momentum         : 20 pts  — star acceleration (2nd derivative)
  community_health : 15 pts  — contributors + issue engagement
  freshness        : 15 pts  — commit recency
  underrated_index : 10 pts  — bonus when quality HIGH but stars LOW
  ecosystem_fit    :  5 pts  — package published, CI, examples
  license          :  5 pts  — permissive vs restrictive
  description      :  5 pts  — description quality
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
    if stars < 5:
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


# ── Signal 1: Quality Index (25 pts) ─────────────────────────────

QUALITY_SIGNALS = {
    "readme_size": 5,       # README.md > 2000 chars
    "has_ci": 5,            # .github/workflows/, .travis.yml, .circleci/
    "has_tests": 5,         # tests/, test/, __tests__/, spec/
    "has_contributing": 3,  # CONTRIBUTING.md, .github/CONTRIBUTING.md
    "has_changelog": 3,     # CHANGELOG.md, CHANGES.md, HISTORY.md
    "has_docs_dir": 2,      # docs/, doc/, documentation/
    "repo_size": 2,         # > 100 KB (not empty skeleton)
}


def score_quality_index(repo_tree: list[str], repo_size: int = 0) -> tuple[float, dict]:
    """Analyze repo file tree for quality signals. Returns (score, breakdown)."""
    if not repo_tree:
        return 0.0, {}

    tree_lower = [p.lower() for p in repo_tree]
    breakdown = {}
    score = 0.0

    # README size — check if README.md exists and is substantial
    readme_paths = [p for p in tree_lower if p.startswith("readme")]
    if readme_paths:
        # We can't get size from tree, but presence is a good signal
        breakdown["readme_present"] = True
        score += QUALITY_SIGNALS["readme_size"]

    # CI/CD configuration
    ci_patterns = [".github/workflows/", ".travis.yml", ".circleci/",
                   "azure-pipelines.yml", "Jenkinsfile", ".gitlab-ci.yml"]
    has_ci = any(any(p.startswith(pat.lower()) or p == pat.lower()
                     for pat in ci_patterns) for p in tree_lower)
    if has_ci:
        breakdown["has_ci"] = True
        score += QUALITY_SIGNALS["has_ci"]

    # Test directories
    test_patterns = ["tests/", "test/", "__tests__/", "spec/", "test_"]
    has_tests = any(any(p.startswith(pat) for pat in test_patterns)
                    for p in tree_lower)
    # Also check for test files like test_*.py, *_test.go, *.test.js
    if not has_tests:
        has_tests = any(
            "test" in p and (p.endswith(".py") or p.endswith(".go") or
                             p.endswith(".js") or p.endswith(".ts") or
                             p.endswith(".rs"))
            for p in tree_lower
        )
    if has_tests:
        breakdown["has_tests"] = True
        score += QUALITY_SIGNALS["has_tests"]

    # Contributing guide
    contributing = [".github/contributing.md", "contributing.md", ".github/issue_template"]
    has_contributing = any(p in tree_lower for p in contributing)
    if not has_contributing:
        has_contributing = any("contributing" in p for p in tree_lower)
    if has_contributing:
        breakdown["has_contributing"] = True
        score += QUALITY_SIGNALS["has_contributing"]

    # Changelog
    changelog = ["changelog.md", "changes.md", "history.md", "release_notes.md"]
    has_changelog = any(p in tree_lower for p in changelog)
    if has_changelog:
        breakdown["has_changelog"] = True
        score += QUALITY_SIGNALS["has_changelog"]

    # Documentation directory
    doc_dirs = ["docs/", "doc/", "documentation/", "wiki/"]
    has_docs = any(any(p.startswith(d) for d in doc_dirs) for p in tree_lower)
    if has_docs:
        breakdown["has_docs_dir"] = True
        score += QUALITY_SIGNALS["has_docs_dir"]

    # Repo size (> 100 KB suggests real project)
    if repo_size > 100:
        breakdown["substantial_size"] = True
        score += QUALITY_SIGNALS["repo_size"]

    return min(score, 25.0), breakdown


# ── Signal 2: Momentum (20 pts) — Star acceleration ──────────────

def score_momentum(stars: int, created_at_str: str,
                   score_history: list[tuple] | None = None) -> float:
    """Compute momentum from star acceleration.

    If score_history is available (list of (date, score, stars) tuples),
    we compute the 2nd derivative of star growth.
    Otherwise, fall back to stars/day with diminishing returns.
    """
    if score_history and len(score_history) >= 3:
        # Use actual star history to compute acceleration
        # Sort by date ascending
        sorted_hist = sorted(score_history, key=lambda x: x[0])
        star_counts = [h[2] for h in sorted_hist if h[2] is not None]
        if len(star_counts) >= 3:
            # Compute daily deltas
            deltas = [star_counts[i] - star_counts[i-1]
                      for i in range(1, len(star_counts))]
            if len(deltas) >= 2:
                # Acceleration = change in delta
                accel = deltas[-1] - deltas[0]
                # Positive acceleration = gaining momentum
                if accel > 0:
                    # Normalize: 10 stars/day acceleration = max score
                    return min(20.0, 10.0 + (accel / 10.0) * 10.0)
                elif accel == 0:
                    return 10.0  # Steady
                else:
                    return max(0.0, 10.0 + (accel / 5.0) * 5.0)

    # Fallback: stars/day with diminishing returns (log scale)
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = max((now - created).days, 1)
        stars_per_day = stars / days
        # Log scale: 1 star/day = 10pts, 10/day = 15pts, 100/day = 20pts
        if stars_per_day <= 0:
            return 0.0
        normalized = min(20.0, 10.0 + math.log10(max(stars_per_day, 0.1)) * 5.0)
        return round(normalized, 2)
    except Exception:
        return 0.0


# ── Signal 3: Community Health (15 pts) ──────────────────────────

def score_community_health(contributors: int, open_issues: int,
                           stars: int) -> float:
    """Contributor diversity + issue engagement."""
    score = 0.0

    # Contributor count (log scale, up to 10 pts)
    if contributors <= 1:
        score += 2.0
    elif contributors <= 4:
        score += 6.0
    else:
        score += min(10.0, 6.0 + math.log(contributors, 2) * 1.5)

    # Issue engagement: healthy projects have 5-15% issue-to-star ratio
    if stars > 0:
        ratio = open_issues / stars
        if 0.05 <= ratio <= 0.15:
            score += 5.0
        elif 0.02 <= ratio < 0.05:
            score += 3.0
        elif 0.15 < ratio <= 0.30:
            score += 3.0
        elif ratio < 0.02:
            score += 1.0
        else:
            score += 1.0
    else:
        score += 2.0

    return min(15.0, round(score, 2))


# ── Signal 4: Freshness (15 pts) ─────────────────────────────────

def score_freshness(pushed_at_str: Optional[str]) -> float:
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


# ── Signal 5: Underrated Index (10 pts) ──────────────────────────

def score_underrated(quality_score: float, stars: int) -> float:
    """Bonus when quality is HIGH but stars are LOW — the hidden gem signal.

    This is the secret sauce: a repo with great quality (CI, tests, docs)
    but few stars is exactly the kind of hidden gem we want to surface.
    """
    if quality_score < 10:
        return 0.0  # Low quality repos don't get underrated bonus

    # Quality-to-star ratio
    # quality_score is 0-25, normalize to 0-1
    quality_norm = quality_score / 25.0

    # Star penalty: more stars = less underrated
    # 5 stars = 1.0, 50 stars = 0.7, 500 stars = 0.4, 5000 stars = 0.1
    if stars <= 0:
        star_factor = 1.0
    else:
        star_factor = max(0.0, 1.0 - math.log10(max(stars, 1)) / 5.0)

    underrated = quality_norm * star_factor * 10.0
    return round(min(10.0, underrated), 2)


# ── Signal 6: Ecosystem Fit (5 pts) ──────────────────────────────

def score_ecosystem(repo_tree: list[str]) -> float:
    """Check for package manager files, CI, examples."""
    if not repo_tree:
        return 0.0

    tree_lower = [p.lower() for p in repo_tree]
    score = 0.0

    # Package manager files (project is publishable)
    package_files = [
        "package.json", "setup.py", "pyproject.toml", "setup.cfg",
        "cargo.toml", "go.mod", "gemspec", "composer.json",
        "build.gradle", "pom.xml", "pubspec.yaml", "cabal",
        "mix.exs", "deno.json", "bun.lockb"
    ]
    has_package = any(any(p.endswith(f) or p == f for f in package_files)
                      for p in tree_lower)
    if has_package:
        score += 2.0

    # Examples directory
    example_dirs = ["examples/", "example/", "demo/", "samples/"]
    has_examples = any(any(p.startswith(d) for d in example_dirs)
                       for p in tree_lower)
    if has_examples:
        score += 2.0

    # API documentation
    api_docs = ["api.md", "api-reference.md", "openapi", "swagger"]
    has_api = any(any(a in p for a in api_docs) for p in tree_lower)
    if has_api:
        score += 1.0

    return min(5.0, score)


# ── Signal 7: License (5 pts) ────────────────────────────────────

PERMISSIVE_LICENSES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause",
    "isc", "unlicense", "cc0-1.0", "wtfpl", "zlib"
}
RESTRICTIVE_LICENSES = {
    "gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0",
    "agpl-3.0", "eupl-1.2", "cc-by-nc-4.0"
}


def score_license(license_data: Optional[dict]) -> float:
    """Permissive = 5, restrictive = 3, none = 0."""
    if not license_data:
        return 0.0
    key = (license_data.get("key") or "").lower()
    if key in PERMISSIVE_LICENSES:
        return 5.0
    elif key in RESTRICTIVE_LICENSES:
        return 3.0
    elif key:
        return 1.0
    return 0.0


# ── Signal 8: Description Quality (5 pts) ────────────────────────

def score_description(desc: str | None) -> float:
    """Score description quality — length, specificity, action verbs."""
    if not desc:
        return 0.0

    score = 0.0

    # Length
    if len(desc) >= 100:
        score += 2.0
    elif len(desc) >= 50:
        score += 1.5
    elif len(desc) >= 30:
        score += 1.0

    # Contains technical keywords (suggests real project, not marketing)
    tech_words = ["api", "sdk", "library", "framework", "tool", "cli",
                  "database", "server", "client", "parser", "compiler",
                  "runtime", "engine", "compiler", "interpreter", "driver"]
    desc_lower = desc.lower()
    tech_count = sum(1 for w in tech_words if w in desc_lower)
    score += min(2.0, tech_count * 0.5)

    # Contains action verbs (describes what it does)
    action_words = ["build", "create", "generate", "parse", "convert",
                    "deploy", "manage", "monitor", "automate", "process",
                    "handle", "implement", "support", "provide", "enable"]
    action_count = sum(1 for w in action_words if w in desc_lower)
    score += min(1.0, action_count * 0.3)

    return min(5.0, round(score, 2))


# ── Master scorer ─────────────────────────────────────────────────

def calculate_potential_score(
    repo: dict,
    contributors: int,
    repo_tree: list[str] | None = None,
    score_history: list[tuple] | None = None,
) -> tuple[float, dict]:
    """Compute total Gemstone score and breakdown. Returns (total, breakdown)."""

    quality_score, quality_detail = score_quality_index(
        repo_tree or [], repo.get("size", 0)
    )

    breakdown = {
        "quality_index":     quality_score,
        "quality_detail":    quality_detail,
        "momentum":          score_momentum(
                                repo.get("stargazers_count", 0),
                                repo.get("created_at", ""),
                                score_history,
                             ),
        "community_health":  score_community_health(
                                contributors,
                                repo.get("open_issues_count", 0),
                                repo.get("stargazers_count", 0),
                             ),
        "freshness":         score_freshness(repo.get("pushed_at")),
        "underrated_index":  score_underrated(
                                quality_score,
                                repo.get("stargazers_count", 0),
                             ),
        "ecosystem_fit":     score_ecosystem(repo_tree or []),
        "license":           score_license(repo.get("license")),
        "description":       score_description(repo.get("description")),
    }
    total = min(100.0, sum(v for k, v in breakdown.items()
                           if k != "quality_detail"))
    return round(total, 1), breakdown
