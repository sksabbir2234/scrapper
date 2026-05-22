-- schema_v4.sql — SEO engine + AI Prompt Library tables

-- SEO metadata per article (extends existing seo_title/seo_description on articles)
CREATE TABLE IF NOT EXISTS article_seo (
    id              SERIAL PRIMARY KEY,
    article_id      INTEGER UNIQUE REFERENCES articles(id) ON DELETE CASCADE,
    seo_title       VARCHAR(70),
    seo_description VARCHAR(165),
    seo_keywords    TEXT[] DEFAULT '{}',
    canonical_url   VARCHAR,
    og_title        VARCHAR(95),
    og_description  VARCHAR(200),
    og_image_url    VARCHAR,
    schema_json     JSONB,
    reading_time    INTEGER,
    seo_score       INTEGER DEFAULT 0,
    score_breakdown JSONB,
    issues          JSONB,
    generated_at    TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    generation_method VARCHAR DEFAULT 'rule_based'
);
CREATE INDEX IF NOT EXISTS idx_seo_score   ON article_seo(seo_score DESC);
CREATE INDEX IF NOT EXISTS idx_seo_article ON article_seo(article_id);

-- Sitemap generation log
CREATE TABLE IF NOT EXISTS sitemap_log (
    id            SERIAL PRIMARY KEY,
    generated_at  TIMESTAMP DEFAULT NOW(),
    article_count INTEGER,
    duration_ms   INTEGER,
    status        VARCHAR DEFAULT 'success'
);

-- AI Prompt Library
CREATE TABLE IF NOT EXISTS prompt_library (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR NOT NULL,
    prompt_text TEXT NOT NULL,
    category    VARCHAR NOT NULL,
    subcategory VARCHAR,
    tags        TEXT[] DEFAULT '{}',
    use_case    TEXT,
    model_hint  VARCHAR DEFAULT 'any',
    difficulty  VARCHAR DEFAULT 'beginner',
    upvotes     INTEGER DEFAULT 0,
    copy_count  INTEGER DEFAULT 0,
    is_featured BOOLEAN DEFAULT FALSE,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_category ON prompt_library(category);
CREATE INDEX IF NOT EXISTS idx_prompt_upvotes  ON prompt_library(upvotes DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_copies   ON prompt_library(copy_count DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_featured ON prompt_library(is_featured) WHERE is_featured = TRUE;
