import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.db.database import engine, Base
from backend.app.models import Source, Article, ScrapeLog

def setup_database():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database setup complete!")
    print(f"Tables created: sources, articles, scrape_logs")

if __name__ == "__main__":
    try:
        setup_database()
    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure PostgreSQL is running and DATABASE_URL in .env is correct.")
        sys.exit(1)
