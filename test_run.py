"""콘솔 테스트 스크립트.

요청된 검증 순서를 그대로 수행한다:
  1) Hearts2Hearts 커뮤니티 확인
  2) 멤버 고유 식별자 확인
  3) 최근 게시물 10개 분류 (POST ID / AUTHOR / IMAGES 콘솔 출력)
  4) 사진 다운로드

GUI 없이 터미널에서 바로 실행해 결과를 확인할 수 있다.
사용법: python test_run.py

주의: 이 스크립트는 실행할 때마다 Chrome을 새로 열고 끝나면 닫는다. Chrome을 완전히
껐다 켜면 Weverse 세션 쿠키가 브라우저 기본 동작으로 삭제되어 로그인이 풀릴 수 있으므로,
매번 다시 로그인해야 한다면 평소에는 GUI(main.py)를 사용하는 것이 좋다 -
GUI는 'Chrome 열기'로 연 창을 닫지 않고 계속 재사용하므로 로그인이 유지된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.browser.chrome_manager import ChromeManager  # noqa: E402
from src.collectors.member_registry import MemberRegistry  # noqa: E402
from src.collectors.weverse_collector import WeverseCollector  # noqa: E402
from src.database.archive_db import ArchiveDB  # noqa: E402
from src.services.archive_service import ArchiveService  # noqa: E402
from src.utils.logger import setup_logger  # noqa: E402

logger = setup_logger(PROJECT_ROOT / "logs")


def main() -> None:
    config_path = PROJECT_ROOT / "config.json"
    if not config_path.exists():
        config_path = PROJECT_ROOT / "config.example.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    profile_dir = PROJECT_ROOT / config.get("browser_profile", "./data/chrome_profile")
    db_path = PROJECT_ROOT / config.get("database_path", "./data/archive.db")
    download_root = Path(config.get("download_root", "./Hearts2Hearts_Archive"))
    if not download_root.is_absolute():
        download_root = PROJECT_ROOT / download_root
    limit = int(config.get("recent_post_limit", 10))

    registry = MemberRegistry(PROJECT_ROOT / config.get("members_config_path", "./config/members.json"))

    chrome = ChromeManager(profile_dir, headless=False)
    db = None
    try:
        context = chrome.launch()
        page = chrome.new_page()

        debug_dir = (PROJECT_ROOT / "data" / "api_debug") if config.get("debug_capture_api") else None
        if debug_dir:
            print(f"(디버그) 캡처된 API 응답을 {debug_dir} 에 저장합니다. selectors.py 조정 시 참고하세요.")

        # ── 로그인 확인 ──────────────────────────────────────────────
        login_debug_dir = (debug_dir / "login_check") if debug_dir else None
        logged_in = chrome.check_login_status(page, registry.community_slug, debug_dir=login_debug_dir)
        if not logged_in:
            print("\n로그인이 필요합니다. 지금 뜬 이 Chrome 창에서 직접 로그인한 뒤,")
            print("이 스크립트를 다시 실행해 주세요. (이 스크립트는 실행이 끝나면 Chrome을 닫으므로,")
            print("Weverse 세션 쿠키가 session-only 방식이면 재실행 시 다시 로그인해야 할 수 있습니다.")
            print("매번 재로그인하지 않고 이어서 쓰려면 GUI(main.py)의 'Chrome 열기' -> 창을 닫지 않고")
            print("'사진 저장 시작' 방식을 사용하세요.)")
            if login_debug_dir:
                print(f"(디버그) 지금 화면 스크린샷을 {login_debug_dir} 에 저장했습니다.\n")
            else:
                print()
            return
        collector = WeverseCollector(page, registry, debug_dir=debug_dir)

        # ── 1) 커뮤니티 확인 ─────────────────────────────────────────
        print("\n=== 1) Hearts2Hearts 커뮤니티 확인 ===")
        ok = collector.confirm_community()
        print(f"커뮤니티 확인 결과: {'성공' if ok else '실패'}")
        if not ok:
            return

        # ── 2) 멤버 고유 식별자 확인 ─────────────────────────────────
        print("\n=== 2) 멤버 고유 식별자 확인 ===")
        found = collector.discover_member_ids()
        for m in registry.members:
            status = m.get("member_id") or "(미확인)"
            print(f"  {m['name']:8s} -> {status}")
        print(f"이번 실행에서 새로 확인된 멤버 수: {len(found)}")

        # ── 3) 최근 게시물 10개 분류 + 4) 사진 다운로드 ───────────────
        print(f"\n=== 3) 최근 게시물 {limit}개 분류 / 4) 사진 다운로드 ===")
        db = ArchiveDB(db_path)
        service = ArchiveService(
            context=context,
            collector=collector,
            db=db,
            registry=registry,
            download_root=download_root,
            retry_count=int(config.get("retry_count", 3)),
            min_interval_sec=float(config.get("request_min_interval_sec", 1.5)),
        )
        stats = service.run(mode="latest", limit=limit)

        for item in stats.classified:
            print(
                f"POST ID: {item['post_id']} / AUTHOR: {item['author']} "
                f"-> {item['member_folder']} ({item['category']}) / IMAGES: {item['image_count']}"
            )

        print("\n=== 결과 요약 ===")
        print(f"새 게시물 : {stats.new_posts}")
        print(f"새 사진   : {stats.new_images}")
        print(f"중복 제외 : {stats.duplicates}")
        print(f"오류      : {stats.errors}")
        print(f"저장 위치 : {download_root}")

    finally:
        if db is not None:
            db.close()
        chrome.close()


if __name__ == "__main__":
    main()
