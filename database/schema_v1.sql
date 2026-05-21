-- v1 Schema Migration: Categories, Tags, SEO, Credibility

-- Enhanced sources with credibility
ALTER TABLE sources ADD COLUMN IF NOT EXISTS credibility_score SMALLINT DEFAULT 50;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS scrape_type VARCHAR(30) DEFAULT 'rss';

-- Categories table
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(80) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

-- Tags table
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL
);

-- Article-category junction
CREATE TABLE IF NOT EXISTS article_categories (
    article_id BIGINT REFERENCES articles(id) ON DELETE CASCADE,
    category_id INT REFERENCES categories(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT FALSE,
    confidence SMALLINT DEFAULT 100,
    PRIMARY KEY (article_id, category_id)
);

-- Article-tag junction
CREATE TABLE IF NOT EXISTS article_tags (
    article_id BIGINT REFERENCES articles(id) ON DELETE CASCADE,
    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, tag_id)
);

-- SEO fields on articles
ALTER TABLE articles ADD COLUMN IF NOT EXISTS seo_title VARCHAR(60);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS seo_description VARCHAR(155);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS summary_ai TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS tags TEXT[];

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_fts ON articles USING GIN(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content_text,'')));
CREATE INDEX IF NOT EXISTS idx_article_categories_article ON article_categories(article_id);
CREATE INDEX IF NOT EXISTS idx_article_categories_category ON article_categories(category_id);
CREATE INDEX IF NOT EXISTS idx_article_tags_article ON article_tags(article_id);
CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags(tag_id);

-- Seed default categories
INSERT INTO categories (slug, name) VALUES
    ('world', 'World'),
    ('politics', 'Politics'),
    ('tech', 'Technology'),
    ('business', 'Business'),
    ('science', 'Science'),
    ('health', 'Health'),
    ('sports', 'Sports'),
    ('entertainment', 'Entertainment')
ON CONFLICT (slug) DO NOTHING;
