"""Weverse 파싱 핵심 로직.

- Hearts2Hearts 커뮤니티 콘텐츠만 다룬다 (다른 아티스트 커뮤니티는 절대 접근하지 않는다).
- 사이트 구조 변경에 대응하기 쉽도록 selector/필드명은 config/selectors.py 에서만 가져온다.
- 게시물 하나의 파싱이 실패해도 전체 작업이 멈추지 않도록 개별 try/except 로 감싼다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page

from config import selectors
from src.collectors.member_registry import MemberRegistry
from src.collectors.network_capture import ApiCapture, walk_json
from src.models.post import Post
from src.utils.checkpoint import checkpoint

logger = logging.getLogger("h2h_archiver")


class WeverseCollector:
    def __init__(self, page: Page, registry: MemberRegistry, debug_dir: Optional[Path] = None):
        self.page = page
        self.registry = registry
        self.slug = registry.community_slug
        self.api_capture = ApiCapture(debug_dir=debug_dir)
        self.api_capture.attach(page)

    # ── 1) 커뮤니티 확인 ─────────────────────────────────────────────
    def confirm_community(self) -> bool:
        """Hearts2Hearts 커뮤니티 페이지가 맞는지 확인한다. 다른 아티스트 커뮤니티는 절대 열지 않는다."""
        url = selectors.community_url(self.slug)
        logger.info(f"Hearts2Hearts 커뮤니티 접속 시도: {url}")
        checkpoint(f"confirm_community: goto({url}) 호출 전")
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        checkpoint("confirm_community: goto 완료")
        self.page.wait_for_timeout(1500)
        checkpoint("confirm_community: wait_for_timeout 완료")

        current_url = self.page.url
        if self.slug not in current_url:
            logger.error(f"예상치 못한 URL로 이동됨: {current_url} (Hearts2Hearts 커뮤니티가 아닐 수 있음)")
            return False

        title = ""
        try:
            title = self.page.title()
        except Exception:
            pass
        logger.info(f"Hearts2Hearts 커뮤니티 접속 확인 (title='{title}')")
        return True

    # ── 2) 멤버 고유 식별자 확인 ─────────────────────────────────────
    def discover_member_ids(self) -> dict[str, Optional[str]]:
        """멤버 탭에서 각 아티스트의 고정 식별자(memberId)를 1회성으로 수집해 registry에 채운다.

        최초 매핑 단계에서만 화면 닉네임을 사용해 실제 인물과 계정을 연결한다.
        이후 게시물 분류는 여기서 저장된 member_id만 사용한다 (닉네임 재사용 안 함).
        """
        self.api_capture.clear()
        url = selectors.community_members_tab_url(self.slug)
        logger.info(f"멤버 탭 접속: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(3000)
        except Exception as e:
            logger.error(f"멤버 탭 접속 실패: {e}")
            return {}

        found: dict[str, str] = {}
        alias_lookup = self._build_alias_lookup()

        # 1순위: artistOfficialProfile (공식 프로필) - 화면 닉네임보다 신뢰도가 높은
        # 정식 이름(officialName)과 고정 memberId가 함께 들어있는 출처.
        official_candidates: list[dict] = []

        def collect_official(node: dict) -> None:
            if selectors.OFFICIAL_PROFILE_OBJECT_KEY in node and "memberId" in node:
                official_candidates.append(node)

        for payload in self.api_capture.captured:
            try:
                walk_json(payload, collect_official)
            except Exception:
                continue

        for node in official_candidates:
            member_id = node.get("memberId")
            profile = node.get(selectors.OFFICIAL_PROFILE_OBJECT_KEY)
            if not member_id or not isinstance(profile, dict):
                continue
            official_name = _first_present(profile, selectors.OFFICIAL_NAME_KEYS)
            if not official_name:
                continue
            member_name = alias_lookup.get(str(official_name).strip().upper())
            if member_name and member_name not in found:
                found[member_name] = str(member_id)
                logger.info(f"[공식 프로필] 멤버 식별자 발견: {member_name} -> {member_id}")

        # 2순위: 일반 작성자 정보(네트워크 응답)에서 멤버 후보 탐색 (보조)
        if len(found) < len(self.registry.members):
            candidates: list[dict] = []

            def collect(node: dict) -> None:
                keys = set(node.keys())
                if keys & set(selectors.AUTHOR_NAME_KEYS) and keys & set(selectors.AUTHOR_ID_KEYS):
                    candidates.append(node)

            for payload in self.api_capture.captured:
                try:
                    walk_json(payload, collect)
                except Exception:
                    continue

            for node in candidates:
                name_val = _first_present(node, selectors.AUTHOR_NAME_KEYS)
                id_val = _first_present(node, selectors.AUTHOR_ID_KEYS)
                if not name_val or not id_val:
                    continue
                member_name = alias_lookup.get(str(name_val).strip().upper())
                if member_name and member_name not in found:
                    found[member_name] = str(id_val)
                    logger.info(f"[네트워크 응답] 멤버 식별자 발견: {member_name} -> {id_val}")

        # 3순위 (fallback): DOM에서 프로필 링크 후보 탐색
        if len(found) < len(self.registry.members):
            self._discover_member_ids_from_dom(found, alias_lookup)

        # registry에 반영 + 저장
        for name, member_id in found.items():
            self.registry.set_member_id(name, member_id)
        if found:
            self.registry.save()

        unresolved = self.registry.unresolved_members()
        if unresolved:
            logger.warning(
                f"고정 식별자를 확인하지 못한 멤버: {unresolved} "
                f"(해당 멤버 게시물은 작성자 판별 시 UNKNOWN으로 분류될 수 있습니다)"
            )
        return found

    def _discover_member_ids_from_dom(self, found: dict, alias_lookup: dict[str, str]) -> None:
        try:
            links = self.page.locator("a[href*='/artist']").all()
        except Exception:
            links = []
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                text = (link.inner_text(timeout=500) or "").strip()
            except Exception:
                continue
            if not text:
                continue
            member_name = alias_lookup.get(text.strip().upper())
            if not member_name or member_name in found:
                continue
            member_id = _extract_id_from_href(href)
            if member_id:
                found[member_name] = member_id
                logger.info(f"[DOM] 멤버 식별자 발견: {member_name} -> {member_id} ({href})")

    def _build_alias_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for m in self.registry.members:
            for alias in m.get("aliases", []):
                lookup[alias.strip().upper()] = m["name"]
        return lookup

    # ── 3) 최근 게시물 목록 및 작성자/이미지 추출 ─────────────────────
    def fetch_recent_posts(self, limit: int = 10) -> list[Post]:
        self.api_capture.clear()
        url = selectors.community_artist_tab_url(self.slug)
        logger.info(f"아티스트 탭(게시물 목록) 접속: {url}")
        checkpoint(f"fetch_recent_posts: goto({url}) 호출 전")
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        checkpoint("fetch_recent_posts: goto 완료")
        self.page.wait_for_timeout(2000)

        # SPA 특성상 추가 로딩을 위해 짧게 스크롤 (하드코딩 sleep 남발 방지: 최소 횟수만)
        for i in range(3):
            checkpoint(f"fetch_recent_posts: 스크롤 {i + 1}/3 호출 전")
            try:
                self.page.mouse.wheel(0, 1800)
            except Exception as e:
                logger.debug(f"스크롤 중 오류 (무시): {e}")
            self.page.wait_for_timeout(800)
            logger.debug(f"게시물 목록 스크롤 {i + 1}/3 완료")
        checkpoint("fetch_recent_posts: 스크롤 완료")

        logger.info(f"네트워크 캡처 {len(self.api_capture.captured)}건에서 게시물 후보 탐색 시작")
        raw_candidates = self._collect_post_candidates_from_network()
        logger.info(f"게시물 후보 {len(raw_candidates)}건 발견")
        checkpoint(f"fetch_recent_posts: 후보 {len(raw_candidates)}건 파싱 시작")
        posts: list[Post] = []
        seen_ids: set[str] = set()

        for node in raw_candidates:
            try:
                post = self._parse_post_node(node)
            except Exception as e:
                logger.error(f"게시물 파싱 실패 (건너뜀): {e}")
                continue
            if post is None or post.post_id in seen_ids:
                continue
            seen_ids.add(post.post_id)
            posts.append(post)

        posts.sort(key=lambda p: p.published_at, reverse=True)

        if not posts:
            logger.warning("네트워크 응답에서 게시물을 찾지 못했습니다. 게시물 구조를 인식하지 못했습니다.")

        return posts[:limit]

    def _collect_post_candidates_from_network(self) -> list[dict]:
        candidates: list[dict] = []

        def collect(node: dict) -> None:
            keys = set(node.keys())
            has_post_id = bool(keys & set(selectors.POST_ID_KEYS))
            has_author = bool(keys & set(selectors.AUTHOR_OBJECT_KEYS)) or (
                keys & set(selectors.AUTHOR_ID_KEYS) and keys & set(selectors.AUTHOR_NAME_KEYS)
            )
            if has_post_id and has_author:
                candidates.append(node)

        for payload in self.api_capture.captured:
            try:
                walk_json(payload, collect)
            except Exception:
                continue
        return candidates

    def _parse_post_node(self, node: dict) -> Optional[Post]:
        post_id_val = _first_present(node, selectors.POST_ID_KEYS)
        if post_id_val is None:
            return None
        post_id = str(post_id_val)

        # 다른 아티스트 커뮤니티 콘텐츠가 섞여 들어오는 것을 막는 안전장치.
        # 게시물에 커뮤니티 정보가 있는데 우리가 보고 있는 Hearts2Hearts(slug)와 다르면
        # 절대 처리하지 않는다 (요청사항: 다른 커뮤니티 사진은 절대 다운로드 금지).
        community_obj = node.get(selectors.POST_COMMUNITY_OBJECT_KEY)
        if isinstance(community_obj, dict):
            community_url_path = _first_present(community_obj, selectors.COMMUNITY_URL_PATH_KEYS)
            if community_url_path and str(community_url_path).lower() != self.slug.lower():
                logger.warning(
                    f"다른 커뮤니티({community_url_path})의 게시물이라 건너뜀: post_id={post_id}"
                )
                return None

        author_obj: dict[str, Any] = node
        for key in selectors.AUTHOR_OBJECT_KEYS:
            if key in node and isinstance(node[key], dict):
                author_obj = node[key]
                break

        author_id = _first_present(author_obj, selectors.AUTHOR_ID_KEYS)
        author_name = _first_present(author_obj, selectors.AUTHOR_NAME_KEYS)
        author_id_str = str(author_id) if author_id is not None else None
        author_name_str = str(author_name) if author_name is not None else "UNKNOWN"

        member_folder, category = self.registry.classify(author_id_str, author_name_str)

        published_raw = _first_present(node, selectors.PUBLISHED_AT_KEYS)
        published_at = _parse_datetime(published_raw)

        content = _first_present(node, selectors.CONTENT_TEXT_KEYS) or ""
        image_urls = _extract_image_urls(node)

        return Post(
            post_id=post_id,
            post_url=selectors.post_url(self.slug, post_id),
            author_name=author_name_str,
            author_member_id=author_id_str,
            published_at=published_at,
            content=str(content)[:2000],
            category=category,
            member_folder=member_folder,
            image_urls=image_urls,
        )


# ── 모듈 레벨 순수 함수 (parsing helper) ──────────────────────────────
def _first_present(node: dict, keys: list[str]):
    for k in keys:
        if k in node and node[k] not in (None, ""):
            return node[k]
    return None


def _parse_datetime(raw: Any) -> datetime:
    if raw is None:
        return datetime.now()
    try:
        if isinstance(raw, (int, float)):
            # 밀리초/초 단위 epoch 모두 대응
            ts = raw / 1000 if raw > 10_000_000_000 else raw
            return datetime.fromtimestamp(ts)
        if isinstance(raw, str):
            cleaned = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
    except Exception:
        pass
    return datetime.now()


def _extract_image_urls(node: dict) -> list[str]:
    photo_list = None
    for key in selectors.PHOTO_LIST_KEYS:
        if key in node and isinstance(node[key], list):
            photo_list = node[key]
            break
    if not photo_list:
        return []

    urls: list[str] = []
    for item in photo_list:
        # orderedAttachments처럼 사진/영상이 섞여 있을 수 있으므로, type이 명시되어
        # 있는데 사진이 아니면 건너뛴다 (영상 등 원치 않는 첨부 제외).
        if isinstance(item, dict) and "type" in item and item["type"] not in selectors.PHOTO_TYPE_VALUES:
            continue
        url = _pick_best_image_url(item)
        if url:
            urls.append(url)
    return urls


def _pick_best_image_url(photo: Any) -> Optional[str]:
    if isinstance(photo, str):
        return photo
    if not isinstance(photo, dict):
        return None

    # 실제 Weverse 응답은 {"type": "photo", "data": {"url": ...}} 처럼 한 겹 감싸져
    # 오는 경우가 있다 - data가 dict면 그 안쪽을 실제 이미지 정보로 본다.
    candidate = photo["data"] if isinstance(photo.get("data"), dict) else photo

    for key in selectors.IMAGE_URL_KEYS_PRIORITY:
        val = candidate.get(key)
        if isinstance(val, str) and val.startswith("http"):
            if any(hint in key.lower() for hint in selectors.THUMBNAIL_URL_HINT_KEYWORDS):
                continue
            return val

    # 우선순위 키에 없으면, 썸네일로 의심되지 않는 첫 http URL을 사용
    for key, val in candidate.items():
        if isinstance(val, str) and val.startswith("http"):
            if any(hint in key.lower() for hint in selectors.THUMBNAIL_URL_HINT_KEYWORDS):
                continue
            return val
    return None


def _extract_id_from_href(href: str) -> Optional[str]:
    # /hearts2hearts/artist/123456 또는 ?memberId=123 형태 모두 대응
    import re

    m = re.search(r"/artist/([\w-]+)", href)
    if m:
        return m.group(1)
    m = re.search(r"[?&](memberId|artistId|profileId)=([\w-]+)", href)
    if m:
        return m.group(2)
    return None
