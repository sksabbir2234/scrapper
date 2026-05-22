"""
Prompts scraper — fetches the awesome-chatgpt-prompts CSV from GitHub weekly
and stores entries in the PromptLibrary table.
"""

import csv
import hashlib
import io
import logging
import re
from datetime import datetime, timezone

import httpx
from slugify import slugify

logger = logging.getLogger(__name__)

AWESOME_PROMPTS_URL = "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/prompts.csv"

# Category detection based on prompt content / act title
_CATEGORY_PATTERNS = {
    "coding": [
        r"\bcode\b", r"\bprogram", r"\bdeveloper\b", r"\bsoftware\b",
        r"\bpython\b", r"\bjavascript\b", r"\bregex\b", r"\bdebug",
        r"\bapi\b", r"\bfrontend\b", r"\bbackend\b", r"\blinux\b",
        r"\bterminal\b", r"\bgit\b", r"\bdocker\b", r"\bsql\b",
    ],
    "writing": [
        r"\bwrite[rs]?\b", r"\bessay\b", r"\bpoet", r"\bcontent\b",
        r"\bcopywriter\b", r"\bjournalist\b", r"\bblog\b", r"\bstory",
        r"\btranslator\b", r"\blanguage\b", r"\bgramm", r"\beditor\b",
    ],
    "analysis": [
        r"\banaly", r"\bresearch", r"\bdata\b", r"\bscientist\b",
        r"\bstatistic", r"\bmath\b", r"\beconomist\b", r"\bfinancial\b",
        r"\bproduct\s+manager\b", r"\bstartup\b", r"\bstrateg",
    ],
    "creative": [
        r"\bdesign", r"\bart\b", r"\bmusic\b", r"\bfilm\b",
        r"\bcomedian\b", r"\bstand[\s-]up\b", r"\binterior\b",
        r"\bcreative\b", r"\bgame\b", r"\broleplay", r"\bfiction\b",
    ],
    "system": [
        r"\bact\s+as\b", r"\bprompt\b", r"\bsystem\b", r"\bassistant\b",
        r"\bcoach\b", r"\bmentor\b", r"\btherapist\b", r"\bdoctor\b",
        r"\blawyer\b", r"\baccountant\b", r"\bhr\b", r"\brecruiter\b",
    ],
}

_DIFFICULTY_PATTERNS = {
    "advanced": [
        r"\bexpert\b", r"\bsenior\b", r"\badvanced\b", r"\barchitect\b",
        r"\bprincipal\b", r"\blead\b", r"\bcto\b", r"\bcyber\s*security\b",
    ],
    "intermediate": [
        r"\bintermediate\b", r"\bexperienced\b", r"\bspecialist\b",
        r"\banalyst\b", r"\bdeveloper\b", r"\bengineer\b", r"\bmanager\b",
    ],
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _detect_category(act: str, prompt: str) -> str:
    text = f"{act} {prompt}".lower()
    scores = {}
    for cat, patterns in _CATEGORY_PATTERNS.items():
        scores[cat] = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "system"


def _detect_difficulty(act: str, prompt: str) -> str:
    text = f"{act} {prompt}".lower()
    for level, patterns in _DIFFICULTY_PATTERNS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            return level
    return "beginner"


def _extract_tags(act: str, prompt: str) -> list[str]:
    """Extract meaningful tags from act and prompt text."""
    tags = set()
    text = f"{act} {prompt}".lower()

    # Common domain tags
    tag_patterns = {
        "ai": r"\bartificial\s+intelligence\b|\bai\b|\bllm\b|\bchatgpt\b",
        "programming": r"\bprogramm|\bcod(e|ing)\b|\bdevelop",
        "writing": r"\bwrit(e|ing|er)\b|\bcontent\b|\bcopy\b",
        "business": r"\bbusiness\b|\bstartup\b|\bmarketing\b|\bsales\b",
        "education": r"\bteach|\btutor|\bleducat|\blearn",
        "health": r"\bhealth\b|\bmedical\b|\bdoctor\b|\bnutrition\b",
        "finance": r"\bfinanc|\binvest|\btax\b|\bbudget",
        "design": r"\bdesign\b|\bux\b|\bui\b|\bgraphic\b",
        "data": r"\bdata\b|\banalytics?\b|\bsql\b|\bdatabase\b",
        "security": r"\bsecurity\b|\bcyber|\bhack|\bpentest",
    }

    for tag, pattern in tag_patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            tags.add(tag)

    return sorted(tags)[:5]


def fetch_prompts_csv() -> str | None:
    """Download the awesome-chatgpt-prompts CSV."""
    headers = {"User-Agent": "NewsAI-Scraper"}
    try:
        resp = httpx.get(AWESOME_PROMPTS_URL, headers=headers, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch prompts CSV: {e}")
        return None


def parse_prompts_csv(csv_text: str) -> list[dict]:
    """Parse the CSV and return structured prompt data."""
    reader = csv.DictReader(io.StringIO(csv_text))

    prompts = []
    for row in reader:
        act = (row.get("act") or "").strip()
        prompt_text = (row.get("prompt") or "").strip()

        if not act or not prompt_text:
            continue

        category = _detect_category(act, prompt_text)
        difficulty = _detect_difficulty(act, prompt_text)
        tags = _extract_tags(act, prompt_text)

        prompts.append({
            "title": act[:200],
            "prompt_text": prompt_text,
            "category": category,
            "tags": ", ".join(tags) if tags else None,
            "difficulty": difficulty,
            "url_hash": _hash(act),
        })

    logger.info(f"Parsed {len(prompts)} prompts from awesome-chatgpt-prompts CSV")
    return prompts


def scrape_prompts() -> list[dict]:
    """Main entry — fetch and parse the prompts CSV."""
    csv_text = fetch_prompts_csv()
    if not csv_text:
        return []
    return parse_prompts_csv(csv_text)
