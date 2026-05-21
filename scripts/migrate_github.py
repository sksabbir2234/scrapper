"""One-time migration: add repo_id, is_breaking, label columns to github_updates.

Run: python scripts/migrate_github.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import text
from backend.app.db.database import engine

with engine.connect() as conn:
    for sql in [
        "ALTER TABLE github_updates ADD COLUMN IF NOT EXISTS repo_id INTEGER REFERENCES github_repos(id)",
        "ALTER TABLE github_updates ADD COLUMN IF NOT EXISTS is_breaking BOOLEAN DEFAULT FALSE",
        "ALTER TABLE github_updates ADD COLUMN IF NOT EXISTS label VARCHAR(200)",
    ]:
        try:
            conn.execute(text(sql))
        except Exception as e:
            print(f"  (skip) {e}")

    # Backfill repo_id from repo_name
    conn.execute(text("""
        UPDATE github_updates gu
        SET repo_id = gr.id
        FROM github_repos gr
        WHERE gu.repo_id IS NULL AND gu.repo_name = gr.full_name
    """))
    conn.commit()

print("Migration complete.")
