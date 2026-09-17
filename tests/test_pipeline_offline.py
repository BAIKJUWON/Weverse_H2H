"""실제 Weverse/Chrome 없이 핵심 로직(분류, 이미지 URL 선택, 중복 방지, 저장 구조)을
검증하는 오프라인 테스트. 가짜 API 응답 JSON과 가짜 브라우저 컨텍스트를 사용한다.

실행: python tests/test_pipeline_offline.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.member_registry import MemberRegistry
from src.collectors.weverse_collector import WeverseCollector
from src.database.archive_db import ArchiveDB
from src.services.archive_service import ArchiveService


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self.ok = status < 400
        self.status = status

    def body(self) -> bytes:
        return self._data


class FakeRequest:
    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str, timeout: int = 30000) -> FakeResponse:
        self.calls.append(url)
        # URL 문자열을 그대로 "이미지 바이트"처럼 사용해 서로 다른 URL은 다른 내용,
        # 같은 URL은 같은 내용(=같은 해시)이 되도록 한다.
        return FakeResponse(f"FAKE_IMAGE_BYTES::{url}".encode("utf-8"))


class FakeContext:
    def __init__(self):
        self.request = FakeRequest()


class FakePage:
    """WeverseCollector 생성자만 만족시키는 최소 더미 (실제 테스트에서는 사용 안 함)."""

    def on(self, *_args, **_kwargs):
        pass


def build_fake_api_payload():
    """Weverse artist 탭 API 응답을 흉내 낸 가짜 JSON (실제 스키마는 추정치)."""
    return {
        "data": [
            {
                "postId": "1001",
                "author": {"memberId": "member-jiwoo-001", "nickname": "JIWOO"},
                "publishedAt": "2026-09-10T10:00:00Z",
                "body": "테스트 게시물 1",
                "photos": [
                    {"thumbnailUrl": "https://img.weverse.io/thumb/1001_1.jpg",
                     "originImgUrl": "https://img.weverse.io/origin/1001_1.jpg"},
                ],
            },
            {
                "postId": "1002",
                "author": {"memberId": "official-h2h", "nickname": "Hearts2Hearts"},
                "publishedAt": "2026-09-11T11:00:00Z",
                "body": "단체 게시물",
                "photos": [
                    {"originImgUrl": "https://img.weverse.io/origin/1002_1.jpg"},
                    {"originImgUrl": "https://img.weverse.io/origin/1002_2.jpg"},
                ],
            },
            {
                "postId": "1003",
                "author": {"memberId": "unknown-999", "nickname": "GuestUser"},
                "publishedAt": "2026-09-12T12:00:00Z",
                "body": "판별 불가 게시물",
                "photos": [
                    {"originImgUrl": "https://img.weverse.io/origin/1003_1.jpg"},
                ],
            },
        ]
    }


def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="h2h_test_"))
    try:
        # members.json 사본 생성 후 고정 식별자를 미리 채워둔다 (discover 단계는 별도 테스트)
        members_src = PROJECT_ROOT / "config" / "members.json"
        with open(members_src, "r", encoding="utf-8") as f:
            members_data = json.load(f)
        for m in members_data["members"]:
            if m["name"] == "JIWOO":
                m["member_id"] = "member-jiwoo-001"
        members_data["official_account"]["member_id"] = "official-h2h"
        members_tmp_path = tmp_dir / "members.json"
        with open(members_tmp_path, "w", encoding="utf-8") as f:
            json.dump(members_data, f, ensure_ascii=False)

        registry = MemberRegistry(members_tmp_path)

        collector = WeverseCollector.__new__(WeverseCollector)  # __init__ 우회 (실제 page 불필요)
        collector.page = None
        collector.registry = registry
        collector.slug = registry.community_slug

        payload = build_fake_api_payload()
        raw_candidates = []

        def collect(node):
            from src.collectors.network_capture import walk_json
            keys = set(node.keys()) if isinstance(node, dict) else set()
            if {"postId"} & keys and ("author" in keys):
                raw_candidates.append(node)

        from src.collectors.network_capture import walk_json
        walk_json(payload, collect)

        posts = []
        for node in raw_candidates:
            post = collector._parse_post_node(node)
            assert post is not None
            posts.append(post)

        # ── 검증 1: 분류 결과 ───────────────────────────────────────
        by_id = {p.post_id: p for p in posts}
        assert by_id["1001"].member_folder == "JIWOO", by_id["1001"].member_folder
        assert by_id["1001"].category == "member"
        assert by_id["1002"].member_folder == "GROUP", by_id["1002"].member_folder
        assert by_id["1003"].member_folder == "UNKNOWN", by_id["1003"].member_folder
        print("[OK] 작성자 고정 식별자 기반 분류 (JIWOO / GROUP / UNKNOWN)")

        # ── 검증 2: 원본(썸네일 아님) 이미지 URL 선택 ─────────────────
        assert by_id["1001"].image_urls == ["https://img.weverse.io/origin/1001_1.jpg"]
        print("[OK] 썸네일이 아닌 원본 이미지 URL 선택")

        # ── 검증 3: 다운로드 + DB 중복 방지 + metadata.json ───────────
        db_path = tmp_dir / "archive.db"
        db = ArchiveDB(db_path)
        download_root = tmp_dir / "downloads"
        fake_context = FakeContext()

        service = ArchiveService(
            context=fake_context,
            collector=collector,
            db=db,
            registry=registry,
            download_root=download_root,
            retry_count=1,
            min_interval_sec=0,
        )

        from src.services.archive_service import ArchiveStats

        stats_first = ArchiveStats()
        for post in posts:
            service._process_post(post, stats_first)
        print(f"[1차 실행] new_images={stats_first.new_images} duplicates={stats_first.duplicates} errors={stats_first.errors}")
        assert stats_first.new_images == 4  # 1001:1장 + 1002:2장 + 1003:1장
        assert stats_first.duplicates == 0

        # 2차 실행 (동일 게시물 재확인) -> 전부 중복 처리되어야 함
        stats_second = ArchiveStats()
        for post in posts:
            service._process_post(post, stats_second)
        print(f"[2차 실행] new_images={stats_second.new_images} duplicates={stats_second.duplicates} errors={stats_second.errors}")
        assert stats_second.new_images == 0
        assert stats_second.duplicates == 4
        print("[OK] 동일 게시물 재확인 시 이미지 재다운로드 없이 전부 중복 처리됨")

        # 폴더 구조 확인
        jiwoo_dir = download_root / "Hearts2Hearts" / "Weverse" / "JIWOO" / "2026" / "09"
        group_dir = download_root / "Hearts2Hearts" / "Weverse" / "GROUP" / "2026" / "09"
        unknown_dir = download_root / "Hearts2Hearts" / "Weverse" / "UNKNOWN" / "2026" / "09"
        assert jiwoo_dir.exists(), jiwoo_dir
        assert group_dir.exists(), group_dir
        assert unknown_dir.exists(), unknown_dir
        print("[OK] Member/Group/Unknown 폴더 구조 생성 확인")

        # metadata.json 확인
        post_1001_dir = next(jiwoo_dir.glob("2026-09-10_1001"))
        meta = json.loads((post_1001_dir / "metadata.json").read_text(encoding="utf-8"))
        assert meta["post_id"] == "1001"
        assert meta["author"] == "JIWOO"
        assert meta["category"] == "member"
        assert meta["image_count"] == 1
        print("[OK] metadata.json 필드 확인:", meta)

        db.close()
        print("\n모든 오프라인 테스트 통과")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
