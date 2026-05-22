import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Date, ForeignKey, Index, SmallInteger, Float, JSON, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    domain = Column(String(100), nullable=False)
    rss_url = Column(String(500), unique=True, nullable=False)
    category = Column(String(50))
    country_code = Column(String(2))
    is_active = Column(Boolean, default=True)
    scrape_interval_min = Column(Integer, default=30)
    credibility_score = Column(SmallInteger, default=50)
    scrape_type = Column(String(30), default="rss")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    articles = relationship("Article", back_populates="source")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(80), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)

    article_categories = relationship("ArticleCategory", back_populates="category")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False)

    article_tags = relationship("ArticleTag", back_populates="tag")


class ArticleCategory(Base):
    __tablename__ = "article_categories"

    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, default=False)
    confidence = Column(SmallInteger, default=100)

    article = relationship("Article", back_populates="article_categories")
    category = relationship("Category", back_populates="article_categories")


class ArticleTag(Base):
    __tablename__ = "article_tags"

    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    article = relationship("Article", back_populates="article_tags")
    tag = relationship("Tag", back_populates="article_tags")


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(Text, nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    original_url = Column(String(1000), unique=True, nullable=False)
    url_hash = Column(String(64), nullable=False)
    content_text = Column(Text)
    author = Column(String(150))
    published_at = Column(DateTime(timezone=True))
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    language = Column(String(2), default="en")
    category = Column(String(50))
    view_count = Column(Integer, default=0)
    seo_title = Column(String(60))
    seo_description = Column(String(155))
    summary_ai = Column(Text)
    image_url = Column(String(1000))
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    tags = None  # TEXT[] column - handled by raw SQL if needed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("Source", back_populates="articles")
    article_categories = relationship("ArticleCategory", back_populates="article")
    article_tags = relationship("ArticleTag", back_populates="article")

    __table_args__ = (
        Index("idx_articles_fts", "title", "content_text"),
    )


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    articles_found = Column(Integer, default=0)
    articles_inserted = Column(Integer, default=0)
    articles_skipped = Column(Integer, default=0)
    errors = Column(Text)
    duration_seconds = Column(Integer)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())


class GithubRepo(Base):
    __tablename__ = "github_repos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner = Column(String(100), nullable=False)
    repo = Column(String(100), nullable=False)
    label = Column(String(200))
    full_name = Column(String(200), unique=True, nullable=False)  # owner/repo
    repo_url = Column(String(500))
    description = Column(Text)
    homepage = Column(String(500))
    language = Column(String(50))
    license = Column(String(50))
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    open_issues = Column(Integer, default=0)
    watchers = Column(Integer, default=0)
    category = Column(String(50))  # llm, agent, infra, vision, data, tooling
    tags = Column(String(300))  # comma-separated
    trending_score = Column(Float, default=0.0)
    is_archived = Column(Boolean, default=False)
    stats_updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    updates = relationship("GithubUpdate", back_populates="repo_obj")
    snapshots = relationship("GithubRepoSnapshot", back_populates="repo_obj")


class GithubRepoSnapshot(Base):
    __tablename__ = "github_repo_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("github_repos.id"), nullable=False)
    stars = Column(Integer)
    forks = Column(Integer)
    open_issues = Column(Integer)
    watchers = Column(Integer)
    snapshot_date = Column(Date, nullable=False)

    repo_obj = relationship("GithubRepo", back_populates="snapshots")

    __table_args__ = (
        Index("idx_snapshot_repo_date", "repo_id", "snapshot_date", unique=True),
    )


class GithubUpdate(Base):
    __tablename__ = "github_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("github_repos.id"), nullable=True)
    repo_name = Column(String(200), nullable=False)
    repo_url = Column(String(1000), nullable=False)
    update_type = Column(String(30), nullable=False)  # release, commit, pr
    title = Column(Text, nullable=False)
    body = Column(Text)
    external_url = Column(String(1000), nullable=False)
    url_hash = Column(String(64), unique=True, nullable=False)
    is_breaking = Column(Boolean, default=False)
    label = Column(String(200))
    published_at = Column(DateTime(timezone=True))
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    stars = Column(Integer)
    language = Column(String(50))

    repo_obj = relationship("GithubRepo", back_populates="updates")


class GithubWeeklyDigest(Base):
    __tablename__ = "github_weekly_digests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, unique=True, nullable=False)
    week_end = Column(Date, nullable=False)
    total_releases = Column(Integer, default=0)
    total_commits = Column(Integer, default=0)
    total_prs = Column(Integer, default=0)
    breaking_changes = Column(Integer, default=0)
    top_repos = Column(Text)  # JSON
    summary_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GithubScrapeLog(Base):
    __tablename__ = "github_scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repos_scraped = Column(Integer, default=0)
    updates_found = Column(Integer, default=0)
    updates_inserted = Column(Integer, default=0)
    repos_updated = Column(Integer, default=0)
    errors = Column(Text)
    duration_seconds = Column(Integer)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())


class FinanceResource(Base):
    __tablename__ = "finance_resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    url = Column(String(500))
    resource_type = Column(String(50))  # book, course, article, video, tool
    level = Column(String(20))  # beginner, intermediate, advanced
    cost_level = Column(String(20), default="any")  # zero_cost, low_cost, any
    topic = Column(String(50))
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FinanceQuizQuestion(Base):
    __tablename__ = "finance_quiz_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    option_a = Column(String(300), nullable=False)
    option_b = Column(String(300), nullable=False)
    option_c = Column(String(300), nullable=False)
    option_d = Column(String(300), nullable=False)
    correct_answer = Column(String(1), nullable=False)  # A, B, C, D
    explanation = Column(Text)
    difficulty = Column(String(20), default="beginner")
    topic = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PromptPattern(Base):
    __tablename__ = "prompt_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    category = Column(String(50))  # coding, writing, analysis, creative, system
    pattern_text = Column(Text, nullable=False)
    example_input = Column(Text)
    example_output = Column(Text)
    tips = Column(Text)
    difficulty = Column(String(20), default="intermediate")
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIModelCard(Base):
    __tablename__ = "ai_model_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    provider = Column(String(100))
    model_type = Column(String(50))  # chat, code, vision, embedding
    context_window = Column(Integer)
    pricing_note = Column(String(200))
    strengths = Column(Text)
    weaknesses = Column(Text)
    best_for = Column(Text)
    api_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class AITool(Base):
    __tablename__ = "ai_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500))
    category = Column(String(50))  # code, writing, image, research, productivity
    description = Column(Text)
    is_tool_of_week = Column(Boolean, default=False)
    tool_of_week_date = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AITip(Base):
    __tablename__ = "ai_tips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50))  # prompting, workflow, tool, news
    likes = Column(Integer, default=0)
    is_featured = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OSSAlternative(Base):
    __tablename__ = "oss_alternatives"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(300), unique=True, nullable=False)
    oss_name = Column(String(200), nullable=False)
    oss_github = Column(String(200))  # owner/repo
    oss_url = Column(String(500))
    oss_description = Column(Text)
    paid_name = Column(String(200), nullable=False)
    paid_url = Column(String(500))
    paid_price_hint = Column(String(200))
    category = Column(String(50), nullable=False, index=True)
    subcategory = Column(String(50))
    tags = Column(Text)  # comma-separated
    why_better = Column(Text)
    quick_tip = Column(Text)
    difficulty = Column(String(20))  # easy, medium, advanced
    self_hostable = Column(Boolean, default=True)
    has_free_tier = Column(Boolean, default=True)
    gh_stars = Column(Integer, default=0)
    gh_forks = Column(Integer, default=0)
    gh_open_issues = Column(Integer, default=0)
    gh_last_push = Column(DateTime(timezone=True))
    gh_language = Column(String(50))
    gh_license = Column(String(50))
    stats_updated_at = Column(DateTime(timezone=True))
    featured = Column(Boolean, default=False)
    upvotes = Column(Integer, default=0)
    views = Column(Integer, default=0)
    added_by = Column(String(20), default="seed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArticleView(Base):
    __tablename__ = "article_views"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    viewed_at = Column(DateTime, default=datetime.utcnow)
    ip_hash = Column(String(16))
    ua_type = Column(String(10))


class ArticleViewDaily(Base):
    __tablename__ = "article_views_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    view_date = Column(Date)
    view_count = Column(Integer, default=0)


class SiteViewDaily(Base):
    __tablename__ = "site_views_daily"

    view_date = Column(Date, primary_key=True)
    total_views = Column(Integer, default=0)
    desktop = Column(Integer, default=0)
    mobile = Column(Integer, default=0)
    bot = Column(Integer, default=0)


class ArticleSEO(Base):
    __tablename__ = "article_seo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), unique=True)
    seo_title = Column(String(70))
    seo_description = Column(String(165))
    seo_keywords = Column(Text)  # stored as JSON array string
    canonical_url = Column(String)
    og_title = Column(String(95))
    og_description = Column(String(200))
    og_image_url = Column(String)
    schema_json = Column(JSON)
    reading_time = Column(Integer)
    seo_score = Column(Integer, default=0)
    score_breakdown = Column(JSON)
    issues = Column(JSON)
    generated_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    generation_method = Column(String, default="rule_based")

    article = relationship("Article", backref="seo")


class PromptLibrary(Base):
    __tablename__ = "prompt_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    prompt_text = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    subcategory = Column(String)
    tags = Column(Text)  # stored as JSON array string
    use_case = Column(Text)
    model_hint = Column(String, default="any")
    difficulty = Column(String, default="beginner")
    upvotes = Column(Integer, default=0)
    copy_count = Column(Integer, default=0)
    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DiscoveredProject(Base):
    __tablename__ = "discovered_projects"

    id               = Column(Integer, primary_key=True)
    full_name        = Column(String, unique=True, nullable=False)
    repo_url         = Column(String, nullable=False)
    owner            = Column(String, nullable=False)
    repo             = Column(String, nullable=False)
    description      = Column(Text)
    language         = Column(String)
    license_name     = Column(String)
    topics           = Column(ARRAY(String), default=[])
    stars            = Column(Integer, default=0)
    forks            = Column(Integer, default=0)
    open_issues      = Column(Integer, default=0)
    watchers         = Column(Integer, default=0)
    contributors     = Column(Integer, default=0)
    repo_created_at  = Column(DateTime)
    repo_pushed_at   = Column(DateTime)
    first_seen       = Column(DateTime, default=datetime.utcnow)
    last_scored      = Column(DateTime, default=datetime.utcnow)
    potential_score  = Column(Float, default=0)
    score_breakdown  = Column(JSON)
    discovery_source = Column(String)
    consecutive_low_score_days = Column(Integer, default=0)
    is_active        = Column(Boolean, default=True)
    promoted_to_watch = Column(Boolean, default=False)

    score_history = relationship("DiscoveredProjectScore", back_populates="project",
                                 cascade="all, delete-orphan")


class DiscoveredProjectScore(Base):
    __tablename__ = "discovered_project_scores"

    project_id = Column(Integer, ForeignKey("discovered_projects.id",
                        ondelete="CASCADE"), primary_key=True)
    scored_at  = Column(Date, primary_key=True, default=date.today)
    score      = Column(Float, nullable=False)
    stars      = Column(Integer)

    project = relationship("DiscoveredProject", back_populates="score_history")


class RadarRunLog(Base):
    __tablename__ = "radar_run_log"

    id             = Column(Integer, primary_key=True)
    started_at     = Column(DateTime, default=datetime.utcnow)
    finished_at    = Column(DateTime)
    strategy       = Column(String)
    repos_found    = Column(Integer, default=0)
    repos_new      = Column(Integer, default=0)
    repos_updated  = Column(Integer, default=0)
    repos_skipped  = Column(Integer, default=0)
    api_calls_used = Column(Integer, default=0)
    status         = Column(String, default="running")
    error_message  = Column(Text)
