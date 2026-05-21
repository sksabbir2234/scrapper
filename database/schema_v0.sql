-- Sources: where we scrape from
CREATE TABLE IF NOT EXISTS sources (
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
CREATE TABLE IF NOT EXISTS articles (
    id BIGSERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) ON DELETE CASCADE,
    
    -- Identity & Deduplication
    title TEXT NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    original_url VARCHAR(500) UNIQUE NOT NULL,
    url_hash CHAR(64) NOT NULL,
    
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
CREATE TABLE IF NOT EXISTS scrape_logs (
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
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_logs_source ON scrape_logs(source_id, scraped_at DESC);
