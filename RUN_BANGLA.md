# নিউজ অ্যাগ্রিগেটর চালানোর সম্পূর্ণ গাইড

## ধাপ ১: PostgreSQL ডাটাবেস চালু করুন

PowerShell এডমিন মোডে খুলুন এবং লিখুন:

```powershell
Start-Service postgresql-x64-18
```

চেক করতে চাইলে:

```powershell
Get-Service postgresql*
```

## ধাপ ২: সার্ভার চালু করুন

টার্মিনাল খুলুন এবং এই কমান্ডগুলো দিন:

```bash
cd "D:\cse code\scrapper\backend"
python -m uvicorn app.main:app --reload --port 8000
```

সফল হলে দেখাবে:
```
INFO: Uvicorn running on http://127.0.0.1:8000
```

ব্রাউজারে খুলুন: **http://127.0.0.1:8000**

## ধাপ ৩: সোর্স ডাটাবেসে যোগ করুন (প্রথমবার)

নতুন টার্মিনাল খুলুন:

```bash
cd "D:\cse code\scrapper"
python scripts/run_scraper.py --seed
```

এটি `config/sources.yaml` থেকে সোর্সগুলো (BBC, Al Jazeera, TechCrunch) ডাটাবেসে যোগ করবে।

## ধাপ ৪: নিউজ স্ক্র্যাপ করুন

```bash
python scripts/run_scraper.py
```

AI সামারি ও ক্যাটাগরি ক্লাসিফিকেশন সহ স্ক্র্যাপ করতে:

```bash
python scripts/run_scraper.py --summarize --classify
```

শুধু নির্দিষ্ট সোর্স স্ক্র্যাপ করতে:

```bash
python scripts/run_scraper.py --sources "BBC News" "TechCrunch" --limit 10
```

## ধাপ ৫: ওয়েবসাইট দেখুন

ব্রাউজারে এই লিঙ্কগুলো খুলুন:

| লিঙ্ক | কী আছে |
|-------|---------|
| http://127.0.0.1:8000/ | হোমপেজ (সর্বশেষ ৫০টি নিউজ) |
| http://127.0.0.1:8000/articles | সব নিউজ (পেজিনেটেড) |
| http://127.0.0.1:8000/categories | ক্যাটাগরি দেখুন |
| http://127.0.0.1:8000/trending | ট্রেন্ডিং নিউজ |
| http://127.0.0.1:8000/search | সার্চ করুন |
| http://127.0.0.1:8000/admin | অ্যাডমিন প্যানেল |

---

## দৈনিক রক্ষণাবেক্ষণ

### প্রতিদিন সকালে

সার্ভার চালু থাকলে কিছু করতে হবে না। স্কেজুলার প্রতি ৩০ মিনিটে অটো স্ক্র্যাপ করবে।

### ম্যানুয়ালি স্ক্র্যাপ চাইলে

```bash
cd "D:\cse code\scrapper"
python scripts/run_scraper.py
```

### নতুন সোর্স যোগ করতে চাইলে

**পদ্ধতি ১: API দিয়ে (সার্ভার বন্ধ না করে)**

```bash
curl -X POST http://127.0.0.1:8000/admin/sources -H "Content-Type: application/json" -d "{\"name\":\"Reuters\",\"domain\":\"reuters.com\",\"rss_url\":\"https://www.reuters.com/rssfeed/worldNews\",\"category\":\"world\",\"country_code\":\"US\",\"credibility_score\":95}"
```

**পদ্ধতি ২: YAML ফাইল এডিট করে (একসাথে অনেক সোর্স)**

১. `config/sources.yaml` ফাইল খুলুন
২. নতুন সোর্স যোগ করুন:

```yaml
  - name: "Reuters"
    domain: "reuters.com"
    rss: "https://www.reuters.com/rssfeed/worldNews"
    category: "world"
    country: "US"
    credibility_score: 95
    scrape_interval_min: 15
```

৩. সিড চালান:

```bash
python scripts/run_scraper.py --seed
```

### সোর্স বন্ধ/চালু করতে

ব্রাউজারে যান: http://127.0.0.1:8000/admin

সেখানে প্রতিটি সোর্সের পাশে Toggle বাটন আছে।

### অবিলম্বে স্ক্র্যাপ চালাতে

```bash
curl -X POST http://127.0.0.1:8000/admin/scrape/trigger
```

---

## Groq API কী সেটআপ (AI সামারির জন্য)

১. যান: https://console.groq.com
২. ফ্রি অ্যাকাউন্ট বানান
৩. API কী কপি করুন
৪. `.env` ফাইলে যোগ করুন:

```
GROQ_API_KEY=gsk_আপনার_কী_এখানে
```

এরপর `--summarize` ফ্ল্যাগ ব্যবহার করলে প্রতিটি নিউজের AI সামারি তৈরি হবে।

---

## সমস্যা সমাধান

### সমস্যা: Port 8000 ব্যস্ত আছে

```bash
# পুরনো প্রসেস বন্ধ করুন
taskkill /PID <pid> /F

# অথবা অন্য পোর্ট ব্যবহার করুন
python -m uvicorn app.main:app --reload --port 8080
```

### সমস্যা: ডাটাবেস কানেকশন এরর

PowerShell এডমিন মোডে:

```powershell
Start-Service postgresql-x64-18
```

### সমস্যা: "Table already defined" এরর

পুরনো Python প্রসেস বন্ধ করুন:

```powershell
Get-Process python | Stop-Process -Force
```

### সমস্যা: কোনো নিউজ পাচ্ছে না

```bash
# প্রথমে সিড চালান
python scripts/run_scraper.py --seed

# তারপর স্ক্র্যাপ করুন
python scripts/run_scraper.py
```

---

## সার্ভার বন্ধ করতে

সার্ভার চালু থাকা টার্মিনালে `Ctrl+C` চাপুন।

---

## সব কমান্ডের সারসংক্ষেপ

| কাজ | কমান্ড |
|-----|--------|
| সার্ভার চালু | `cd "D:\cse code\scrapper\backend"` তারপর `python -m uvicorn app.main:app --reload --port 8000` |
| সোর্স সিড | `python scripts/run_scraper.py --seed` |
| স্ক্র্যাপ | `python scripts/run_scraper.py` |
| স্ক্র্যাপ + AI | `python scripts/run_scraper.py --summarize --classify` |
| নির্দিষ্ট সোর্স | `python scripts/run_scraper.py --sources "BBC News"` |
| সার্ভার বন্ধ | `Ctrl+C` |
