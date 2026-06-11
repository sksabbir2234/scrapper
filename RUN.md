# How to Run the News Aggregator

## Prerequisites

- Python 3.11+
- PostgreSQL 18 (running on localhost:5432)
- Database: `newsdb`, User: `newsuser`, Password: `newspass`

## 1. Start PostgreSQL

```powershell
# Check if running (PowerShell as admin)
Get-Service postgresql*

# Start if needed
Get-Service postgresql*
```

## 2. Start the FastAPI Server

```bash
cd "D:\cse code\scrapper\backend"
python -m uvicorn app.main:app --reload --port 8000
```

Open in browser: **http://127.0.0.1:8000**

## 3. CLI Commands

All CLI commands run from the **project root**:

```bash
cd "D:\cse code\scrapper"
```

### Seed sources from YAML (first time setup)

```bash
python scripts/run_scraper.py --seed
```

### Scrape all active sources

```bash
python scripts/run_scraper.py
```

### Scrape with AI features (requires GROQ_API_KEY in .env)

```bash
python scripts/run_scraper.py --summarize --classify
```

### Scrape specific sources

```bash
python scripts/run_scraper.py --sources "BBC News" "TechCrunch" --limit 10
```

### All CLI flags

| Flag | Description |
|------|-------------|
| `--seed` | Sync sources from config/sources.yaml to DB |
| `--sources "Name1" "Name2"` | Scrape only these sources |
| `--limit N` | Max articles per source |
| `--summarize` | Generate AI summaries via Groq |
| `--classify` | Classify articles into categories |

## 4. Web Pages

| URL | Page |
|-----|------|
| http://127.0.0.1:8000/ | Homepage (latest 50 articles) |
| http://127.0.0.1:8000/articles | All articles (paginated) |
| http://127.0.0.1:8000/categories | Category grid |
| http://127.0.0.1:8000/trending | Trending articles |
| http://127.0.0.1:8000/search | Full-text search |
| http://127.0.0.1:8000/admin | Admin dashboard |

## 5. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /admin/sources | Add a new source (JSON body) |
| POST | /admin/sources/{id}/toggle | Enable/disable a source |
| POST | /admin/scrape/trigger | Trigger immediate scrape |
| GET | /health/scraper | Check scraper health |

### Add a source via API

```bash
curl -X POST http://127.0.0.1:8000/admin/sources \
  -H "Content-Type: application/json" \
  -d '{"name":"Reuters","domain":"reuters.com","rss_url":"https://www.reuters.com/rssfeed/worldNews","category":"world","country_code":"US","credibility_score":95}'
```

## 6. Adding/Editing Sources

### Option A: Edit YAML (bulk)

Edit `config/sources.yaml`, then run:
```bash
python scripts/run_scraper.py --seed
```

### Option B: API (single source, no restart)

```bash
curl -X POST http://127.0.0.1:8000/admin/sources -H "Content-Type: application/json" -d '{...}'
```

### Option C: Admin UI

Go to http://127.0.0.1:8000/admin and toggle sources on/off.

## 7. Environment Variables (.env)

```
DATABASE_URL=postgresql+psycopg2://newsuser:newspass@localhost:5432/newsdb
DEBUG=true
SCRAPER_USER_AGENT=NewsAggregatorBot/1.0
SCRAPE_INTERVAL_MINUTES=30
GROQ_API_KEY=gsk_your_key_here        # For AI summaries (free at console.groq.com)
```

## 8. Stop the Server

Press `Ctrl+C` in the terminal running uvicorn.

## 9. Brainrot Video Generator

Generates vertical TikTok/Shorts/Reels videos from your scraped articles.

### One-Time Setup

```bash
# Dependencies (already installed if you ran the video generator setup)
pip install moviepy pillow edge-tts anthropic

# Download gameplay video — pick ONE option:
pip install yt-dlp

# Option A: Subway Surfers
yt-dlp -f "bestvideo[height<=1080]+bestaudio/best" "YOUTUBE_URL" -o "D:\cse code\scrapper\video_generator\assets\gameplay.mp4"

# Option B: Minecraft parkour / satisfying clips (search YouTube for "minecraft parkour gameplay no commentary")
```

Font is already included at `video_generator/assets/font.ttf`.

### Add to .env

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Generate a Video

```bash
cd "D:\cse code\scrapper\cd "

# Test script only (no video rendered, fast)
python brainrot.py --dry-run

# Override story manually
python brainrot.py --story "Google just open sourced Gemini Ultra"

# Full video generation (picks best story from your API)
python brainrot.py
```

Output goes to: `D:\cse code\scrapper\videos\brainrot_YYYY-MM-DD_HH-MM.mp4`

### How It Works

1. Fetches articles from your FastAPI (`/api/articles`)
2. Scores by virality (category, keywords, source, recency)
3. Claude writes a brainrot script (30-55s, punchy sentences)
4. Edge-TTS generates voiceover with word-level timestamps
5. PIL renders word-by-word text overlay (top half)
6. MoviePy composites text + gameplay (bottom half) into 1080x1920 MP4

### Auto-Runs Daily at 8:00 AM

The scheduler in `backend/app/scheduler.py` runs `brainrot.py` automatically when the FastAPI server is running. No manual trigger needed.

### CLI Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Print script only, don't render video |
| `--story "text"` | Override the story with custom text |

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `gameplay.mp4 not found` | Download gameplay video (see setup above) |
| `font.ttf not found` | Re-download Anton font to `video_generator/assets/` |
| Video too short (<28s) | Script is too short — set ANTHROPIC_API_KEY for better scripts |
| `Lock file exists` | Delete `video_generator/.brainrot.lock` if previous job crashed |
| Video silent | Check voice_path exists before composing |

## 10. Troubleshooting

| Problem | Fix |
|---------|-----|
| Port 8000 in use | `taskkill /PID <pid> /F` or use `--port 8080` |
| DB connection error | Check PostgreSQL is running: `Get-Service postgresql*` |
| No articles found | Run `--seed` first, then scrape |
| Model already defined error | You have a stale Python process — kill it |
