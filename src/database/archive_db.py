"""SQLite 기반 아카이브 DB. 게시물/이미지 중복 저장 방지를 담당한다.

중복 판단 우선순위: 1) 게시물 ID  2) 이미지 원본 URL  3) 파일 SHA-256 해시
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class ArchiveDB:
    """게시물/이미지 저장 이력을 관리하는 SQLite 래퍼."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT PRIMARY KEY,
                author TEXT,
                author_member_id TEXT,
                category TEXT,
                post_url TEXT,
                published_at TEXT,
                first_seen_at TEXT,
                last_checked_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                image_url TEXT,
                local_path TEXT,
                sha256 TEXT,
                downloaded_at TEXT,
                FOREIGN KEY (post_id) REFERENCES posts(post_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_url ON images(image_url)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256)")
        self._conn.commit()

    # ── posts ────────────────────────────────────────────────────────
    def post_exists(self, post_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM posts WHERE post_id = ?", (post_id,))
        return cur.fetchone() is not None

    def upsert_post(
        self,
        post_id: str,
        author: str,
        author_member_id: Optional[str],
        category: str,
        post_url: str,
        published_at: str,
    ) -> None:
        now = datetime.now().isoformat()
        existing = self._conn.execute(
            "SELECT first_seen_at FROM posts WHERE post_id = ?", (post_id,)
        ).fetchone()
        first_seen_at = existing["first_seen_at"] if existing else now
        self._conn.execute(
            """
            INSERT INTO posts (post_id, author, author_member_id, category, post_url,
                                published_at, first_seen_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                author=excluded.author,
                author_member_id=excluded.author_member_id,
                category=excluded.category,
                last_checked_at=excluded.last_checked_at
            """,
            (post_id, author, author_member_id, category, post_url, published_at, first_seen_at, now),
        )
        self._conn.commit()

    # ── images ───────────────────────────────────────────────────────
    def image_exists_by_url(self, image_url: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM images WHERE image_url = ?", (image_url,))
        return cur.fetchone() is not None

    def image_exists_by_hash(self, sha256: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM images WHERE sha256 = ?", (sha256,))
        return cur.fetchone() is not None

    def add_image(
        self, post_id: str, image_url: str, local_path: str, sha256: str
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO images (post_id, image_url, local_path, sha256, downloaded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (post_id, image_url, local_path, sha256, datetime.now().isoformat()),
        )
        self._conn.commit()

    def count_recent_consecutive_seen(self, post_ids_in_order: list[str]) -> int:
        """최신순으로 나열된 post_id 목록에서, 앞에서부터 연속으로 이미 DB에 존재하는 개수를 센다.
        (최신 게시물 모드에서 탐색 종료 시점 판단에 사용)"""
        count = 0
        for pid in post_ids_in_order:
            if self.post_exists(pid):
                count += 1
            else:
                break
        return count

    def close(self) -> None:
        self._conn.close()
