"""수집(collector) + 다운로드(downloader) + DB + 파일 저장을 조율하는 서비스 계층.

GUI는 이 서비스의 run()만 호출하며, Weverse 파싱 세부사항이나 DB 스키마를 알 필요가 없다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext

from src.collectors.member_registry import MemberRegistry
from src.collectors.weverse_collector import WeverseCollector
from src.database.archive_db import ArchiveDB
from src.downloader.image_downloader import download_image
from src.models.post import Post
from src.utils import paths

logger = logging.getLogger("h2h_archiver")

ProgressCallback = Callable[[int, int, Post], None]


@dataclass
class ArchiveStats:
    new_posts: int = 0
    new_images: int = 0
    duplicates: int = 0
    errors: int = 0
    classified: list[dict] = field(default_factory=list)  # 콘솔/테스트 출력용


class ArchiveService:
    def __init__(
        self,
        context: BrowserContext,
        collector: WeverseCollector,
        db: ArchiveDB,
        registry: MemberRegistry,
        download_root: Path,
        retry_count: int = 3,
        min_interval_sec: float = 1.5,
    ):
        self.context = context
        self.collector = collector
        self.db = db
        self.registry = registry
        self.download_root = download_root
        self.retry_count = retry_count
        self.min_interval_sec = min_interval_sec

    def run(
        self,
        mode: str = "latest",
        limit: int = 10,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> ArchiveStats:
        stats = ArchiveStats()

        if not self.collector.confirm_community():
            raise RuntimeError("Hearts2Hearts 커뮤니티 페이지를 확인하지 못했습니다.")

        if self.registry.unresolved_members():
            logger.info("멤버 고정 식별자 확인 시작")
            self.collector.discover_member_ids()

        posts = self._gather_posts(mode, limit)
        logger.info(f"게시물 {len(posts)}개 확인")

        total = len(posts)
        for idx, post in enumerate(posts, start=1):
            if progress_cb:
                progress_cb(idx, total, post)
            logger.info(
                f"[{idx}/{total}] {post.member_folder}/{post.post_id} 처리 시작 "
                f"(사진 {len(post.image_urls)}장)"
            )
            try:
                self._process_post(post, stats)
                stats.classified.append(
                    {
                        "post_id": post.post_id,
                        "author": post.author_name,
                        "member_folder": post.member_folder,
                        "category": post.category,
                        "image_count": len(post.image_urls),
                    }
                )
            except Exception as e:
                logger.error(f"게시물 처리 중 오류 (건너뛰고 계속 진행): post_id={post.post_id} error={e}")
                stats.errors += 1

        return stats

    # ── 탐색 범위 ────────────────────────────────────────────────────
    def _gather_posts(self, mode: str, limit: int) -> list[Post]:
        if mode == "latest":
            return self.collector.fetch_recent_posts(limit=limit)

        # 전체 아카이브 모드.
        # 주의(현재 버전의 한계): fetch_recent_posts()는 아직 "화면을 계속 스크롤해서
        # 더 과거 게시물을 추가로 불러오는" 진짜 페이지네이션을 구현하지 않았고, 매번
        # 같은 최상단 목록을 가져온다. 그래서 같은 조회를 반복하는 건 시간만 낭비되므로
        # (다운로드 시작이 늦어져 "멈춘 것처럼 보이는" 원인이 됨) 지금은 1회만 조회한다.
        # 과거 게시물까지 진짜로 훑는 것은 추후 스크롤 기반 페이지네이션 구현이 필요하다.
        all_posts: list[Post] = []
        seen_ids: set[str] = set()
        consecutive_seen = 0
        batch = self.collector.fetch_recent_posts(limit=limit * 5)
        for post in batch:
            if post.post_id in seen_ids:
                continue
            seen_ids.add(post.post_id)
            all_posts.append(post)
            consecutive_seen = consecutive_seen + 1 if self.db.post_exists(post.post_id) else 0
            if consecutive_seen >= 5:
                logger.info("이미 처리된 게시물이 연속으로 확인되어 전체 탐색을 종료합니다.")
                break
        return all_posts

    # ── 게시물 1건 처리 ──────────────────────────────────────────────
    def _process_post(self, post: Post, stats: ArchiveStats) -> None:
        is_new_post = not self.db.post_exists(post.post_id)

        member_folder_path = paths.member_dir(self.download_root, post.member_folder)
        post_folder_path = paths.post_dir(member_folder_path, post.published_at, post.post_id)

        new_images = 0
        duplicate_images = 0
        total_saved_this_post = 0

        for idx, image_url in enumerate(post.image_urls, start=1):
            if self.db.image_exists_by_url(image_url):
                duplicate_images += 1
                continue

            filename = (
                f"{post.published_at:%Y%m%d}_{paths.sanitize_filename(post.member_folder)}"
                f"_{post.post_id}_{idx:03d}{_guess_extension(image_url)}"
            )
            dest_path = post_folder_path / filename

            digest = download_image(
                self.context,
                image_url,
                dest_path,
                retry_count=self.retry_count,
                min_interval_sec=self.min_interval_sec,
            )
            if digest is None:
                stats.errors += 1
                continue

            if self.db.image_exists_by_hash(digest):
                duplicate_images += 1
                try:
                    dest_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            self.db.add_image(post.post_id, image_url, str(dest_path), digest)
            new_images += 1
            total_saved_this_post += 1

        self.db.upsert_post(
            post_id=post.post_id,
            author=post.author_name,
            author_member_id=post.author_member_id,
            category=post.category,
            post_url=post.post_url,
            published_at=post.published_at.isoformat(),
        )

        if total_saved_this_post > 0:
            self._write_metadata(post, post_folder_path, total_saved_this_post)

        stats.new_images += new_images
        stats.duplicates += duplicate_images
        if is_new_post:
            stats.new_posts += 1

        logger.info(
            f"{post.member_folder} / {post.post_id} : 새 사진 {new_images}개, 중복 제외 {duplicate_images}개"
        )

    def _write_metadata(self, post: Post, post_folder_path: Path, image_count: int) -> None:
        post_folder_path.mkdir(parents=True, exist_ok=True)
        meta = {
            "platform": "weverse",
            "artist": "Hearts2Hearts",
            "author": post.author_name,
            "author_member_id": post.author_member_id,
            "post_id": post.post_id,
            "post_url": post.post_url,
            "published_at": post.published_at.isoformat(),
            "downloaded_at": datetime.now().isoformat(),
            "image_count": image_count,
            "category": post.category,
            "members_in_photo": [],
            "content": post.content,
        }
        with open(post_folder_path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


def _guess_extension(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    valid = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    return suffix if suffix in valid else ".jpg"
