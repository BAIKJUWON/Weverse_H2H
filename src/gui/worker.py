"""GUI가 멈추지 않도록 Chrome/Playwright 작업을 전담하는 백그라운드 스레드.

중요 (Playwright sync API의 제약): Playwright의 동기(sync) API는 내부적으로 greenlet
기반 디스패처를 사용하며, 이 디스패처는 `sync_playwright().start()`를 호출한 바로 그
OS 스레드에 고정된다. 다른 스레드에서 만든 Page/BrowserContext를 또 다른 스레드에서
사용하려고 하면 "cannot switch to a different thread (which happens to have exited)"
오류가 난다.

그래서 이 앱은 매 클릭마다 새 QThread를 만들어 Chrome을 열고 닫는 대신, **하나의
BrowserWorker 스레드가 앱이 켜져 있는 동안 계속 살아있으면서** 작업 큐(queue.Queue)로
"Chrome 열기", "사진 저장 시작" 요청을 순서대로 받아 처리한다. Chrome도 그 스레드 안에서
한 번만 열리고 계속 재사용되므로, Chrome을 껐다 켜지 않아도 되고(=로그인 세션 유지),
Playwright 스레드 제약도 자연히 지켜진다.
"""
from __future__ import annotations

import logging
import queue
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from config import selectors
from src.browser.chrome_manager import ChromeManager
from src.collectors.member_registry import MemberRegistry
from src.collectors.weverse_collector import WeverseCollector
from src.database.archive_db import ArchiveDB
from src.models.post import Post
from src.services.archive_service import ArchiveService
from src.utils.checkpoint import checkpoint

logger = logging.getLogger("h2h_archiver")

_STOP = object()


class BrowserWorker(QThread):
    """Chrome/Weverse 관련 작업을 전부 이 스레드 하나에서 순서대로 처리한다."""

    progress = Signal(int, int, str)           # (현재, 전체, 설명)
    login_required = Signal()                   # 로그인이 안 되어 있을 때
    finished_ok = Signal(dict)                    # 저장 작업 결과
    failed = Signal(str)                          # 에러 메시지
    chrome_opened = Signal()                       # "Chrome 열기" 작업 완료

    def __init__(self, profile_dir: Path, members_json_path: Path, community_slug: str):
        super().__init__()
        self.profile_dir = profile_dir
        self.members_json_path = members_json_path
        self.community_slug = community_slug
        self._queue: queue.Queue = queue.Queue()
        self.chrome: Optional[ChromeManager] = None  # 이 스레드 안에서만 생성/사용한다

    # ── 외부(GUI 스레드)에서 작업을 넣는 인터페이스 ───────────────────
    def submit_open_chrome(self) -> None:
        self._queue.put(("open_chrome", None))

    def submit_archive(
        self,
        db_path: Path,
        download_root: Path,
        scan_mode: str,
        recent_post_limit: int,
        retry_count: int,
        min_interval_sec: float,
        debug_dir: Optional[Path],
    ) -> None:
        self._queue.put(
            (
                "archive",
                {
                    "db_path": db_path,
                    "download_root": download_root,
                    "scan_mode": scan_mode,
                    "recent_post_limit": recent_post_limit,
                    "retry_count": retry_count,
                    "min_interval_sec": min_interval_sec,
                    "debug_dir": debug_dir,
                },
            )
        )

    def request_stop(self) -> None:
        """앱 종료 시 스레드를 정리한다. Chrome도 이 스레드 안에서 닫는다."""
        self._queue.put((_STOP, None))

    # ── 스레드 본체 ──────────────────────────────────────────────────
    def run(self) -> None:  # noqa: C901
        checkpoint("BrowserWorker.run() 시작, 큐 대기")
        while True:
            job_type, payload = self._queue.get()
            if job_type is _STOP:
                checkpoint("BrowserWorker: 정지 요청 수신")
                break
            checkpoint(f"BrowserWorker: 작업 시작 - {job_type}")
            try:
                if job_type == "open_chrome":
                    self._do_open_chrome()
                elif job_type == "archive":
                    self._do_archive(payload)
                checkpoint(f"BrowserWorker: 작업 정상 종료 - {job_type}")
            except Exception as e:
                logger.error(f"작업 중 오류 발생: {e}\n{traceback.format_exc()}")
                checkpoint(f"BrowserWorker: 작업 중 예외 발생 - {job_type}: {e}")
                self.failed.emit(str(e))

        if self.chrome is not None:
            self.chrome.close()
            self.chrome = None

    def _ensure_chrome(self) -> ChromeManager:
        if self.chrome is None or not self.chrome.is_connected():
            self.chrome = ChromeManager(self.profile_dir)
            self.chrome.launch()
        return self.chrome

    def _do_open_chrome(self) -> None:
        chrome = self._ensure_chrome()
        page = chrome.new_page()
        page.goto(selectors.community_url(self.community_slug), wait_until="domcontentloaded", timeout=30000)
        self.chrome_opened.emit()

    def _do_archive(self, payload: dict) -> None:
        chrome = self._ensure_chrome()
        page = chrome.new_page()

        registry = MemberRegistry(self.members_json_path)

        login_debug_dir = payload["debug_dir"] / "login_check" if payload["debug_dir"] else None
        logged_in = chrome.check_login_status(page, registry.community_slug, debug_dir=login_debug_dir)
        if not logged_in:
            self.login_required.emit()
            return

        db = ArchiveDB(payload["db_path"])
        try:
            collector = WeverseCollector(page, registry, debug_dir=payload["debug_dir"])
            service = ArchiveService(
                context=chrome.context,
                collector=collector,
                db=db,
                registry=registry,
                download_root=payload["download_root"],
                retry_count=payload["retry_count"],
                min_interval_sec=payload["min_interval_sec"],
            )

            def on_progress(idx: int, total: int, post: Post) -> None:
                self.progress.emit(idx, total, f"{post.member_folder} / {post.post_id}")

            stats = service.run(
                mode=payload["scan_mode"],
                limit=payload["recent_post_limit"],
                progress_cb=on_progress,
            )

            self.finished_ok.emit(
                {
                    "new_posts": stats.new_posts,
                    "new_images": stats.new_images,
                    "duplicates": stats.duplicates,
                    "errors": stats.errors,
                    "classified": stats.classified,
                }
            )
        finally:
            db.close()
