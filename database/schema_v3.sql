-- schema_v3.sql — View tracking tables for analytics
-- Run after schema_v0.sql and schema_v1.sql

-- Raw views table: one row per page view
CREATE TABLE IF NOT EXISTS article_views (
    id          SERIAL PRIMARY KEY,
    article_id  INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    viewed_at   TIMESTAMP DEFAULT NOW(),
    ip_hash     VARCHAR(16),
    ua_type     VARCHAR(10)
);
CREATE INDEX IF NOT EXISTS idx_views_article ON article_views(article_id);
CREATE INDEX IF NOT EXISTS idx_views_date    ON article_views(viewed_at DESC);

-- Daily rollup per article: fast chart queries
CREATE TABLE IF NOT EXISTS article_views_daily (
    id          SERIAL PRIMARY KEY,
    article_id  INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    view_date   DATE NOT NULL,
    view_count  INTEGER DEFAULT 0,
    UNIQUE(article_id, view_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_date ON article_views_daily(view_date DESC);

-- Site-level daily totals: one row per day for admin overview line chart
CREATE TABLE IF NOT EXISTS site_views_daily (
    view_date   DATE PRIMARY KEY,
    total_views INTEGER DEFAULT 0,
    desktop     INTEGER DEFAULT 0,
    mobile      INTEGER DEFAULT 0,
    bot         INTEGER DEFAULT 0
);
