import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index, SmallInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    domain = Column(String(100), nullable=False)
    rss_url = Column(String(255), unique=True, nullable=False)
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
    original_url = Column(String(500), unique=True, nullable=False)
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
    image_url = Column(String(500))
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


class GithubUpdate(Base):
    __tablename__ = "github_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_name = Column(String(200), nullable=False)
    repo_url = Column(String(500), nullable=False)
    update_type = Column(String(30), nullable=False)  # release, commit, trending
    title = Column(Text, nullable=False)
    body = Column(Text)
    external_url = Column(String(500), nullable=False)
    url_hash = Column(String(64), unique=True, nullable=False)
    published_at = Column(DateTime(timezone=True))
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    stars = Column(Integer)
    language = Column(String(50))


class FinanceResource(Base):
    __tablename__ = "finance_resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    url = Column(String(500))
    resource_type = Column(String(50))  # book, course, article, video, tool
    level = Column(String(20))  # beginner, intermediate, advanced
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
