"""Seed database with data from JSON/YAML config files.

Usage:
    python scripts/seed_db.py --all
    python scripts/seed_db.py --sources --finance --ai-tips
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy.orm import Session
from backend.app.db.database import SessionLocal, engine
from backend.app.models import (
    Base, Source, GithubUpdate, FinanceResource, FinanceQuizQuestion,
    PromptPattern, AIModelCard, AITool, AITip, OSSAlternative,
)
from config.source_loader import load_and_upsert_sources
from backend.app.scrapers.github_scraper import load_watch_list

Base.metadata.create_all(bind=engine)

SEED_DIR = Path(__file__).parent.parent / "config" / "seed"


def seed_sources(db: Session):
    inserted, updated, skipped = load_and_upsert_sources(db, Source)
    print(f"Sources: {inserted} inserted, {updated} updated, {skipped} skipped")


def seed_github(db: Session):
    repos = load_watch_list()
    print(f"GitHub watch list: {len(repos)} repos loaded (will populate on first scrape)")


def seed_finance(db: Session):
    # Concepts are loaded from JSON at runtime by the API, not stored in DB
    concepts_path = SEED_DIR / "finance_concepts.json"
    if concepts_path.exists():
        with open(concepts_path, "r", encoding="utf-8") as f:
            concepts = json.load(f)
        print(f"Finance concepts: {len(concepts)} loaded (served from JSON)")

    # Quiz questions
    quiz_path = SEED_DIR / "finance_quiz.json"
    if quiz_path.exists():
        with open(quiz_path, "r", encoding="utf-8") as f:
            questions = json.load(f)
        inserted = 0
        for q in questions:
            existing = db.query(FinanceQuizQuestion).filter(
                FinanceQuizQuestion.question == q["question"]
            ).first()
            if existing:
                continue
            db.add(FinanceQuizQuestion(
                question=q["question"],
                option_a=q["option_a"],
                option_b=q["option_b"],
                option_c=q["option_c"],
                option_d=q["option_d"],
                correct_answer=q["correct_answer"],
                explanation=q.get("explanation"),
                difficulty=q.get("difficulty", "beginner"),
                topic=q.get("topic"),
            ))
            inserted += 1
        db.commit()
        print(f"Finance quiz: {inserted} new questions ({len(questions)} total in file)")

    # Resources
    res_path = SEED_DIR / "finance_resources.json"
    if res_path.exists():
        with open(res_path, "r", encoding="utf-8") as f:
            resources = json.load(f)
        inserted = 0
        for r in resources:
            existing = db.query(FinanceResource).filter(
                FinanceResource.title == r["title"]
            ).first()
            if existing:
                continue
            db.add(FinanceResource(
                title=r["title"],
                url=r.get("url"),
                resource_type=r.get("resource_type"),
                level=r.get("level"),
                topic=r.get("topic"),
                description=r.get("description"),
            ))
            inserted += 1
        db.commit()
        print(f"Finance resources: {inserted} new ({len(resources)} total in file)")


def seed_ai_tips(db: Session):
    # Prompt patterns - loaded from JSON at runtime
    patterns_path = SEED_DIR / "prompt_patterns.json"
    if patterns_path.exists():
        with open(patterns_path, "r", encoding="utf-8") as f:
            patterns = json.load(f)
        inserted = 0
        for p in patterns:
            existing = db.query(PromptPattern).filter(
                PromptPattern.slug == p["slug"]
            ).first()
            if existing:
                continue
            db.add(PromptPattern(
                name=p["name"],
                slug=p["slug"],
                category=p.get("category"),
                pattern_text=p["pattern_text"],
                example_input=p.get("example_input"),
                example_output=p.get("example_output"),
                tips=p.get("tips"),
                difficulty=p.get("difficulty", "intermediate"),
            ))
            inserted += 1
        db.commit()
        print(f"Prompt patterns: {inserted} new ({len(patterns)} total in file)")

    # Model cards
    models_path = SEED_DIR / "ai_model_cards.json"
    if models_path.exists():
        with open(models_path, "r", encoding="utf-8") as f:
            models = json.load(f)
        inserted = 0
        for m in models:
            existing = db.query(AIModelCard).filter(
                AIModelCard.name == m["name"]
            ).first()
            if existing:
                # Update existing
                existing.provider = m.get("provider")
                existing.context_window = m.get("context_window")
                existing.pricing_note = m.get("pricing_note")
                existing.strengths = m.get("strengths")
                existing.weaknesses = m.get("weaknesses")
                existing.best_for = m.get("best_for")
                continue
            db.add(AIModelCard(
                name=m["name"],
                provider=m.get("provider"),
                model_type=m.get("model_type"),
                context_window=m.get("context_window"),
                pricing_note=m.get("pricing_note"),
                strengths=m.get("strengths"),
                weaknesses=m.get("weaknesses"),
                best_for=m.get("best_for"),
                api_url=m.get("api_url"),
            ))
            inserted += 1
        db.commit()
        print(f"AI model cards: {inserted} new ({len(models)} total in file)")

    # Tools
    tools_path = SEED_DIR / "ai_tools.json"
    if tools_path.exists():
        with open(tools_path, "r", encoding="utf-8") as f:
            tools = json.load(f)
        inserted = 0
        for t in tools:
            existing = db.query(AITool).filter(AITool.name == t["name"]).first()
            if existing:
                continue
            db.add(AITool(
                name=t["name"],
                url=t.get("url"),
                category=t.get("category"),
                description=t.get("description"),
            ))
            inserted += 1
        db.commit()
        print(f"AI tools: {inserted} new ({len(tools)} total in file)")

    # Tips
    tips_path = SEED_DIR / "ai_tips.json"
    if tips_path.exists():
        with open(tips_path, "r", encoding="utf-8") as f:
            tips = json.load(f)
        inserted = 0
        for t in tips:
            existing = db.query(AITip).filter(AITip.title == t["title"]).first()
            if existing:
                continue
            db.add(AITip(
                title=t["title"],
                content=t["content"],
                category=t.get("category"),
                is_featured=t.get("is_featured", False),
            ))
            inserted += 1
        db.commit()
        print(f"AI tips: {inserted} new ({len(tips)} total in file)")


def seed_oss(db: Session):
    oss_path = SEED_DIR / "oss_alternatives.json"
    if not oss_path.exists():
        print("OSS alternatives: no seed file found")
        return
    with open(oss_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    inserted = 0
    for e in entries:
        slug = f"{e['oss_name'].lower().replace(' ', '-')}-vs-{e['paid_name'].lower().replace(' ', '-').split('/')[0].strip()}"
        existing = db.query(OSSAlternative).filter(OSSAlternative.slug == slug).first()
        if existing:
            continue
        db.add(OSSAlternative(
            slug=slug,
            oss_name=e["oss_name"],
            oss_github=e.get("oss_github"),
            oss_url=e.get("oss_url", f"https://github.com/{e.get('oss_github', '')}"),
            oss_description=e.get("oss_description"),
            paid_name=e["paid_name"],
            paid_url=e.get("paid_url"),
            paid_price_hint=e.get("paid_price_hint"),
            category=e["category"],
            subcategory=e.get("subcategory"),
            tags=e.get("tags"),
            why_better=e.get("why_better"),
            quick_tip=e.get("quick_tip"),
            difficulty=e.get("difficulty", "medium"),
            self_hostable=e.get("self_hostable", True),
            has_free_tier=e.get("has_free_tier", True),
            featured=e.get("featured", False),
        ))
        inserted += 1
    db.commit()
    print(f"OSS alternatives: {inserted} new ({len(entries)} total in file)")


def main():
    parser = argparse.ArgumentParser(description="Seed database with config data")
    parser.add_argument("--sources", action="store_true", help="Seed news sources")
    parser.add_argument("--github", action="store_true", help="Seed GitHub watch list")
    parser.add_argument("--finance", action="store_true", help="Seed finance data")
    parser.add_argument("--ai-tips", action="store_true", help="Seed AI tips data")
    parser.add_argument("--oss", action="store_true", help="Seed OSS alternatives")
    parser.add_argument("--all", action="store_true", help="Seed everything")
    args = parser.parse_args()

    if not any([args.sources, args.github, args.finance, args.ai_tips, args.oss, args.all]):
        parser.print_help()
        return

    db = SessionLocal()
    try:
        if args.all or args.sources:
            seed_sources(db)
        if args.all or args.github:
            seed_github(db)
        if args.all or args.finance:
            seed_finance(db)
        if args.all or args.ai_tips:
            seed_ai_tips(db)
        if args.all or args.oss:
            seed_oss(db)
        print("\nDone!")
    finally:
        db.close()


if __name__ == "__main__":
    main()
