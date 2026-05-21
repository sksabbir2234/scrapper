# Global English News Aggregator

A full-stack news scraper that aggregates global English news from RSS feeds, stores them in PostgreSQL, and displays them via a FastAPI backend with a simple HTML frontend.

## Quick Start

### 1. Start PostgreSQL

```bash
docker compose up -d
```

### 2. Setup Python Environment

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. Seed Sources & Run Scraper

```bash
cd ..
python scripts/run_scraper.py --seed
python scripts/run_scraper.py --sources "BBC News" Reuters "TechCrunch" --limit 20
```

### 4. Start the API + UI

```bash
cd backend
uvicorn app.main:app --reload
```

Visit http://localhost:8000

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes
│   │   ├── models/       # SQLAlchemy models
│   │   ├── scrapers/     # RSS scraper
│   │   └── db/           # Database connection
│   └── requirements.txt
├── frontend/
│   ├── templates/        # Jinja2 HTML templates
│   └── static/css/       # Styles
├── database/
│   └── schema_v0.sql     # PostgreSQL schema
├── scripts/
│   └── run_scraper.py    # CLI scraper
├── config/
│   └── settings.py       # App configuration
└── docker-compose.yml    # PostgreSQL setup
```

## v0 Pass/Fail Criteria

- [x] 3 sources scrape cleanly (BBC, NYT World, TechCrunch)
- [x] 50+ articles in DB with no duplicates
- [x] UI renders without errors
- [x] `/articles` and `/articles/{slug}` endpoints work
- [x] `scrape_logs` table shows successful runs
