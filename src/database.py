import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "cv_mender.db"


# ── Connection ─────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent readers + scheduler
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ─────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                id              INTEGER PRIMARY KEY DEFAULT 1,
                resume_data     TEXT,
                keywords        TEXT,
                location        TEXT,
                max_jobs        INTEGER DEFAULT 25,
                last_scraped_at TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                title            TEXT NOT NULL,
                company          TEXT NOT NULL,
                location         TEXT,
                url              TEXT UNIQUE,
                description      TEXT,
                scraped_at       TEXT DEFAULT (datetime('now')),
                status           TEXT DEFAULT 'new',
                resume_pdf       BLOB,
                cover_letter_pdf BLOB,
                generated_at     TEXT
            );
        """)


# ── Config ─────────────────────────────────────────────────────────────────────

def get_config() -> Optional[Dict]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM config WHERE id = 1").fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("resume_data"):
        d["resume_data"] = json.loads(d["resume_data"])
    return d


def save_config(
    resume_data: dict,
    keywords: str,
    location: str,
    max_jobs: int = 25,
) -> None:
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO config (id, resume_data, keywords, location, max_jobs)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                resume_data = excluded.resume_data,
                keywords    = excluded.keywords,
                location    = excluded.location,
                max_jobs    = excluded.max_jobs
            """,
            (json.dumps(resume_data), keywords, location, max_jobs),
        )


def touch_last_scraped() -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE config SET last_scraped_at = datetime('now') WHERE id = 1"
        )


# ── Jobs ───────────────────────────────────────────────────────────────────────

def insert_jobs(jobs: List[Dict]) -> int:
    """Insert new jobs, deduplicate by URL. Returns count of newly added rows."""
    new_count = 0
    with _db() as conn:
        for job in jobs:
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (title, company, location, url, description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        job["title"],
                        job["company"],
                        job.get("location", ""),
                        job.get("url", ""),
                        job.get("description", ""),
                    ),
                )
                new_count += 1
            except sqlite3.IntegrityError:
                pass  # duplicate URL — skip
    return new_count


def get_jobs(status: Optional[str] = None) -> List[Dict]:
    """
    Return jobs ordered newest-first.
      status=None      → all except 'removed'
      status='removed' → only removed jobs
      status=<other>   → filter by that status, excluding removed
    """
    with _db() as conn:
        if status == "removed":
            rows = conn.execute(
                "SELECT id, title, company, location, url, description, "
                "scraped_at, status, generated_at "
                "FROM jobs WHERE status = 'removed' ORDER BY scraped_at DESC"
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT id, title, company, location, url, description, "
                "scraped_at, status, generated_at "
                "FROM jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, company, location, url, description, "
                "scraped_at, status, generated_at "
                "FROM jobs WHERE status != 'removed' ORDER BY scraped_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    with _db() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status != 'removed' THEN 1 ELSE 0 END) AS total,
                SUM(CASE WHEN status = 'new'       THEN 1 ELSE 0 END) AS new,
                SUM(CASE WHEN status = 'generated' THEN 1 ELSE 0 END) AS generated,
                SUM(CASE WHEN status = 'applied'   THEN 1 ELSE 0 END) AS applied,
                SUM(CASE WHEN status = 'removed'   THEN 1 ELSE 0 END) AS removed
            FROM jobs
            """
        ).fetchone()
    return dict(row) if row else {"total": 0, "new": 0, "generated": 0, "applied": 0, "removed": 0}


def set_job_status(job_id: int, status: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE jobs SET status = ? WHERE id = ?", (status, job_id)
        )


def save_job_pdfs(job_id: int, resume_pdf: bytes, cover_letter_pdf: bytes) -> None:
    with _db() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET resume_pdf       = ?,
                cover_letter_pdf = ?,
                status           = 'generated',
                generated_at     = datetime('now')
            WHERE id = ?
            """,
            (resume_pdf, cover_letter_pdf, job_id),
        )


def get_job_pdfs(job_id: int) -> Dict:
    with _db() as conn:
        row = conn.execute(
            "SELECT resume_pdf, cover_letter_pdf FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else {}
