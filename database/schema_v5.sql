-- OS Radar — Hidden Gem Discovery Engine
-- Discovered projects, score history, and run logs

CREATE TABLE IF NOT EXISTS discovered_projects (
    id               SERIAL PRIMARY KEY,
    full_name        VARCHAR UNIQUE NOT NULL,
    repo_url         VARCHAR NOT NULL,
    owner            VARCHAR NOT NULL,
    repo             VARCHAR NOT NULL,
    description      TEXT,
    language         VARCHAR,
    license_name     VARCHAR,
    topics           TEXT[] DEFAULT '{}',
    stars            INTEGER DEFAULT 0,
    forks            INTEGER DEFAULT 0,
    open_issues      INTEGER DEFAULT 0,
    watchers         INTEGER DEFAULT 0,
    contributors     INTEGER DEFAULT 0,
    repo_created_at  TIMESTAMP,
    repo_pushed_at   TIMESTAMP,
    first_seen       TIMESTAMP DEFAULT NOW(),
    last_scored      TIMESTAMP DEFAULT NOW(),
    potential_score  FLOAT DEFAULT 0,
    score_breakdown  JSONB,
    discovery_source VARCHAR,
    consecutive_low_score_days INTEGER DEFAULT 0,
    is_active        BOOLEAN DEFAULT TRUE,
    promoted_to_watch BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_discovered_score    ON discovered_projects(potential_score DESC);
CREATE INDEX IF NOT EXISTS idx_discovered_language ON discovered_projects(language);
CREATE INDEX IF NOT EXISTS idx_discovered_active   ON discovered_projects(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_discovered_source   ON discovered_projects(discovery_source);
CREATE INDEX IF NOT EXISTS idx_discovered_seen     ON discovered_projects(first_seen DESC);

-- Score history — separate table for trend queries and sparklines
CREATE TABLE IF NOT EXISTS discovered_project_scores (
    project_id  INTEGER REFERENCES discovered_projects(id) ON DELETE CASCADE,
    scored_at   DATE NOT NULL DEFAULT CURRENT_DATE,
    score       FLOAT NOT NULL,
    stars       INTEGER,
    PRIMARY KEY (project_id, scored_at)
);

CREATE INDEX IF NOT EXISTS idx_scores_project ON discovered_project_scores(project_id);
CREATE INDEX IF NOT EXISTS idx_scores_date    ON discovered_project_scores(scored_at DESC);

-- Radar run log
CREATE TABLE IF NOT EXISTS radar_run_log (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMP DEFAULT NOW(),
    finished_at     TIMESTAMP,
    strategy        VARCHAR,
    repos_found     INTEGER DEFAULT 0,
    repos_new       INTEGER DEFAULT 0,
    repos_updated   INTEGER DEFAULT 0,
    repos_skipped   INTEGER DEFAULT 0,
    api_calls_used  INTEGER DEFAULT 0,
    status          VARCHAR DEFAULT 'running',
    error_message   TEXT
);
