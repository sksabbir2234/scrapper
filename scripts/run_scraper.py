import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from backend.app.db.database import SessionLocal, engine
from backend.app.models import Base, Source, Article, ScrapeLog, Tag, ArticleTag
from backend.app.scrapers.rss_scraper import scrape_rss_feed
from backend.app.scrapers.playwright_scraper import scrape_with_playwright
from backend.app.ai.summarizer import summarize_article
from backend.app.ai.classifier import get_primary_category
from backend.app.ai.keyword_extractor import extract_and_store_tags
from config.source_loader import load_and_upsert_sources

Base.metadata.create_all(bind=engine)


def seed_sources(db: Session):
    inserted, updated, skipped = load_and_upsert_sources(db, Source)
    print(f"Sources synced: {inserted} inserted, {updated} updated, {skipped} skipped")


def run_scraper(source_names: list[str] = None, limit: int = None, summarize: bool = False, classify: bool = False, tags: bool = False):
    db = SessionLocal()
    
    try:
        if source_names:
            sources = db.query(Source).filter(Source.name.in_(source_names)).all()
        else:
            sources = db.query(Source).filter(Source.is_active == True).all()

        if not sources:
            print("No active sources found. Run --seed first.")
            return

        total_found = 0
        total_inserted = 0
        total_skipped = 0

        for source in sources:
            start_time = time.time()
            print(f"\nScraping: {source.name} ({source.rss_url})")
            
            cat = source.category if source.category else None

            if source.scrape_type == "playwright":
                articles = scrape_with_playwright(source.rss_url, source.id, source.name, category=cat)
            else:
                articles = scrape_rss_feed(source.rss_url, source.id, source.name, category=cat)
                if not articles:
                    print(f"  RSS returned 0 articles, trying Playwright fallback...")
                    articles = scrape_with_playwright(source.rss_url, source.id, source.name, category=cat)
            
            if limit:
                articles = articles[:limit]
            
            found = len(articles)
            inserted = 0
            skipped = 0
            errors = []

            seen_urls = set()
            seen_slugs = set()
            for article_data in articles:
                url = article_data.get("original_url")
                url_hash = article_data.get("url_hash")

                # Skip duplicates within this batch
                if url in seen_urls or url_hash in seen_urls:
                    skipped += 1
                    continue
                seen_urls.add(url)
                seen_urls.add(url_hash)

                # Skip duplicates already in DB
                existing = db.query(Article).filter(
                    (Article.url_hash == url_hash) |
                    (Article.original_url == url)
                ).first()

                if existing:
                    skipped += 1
                    continue

                try:
                    # Ensure slug uniqueness
                    slug = article_data.get("slug", "")
                    base_slug = slug
                    counter = 1
                    while slug in seen_slugs or db.query(Article).filter(Article.slug == slug).first():
                        slug = f"{base_slug}-{counter}"
                        counter += 1
                    article_data["slug"] = slug
                    seen_slugs.add(slug)

                    article = Article(**article_data)
                    db.add(article)
                    inserted += 1

                    # Summarize immediately if --summarize flag
                    if summarize:
                        result = summarize_article(article_data.get("title", ""), article_data.get("content_text", ""))
                        if result:
                            article.summary_ai = result["summary_ai"]
                            article.seo_title = result["seo_title"]
                            article.seo_description = result["seo_description"]

                    # Classify immediately if --classify flag
                    if classify:
                        category = get_primary_category(article_data.get("title", ""), article_data.get("content_text", ""))
                        if category:
                            article.category = category.lower()

                    # Extract tags immediately if --tags flag
                    if tags:
                        db.flush()  # Flush to get article.id for tag linking
                        extract_and_store_tags(db, article, Tag, ArticleTag)
                except Exception as e:
                    errors.append(f"Failed to insert {article_data.get('title', 'unknown')}: {str(e)}")

            duration = int(time.time() - start_time)

            try:
                db.commit()
            except Exception as e:
                db.rollback()
                errors.append(f"Batch commit failed: {str(e)}")
                inserted = 0

            log = ScrapeLog(
                source_id=source.id,
                articles_found=found,
                articles_inserted=inserted,
                articles_skipped=skipped,
                errors="\n".join(errors) if errors else None,
                duration_seconds=duration,
            )
            db.add(log)
            db.commit()

            total_found += found
            total_inserted += inserted
            total_skipped += skipped

            print(f"  Found: {found}, Inserted: {inserted}, Skipped: {skipped}, Time: {duration}s")

        print(f"\n{'='*50}")
        print(f"Total: Found={total_found}, Inserted={total_inserted}, Skipped={total_skipped}")
        
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="News Scraper CLI")
    parser.add_argument("--seed", action="store_true", help="Seed initial sources")
    parser.add_argument("--sources", nargs="+", help="Specific source names to scrape")
    parser.add_argument("--limit", type=int, help="Limit articles per source")
    parser.add_argument("--summarize", action="store_true", help="Generate AI summaries via Groq")
    parser.add_argument("--classify", action="store_true", help="Classify articles into categories via zero-shot")
    parser.add_argument("--tags", action="store_true", help="Extract keyword tags via YAKE")
    parser.add_argument("--cleanup", action="store_true", help="Archive old articles (30 days) and clean old logs")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.cleanup:
            from backend.app.lifecycle import run_cleanup
            result = run_cleanup()
            print(f"Cleanup: {result['articles_archived']} articles archived, {result['logs_deleted']} logs deleted")
        elif args.seed:
            seed_sources(db)

        if not args.cleanup and (not args.seed or args.sources):
            run_scraper(source_names=args.sources, limit=args.limit, summarize=args.summarize, classify=args.classify, tags=args.tags)
    finally:
        db.close()
