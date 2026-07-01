"""SQLite persistence for submissions and appeals."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "provenance.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            content_id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL,
            text TEXT NOT NULL,
            llm_score REAL NOT NULL,
            llm_reasoning TEXT,
            stylometric_score REAL NOT NULL,
            confidence REAL NOT NULL,
            attribution TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'classified',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL REFERENCES submissions(content_id),
            creator_reasoning TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_submission(record):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO submissions (
            content_id, creator_id, text, llm_score, llm_reasoning,
            stylometric_score, confidence, attribution, label, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["content_id"],
            record["creator_id"],
            record["text"],
            record["llm_score"],
            record["llm_reasoning"],
            record["stylometric_score"],
            record["confidence"],
            record["attribution"],
            record["label"],
            record["status"],
            record["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def get_submission(content_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM submissions WHERE content_id = ?", (content_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_under_review(content_id):
    conn = get_conn()
    conn.execute(
        "UPDATE submissions SET status = 'under_review' WHERE content_id = ?",
        (content_id,),
    )
    conn.commit()
    conn.close()


def save_appeal(content_id, creator_reasoning, timestamp):
    conn = get_conn()
    conn.execute(
        "INSERT INTO appeals (content_id, creator_reasoning, timestamp) VALUES (?, ?, ?)",
        (content_id, creator_reasoning, timestamp),
    )
    conn.commit()
    conn.close()


def get_log_entries(limit=50):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.*, a.creator_reasoning AS appeal_reasoning, a.timestamp AS appeal_timestamp
        FROM submissions s
        LEFT JOIN appeals a ON a.content_id = s.content_id
        ORDER BY s.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    entries = []
    for row in rows:
        row = dict(row)
        entries.append(
            {
                "content_id": row["content_id"],
                "creator_id": row["creator_id"],
                "timestamp": row["created_at"],
                "attribution": row["attribution"],
                "confidence": row["confidence"],
                "llm_score": row["llm_score"],
                "stylometric_score": row["stylometric_score"],
                "status": row["status"],
                "appeal_reasoning": row["appeal_reasoning"],
                "appeal_timestamp": row["appeal_timestamp"],
            }
        )
    return entries
