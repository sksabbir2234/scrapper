# 🗞️ Global English News Aggregator — Final Implementation Plan

> **Build Prompt & Database Design for a Global News Aggregator Platform**  
> **No Paid AI Required — Free Tools Only (Groq / HuggingFace / Ollama / Pure Scraping)**  
> **Progressive Complexity: v0 → v1 → v2**

---

## 📌 Project Overview

Build a **full-stack news scraper website** that:
- Scrapes global English news from RSS feeds and public APIs
- Stores, deduplicates, and ranks articles in PostgreSQL
- Generates SEO-friendly titles & summaries (free AI)
- Displays trending, categorized, and curated news to users
- Runs automatically via cron jobs with health monitoring

**Language**: English-only (extensible detection layer for future expansion)  
**AI Policy**: Free/Open-Source Only — Zero Paid APIs  
**Database**: PostgreSQL-only until proven insufficient  
**Last Updated**: May 2026

---

## 🎯 Progressive Development Strategy

### Philosophy
**Build v0 in 3 days → Validate flow → Layer v1 complexity → Harden for v2**

This approach:
- Avoids building infrastructure for unproven problems
- Gives visual feedback immediately
- Lets real data drive architectural decisions
- Ships something working in 72 hours

---

## 🚀 v0 Scope (3 Days) — End-to-End Flow Validation

**Goal**: Get articles flowing from RSS → DB → visible UI with zero complexity

### v0 Pass/Fail Criteria
✅ **v0 is done when**:
1. 3 sources scrape cleanly (BBC, Reuters, TechCrunch)
2. 50+ articles in DB with no obvious duplicates
3. UI renders articles without errors
4. `/articles` and `/articles/{slug}` endpoints work
5. `scrape_logs` table shows successful runs

### Day 1: Core Pipeline

#### Environment Setup
- PostgreSQL 15+ via Docker
- Python 3.11+ virtual environment
- Basic project structure

#### Database Schema (v0)

```sql
-- Sources: where we scrape from
CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    domain VARCHAR(100) NOT NULL,
    rss_url VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(50),
    country_code CHAR(2),
    is_active BOOLEAN DEFAULT true,
    scrape_interval_min INT DEFAULT 30,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Articles: core content
CREATE TABLE articles (
    id BIGSERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) ON DELETE CASCADE,
    
    -- Identity & Deduplication
    title TEXT NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    original_url VARCHAR(500) UNIQUE NOT NULL,
    url_hash CHAR(64) NOT NULL,  -- SHA256 of original_url
    
    -- Content
    content_text TEXT,
    author VARCHAR(150),
    published_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Classification
    language CHAR(2) DEFAULT 'en',
    category VARCHAR(50),
    
    -- Metrics
    view_count BIGINT DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scrape Logs: monitoring from day 1
CREATE TABLE scrape_logs (
    id BIGSERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) ON DELETE SET NULL,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    articles_found INT DEFAULT 0,
    articles_inserted INT DEFAULT 0,
    articles_skipped INT DEFAULT 0,
    errors TEXT,
    duration_seconds INT
);

-- Indexes
CREATE INDEX idx_articles_published ON articles(published_at DESC);
CREATE INDEX idx_articles_url_hash ON articles(url_hash);
CREATE INDEX idx_articles_source ON articles(source_id);
CREATE INDEX idx_logs_source ON scrape_logs(source_id, scraped_at DESC);
```

#### Scraper Implementation
- `feedparser` for RSS parsing
- SHA256 url_hash deduplication
- Basic content extraction
- Transactional DB inserts

### Day 2: Minimal API + UI

#### FastAPI Endpoints
```
GET /api/v1/articles              - list articles (paginated)
GET /api/v1/articles/{slug}       - single article
GET /api/v1/trending              - basic recency-sorted articles
```

#### Simple HTML Frontend
- Article list view
- Article detail view
- Basic search (PostgreSQL `LIKE`)
- No JavaScript framework yet

### Day 3: Validation & Iteration

#### Concrete Validation Tasks
1. Run scraper against 3 sources
2. Verify 50+ articles in DB
3. Check for duplicates (query by url_hash)
4. Test all API endpoints
5. Verify UI renders correctly
6. Document any issues for v1

---

## 📊 v0 Data Flow Diagram

```
[RSS Feeds] → feedparser → [Raw Article Dict]
                              ↓
                    [SHA256 url_hash check]
                              ↓
                    [PostgreSQL INSERT]
                              ↓
                    [FastAPI /articles]
                              ↓
                    [Simple HTML UI]
```

**Integration Points to Validate**:
1. RSS parsing reliability (encoding, missing fields)
2. URL hash collision rate
3. Content extraction quality
4. UI rendering with real data

---

## 🔧 v1 Scope (Week 2-3) — Layer Complexity on Real Problems

**Priority Order** (adjusted based on feedback):

### 1. Source YAML Config ← Enables Everything Else
```yaml
# config/sources.yaml
sources:
  - name: "BBC News"
    domain: "bbc.com"
    rss: "http://feeds.bbci.co.uk/news/rss.xml"
    category: "world"
    country: "GB"
    credibility_score: 95
    scrape_interval_min: 15
    
  - name: "Reuters"
    domain: "reuters.com"
    rss: "https://www.reuters.com/rssfeed/worldNews"
    category: "world"
    country: "US"
    credibility_score: 95
    scrape_interval_min: 15
```

### 2. Playwright Fallback ← Unblocks More Sources
- Add Playwright only for sources that fail with feedparser
- Implement stealth mode to avoid detection
- Add to existing pipeline as fallback layer

### 3. Groq Summarization ← Highest User-Visible Value
- **Groq llama3-8b as default** (free tier: 30 req/min)
- Build explicit rate limiter + queue with 30 req/min cap
- Fallback to T5-small for offline/batch processing
- Async AI queue (never block scraping on inference)

### 4. Zero-Shot Classification ← Needed for Category Pages
- Use `cross-encoder/nli-MiniLM-L2-mnli` (lightweight, ~80MB)
- Categories: World, Politics, Tech, Business, Science, Health, Education, Jobs
- Confidence scoring for each assignment
- Clear separation: zero-shot = categories, YAKE/spaCy = tags

### 5. MinHash Near-Duplicate Detection ← Only If v0 Shows Duplicates
- Implement only if v0 reveals duplicate articles slipping through
- Title similarity matching (Levenshtein + token overlap)
- Content fingerprinting for cross-source duplicates

### 6. Admin Panel ← Last (Logs Already Give Visibility)
- FastAPI + HTMX minimal admin panel
- Scrape job monitoring
- Article quality review
- Source management interface

#### v1 Database Additions

```sql
-- Enhanced sources with credibility
ALTER TABLE sources ADD COLUMN credibility_score SMALLINT DEFAULT 50;
ALTER TABLE sources ADD COLUMN scrape_type VARCHAR(30) DEFAULT 'rss';

-- Tags and categories
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(80) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE article_categories (
    article_id BIGINT REFERENCES articles(id) ON DELETE CASCADE,
    category_id INT REFERENCES categories(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    confidence SMALLINT DEFAULT 100,
    PRIMARY KEY (article_id, category_id)
);

CREATE TABLE article_tags (
    article_id BIGINT REFERENCES articles(id) ON DELETE CASCADE,
    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, tag_id)
);

-- SEO fields
ALTER TABLE articles ADD COLUMN seo_title VARCHAR(60);
ALTER TABLE articles ADD COLUMN seo_description VARCHAR(155);
ALTER TABLE articles ADD COLUMN summary_ai TEXT;
ALTER TABLE articles ADD COLUMN tags TEXT[];

-- Indexes
CREATE INDEX idx_articles_category ON articles(category);
CREATE INDEX idx_articles_fts ON articles USING GIN(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content_text,'')));
```

---

## 🏗️ v2 Scope (Week 4-6) — Production Readiness

### 1. Advanced Trending Algorithm
- Source authority weight integration
- HN-style recency decay with credibility multiplier
- **EMA smoothing**: 6h window, 0.3 decay rate
- Materialized view refresh cron (every 5 min)

```python
def calculate_trending_score(article, source_credibility):
    hours_old = (now - article.published_at).total_seconds() / 3600
    gravity = 1.5
    numerator = (article.view_count + article.share_count * 2) * source_credibility
    denominator = (hours_old + 2) ** gravity
    return numerator / denominator
```

### 2. SEO Auto-Generation
- Auto-generate: seo_title, seo_description, slug, OG tags
- Keyword density analysis and readability scoring
- JSON-LD structured data generation
- XML sitemap and RSS/Atom feed generators

### 3. Content Lifecycle Policy
- **Archive after 30 days** (move to archive table, reduce storage)
- **Demote trending after 7 days** (exclude from trending queries)
- **Soft deletes** (never hard delete, mark as `deleted_at`)
- Cleanup cron job for old scrape logs (keep 30 days)

### 4. Multi-Language Extensibility
- Language detection layer (langdetect)
- English-only enforcement for now
- Schema ready for multi-language expansion
- FTS indexes per language

### 5. Image Handling Strategy
- **Store OG image URLs only** (no local storage in v0/v1)
- **Proxy images in v2** (avoid hotlinking issues)
- Add fallback placeholder images
- Validate image URLs on scrape

### 6. Cron/Scheduler Health Check
- Every scrape cycle writes timestamp to Redis
- `/health/scraper` endpoint validates timestamp is recent
- Better Uptime (free tier) monitors health endpoint
- Dead man's switch: alert if no articles ingested in 4 hours

```python
# Health check endpoint
@app.get("/health/scraper")
def scraper_health():
    last_scrape = redis.get("last_scrape_timestamp")
    if not last_scrape or (now - last_scrape) > timedelta(hours=4):
        return {"status": "unhealthy", "message": "Scraper stalled"}
    return {"status": "healthy", "last_scrape": last_scrape}
```

### 7. Rate Limiting + API Auth
- API key authentication from day one of v2
- Rate limiting per endpoint (Redis-backed)
- Admin vs public API separation
- Request logging and abuse detection

### 8. Deployment
- **Railway PostgreSQL + Backend** (no Supabase due to 500MB limit)
- Docker-based deployment with health checks
- Structured logging and metrics
- CI/CD pipeline for automated deploys

---

## 📁 Project Folder Structure

```
global-news-scraper/
├── config/
│   ├── sources.yaml          # News sources with credibility scores
│   └── settings.py           # App configuration
├── src/
│   ├── scrapers/
│   │   ├── base.py           # Abstract Scraper class
│   │   ├── rss_scraper.py    # feedparser + httpx
│   │   └── playwright_scraper.py  # JS-heavy fallback (v1)
│   ├── ai/
│   │   ├── summarizer.py     # Groq llama3 wrapper
│   │   ├── classifier.py     # Zero-shot classification
│   │   └── keyword_extractor.py  # YAKE + spaCy
│   ├── db/
│   │   ├── models.py         # SQLAlchemy ORM classes
│   │   ├── migrations/       # Alembic migrations
│   │   └── queries.py        # Reusable DB queries
│   ├── api/
│   │   ├── routes.py         # FastAPI endpoints
│   │   ├── auth.py           # API key auth (v2)
│   │   └── admin.py          # HTMX admin panel (v1)
│   └── utils/
│       ├── dedup.py          # SHA256 + MinHash (v1)
│       ├── slugify.py
│       └── logger.py
├── frontend/
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS/JS assets
├── tests/
│   ├── test_scrapers.py
│   ├── test_dedup.py
│   └── test_api.py
├── scripts/
│   ├── run_scraper.py        # Main CLI entry point
│   └── seed_sources.py       # Load initial sources
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── DECISIONS.md              # Running decision log
└── README.md
```

---

## 📋 Key Technical Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Database** | PostgreSQL-only | JSONB handles unstructured data; avoid sync layer complexity |
| **Scraper** | feedparser → Playwright fallback | Start simple, add complexity only when needed |
| **Deduplication** | SHA256 → MinHash (v1) | Exact match first, near-duplicate only if needed |
| **AI Summarization** | Groq llama3-8b (30 req/min cap) | Best free-tier quality; explicit rate limiting |
| **Classification** | `cross-encoder/nli-MiniLM-L2-mnli` | Lightweight (~80MB), CPU-friendly, accurate |
| **Trending** | HN-style + source credibility + EMA (6h, 0.3) | Proven algorithm with credibility weighting |
| **Deployment** | Railway PostgreSQL + Backend | No 500MB limit, no inactivity pause |
| **Admin** | FastAPI + HTMX | Zero extra infrastructure, ships fast |
| **Images** | Store URLs only (v0/v1) | Avoid storage costs; proxy in v2 if needed |
| **Health Check** | Redis timestamp + `/health/scraper` | 20 lines, prevents silent failures |

---

## 📝 DECISIONS.md Template

```markdown
# Project Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-XX | PostgreSQL-only (no MongoDB) | JSONB sufficient; avoid sync layer complexity |
| 2026-05-XX | Railway over Supabase | Supabase 500MB limit + inactivity pause unsuitable for daily ingestion |
| 2026-05-XX | `cross-encoder/nli-MiniLM-L2-mnli` over `bart-large-mnli` | 80MB vs 1.6GB, CPU-friendly, similar accuracy |
| 2026-05-XX | Groq llama3 as default AI | Free tier, fast, high-quality summaries |
| 2026-05-XX | FastAPI+HTMX admin over Metabase | Zero extra infrastructure, faster to ship |
| 2026-05-XX | Store image URLs only (v0/v1) | Avoid storage costs; proxy in v2 if needed |
| 2026-05-XX | EMA 6h window, 0.3 decay | Balances recency with stability |
| 2026-05-XX | Archive after 30 days | Manage DB growth while preserving data |
```

---

## ⚠️ Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Scraping blocks | Ethical delays, User-Agent rotation, robots.txt compliance |
| Near-duplicates | SHA256 (v0) → MinHash (v1 only if needed) |
| Groq rate limits | Explicit 30 req/min queue, T5-small fallback |
| Silent scraper failures | Redis heartbeat + `/health/scraper` + Better Uptime alerts |
| DB growth | Archive after 30 days, log cleanup, partitioning (v2) |
| Legal issues | Excerpts-only public API, canonical source links |
| Over-engineering | v0→v1→v2 progression, build only what v0 proves needed |

---

## 🧪 Testing Strategy

### v0 Testing
- Manual validation of 50+ articles
- Duplicate check via url_hash query
- API endpoint testing with curl/Postman
- UI rendering verification

### v1 Testing
- Unit tests for scrapers (mocked HTTP)
- Deduplication logic tests
- AI summarization quality checks
- Classification accuracy validation

### v2 Testing
- Load testing for API endpoints
- Trending algorithm validation
- Health check endpoint testing
- Deployment smoke tests

---

## 🚀 Quick Start (v0)

```bash
# 1. Clone & setup
git clone <repo-url>
cd global-news-scraper
python -m venv venv && source venv/bin/activate  # Linux/Mac
# python -m venv venv && venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 2. Start PostgreSQL
docker run -d --name newsdb -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:15

# 3. Initialize database
psql -U postgres -h localhost -c "CREATE DATABASE newsdb;"
python -m src.db.migrations upgrade head

# 4. Seed initial sources
python scripts/seed_sources.py

# 5. Run test scrape
python scripts/run_scraper.py --sources bbc,reuters,techcrunch --limit 20

# 6. Start API + UI
uvicorn src.api.main:app --reload
# Visit http://localhost:8000
```

---

## 📈 Success Metrics

### v0 Success
- ✅ 3 sources scraping cleanly
- ✅ 50+ articles in DB
- ✅ No obvious duplicates
- ✅ UI renders without errors
- ✅ API endpoints functional

### v1 Success
- ✅ 10+ sources via YAML config
- ✅ Groq summarization working (within rate limits)
- ✅ Category pages functional
- ✅ Admin panel operational
- ✅ Playwright fallback for JS sites

### v2 Success
- ✅ Trending algorithm with credibility weighting
- ✅ SEO-optimized article pages
- ✅ Health check + alerting operational
- ✅ Production deployment on Railway
- ✅ Content lifecycle policy enforced

---

## 📚 Learning Resources

- [Scrapy Official Tutorial](https://docs.scrapy.org/en/latest/intro/tutorial.html)
- [Hugging Face Course: NLP](https://huggingface.co/learn/nlp-course)
- [PostgreSQL Full-Text Search](https://www.postgresql.org/docs/current/textsearch.html)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Legal Web Scraping Guide](https://cloro.dev/blog/website-scraping-legal/)

---

> ✨ **Engineering Mantra**:  
> *"Requirements → DFD → Schema → ERD → Test → Deploy"*  
> *"Build v0 first, then layer complexity based on real data."*  
> *"Let free AI assist, but YOU own the architecture, ethics, and maintenance."*

---

**Next Step**: Start v0 Day 1 implementation.  
**File to create first**: `database/schema_v0.sql` with the schema above.
