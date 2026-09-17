"""Weverse 내부 API(JSON) 응답을 가로채 수집하는 헬퍼.

DOM(class명 등)은 사이트 리뉴얼마다 바뀌기 쉽지만, 화면에 표시되는 데이터 자체는
브라우저가 이미 내부 API를 통해 JSON으로 받아온 것이므로 이를 직접 읽는 편이 더 안정적이다.
로그인된 사용자가 정상적으로 요청해서 받은 응답을 읽을 뿐, 별도의 인증 우회는 하지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page, Response

from config import selectors

logger = logging.getLogger("h2h_archiver")

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]+")

# 2026-09-14: Weverse가 초당 수십 회씩 원격설정/폴링 API를 호출하는 것을 실제로 확인함.
# 걸러내지 않으면 캡처 리스트가 끝없이 커지고 디버그 파일이 폭증해 앱이 멈춘 것처럼 보인다.
_MAX_CAPTURED = 500
_MAX_DEBUG_DUMPS = 40


class ApiCapture:
    """지정한 URL 힌트에 해당하는 JSON 응답 본문을 누적 저장한다.

    debug_dir을 지정하면 캡처된 JSON 응답 본문을 파일로 저장한다.
    Weverse의 실제 내부 API 구조는 비공개라 selectors.py의 필드명 추정이 빗나갈 수 있는데,
    이 파일들을 확인하면 실제 응답 구조에 맞춰 selectors.py를 빠르게 수정할 수 있다.
    주의: 쿠키/Authorization 헤더는 저장하지 않는다. 응답 "본문"(닉네임, 게시물 내용 등)만
    저장되므로 완전한 익명 데이터는 아니다 - 외부에 공유하지 않도록 주의할 것.
    """

    def __init__(self, debug_dir: Optional[Path] = None):
        self.captured: list[Any] = []
        self._seen_signatures: set[str] = set()
        self.debug_dir = debug_dir
        self._debug_counter = 0

    def attach(self, page: Page) -> None:
        page.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        try:
            url = response.url
            if any(hint in url for hint in selectors.API_URL_EXCLUDE_HINTS):
                return
            if not any(hint in url for hint in selectors.API_URL_HINTS):
                return
            if len(self.captured) >= _MAX_CAPTURED:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            if response.status >= 400:
                return
            body = response.json()
        except Exception:
            # 응답 파싱 실패는 흔한 일이므로 조용히 무시하고 다음 응답을 계속 처리한다.
            return

        signature = f"{response.url}:{len(str(body))}"
        if signature in self._seen_signatures:
            return
        self._seen_signatures.add(signature)
        self.captured.append(body)
        self._maybe_dump_debug(response.url, body)

    def _maybe_dump_debug(self, url: str, body: Any) -> None:
        if self.debug_dir is None or self._debug_counter >= _MAX_DEBUG_DUMPS:
            return
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            self._debug_counter += 1
            short_url = _SAFE_FILENAME.sub("_", url)[-80:]
            fname = f"{datetime.now():%H%M%S}_{self._debug_counter:03d}_{short_url}.json"
            with open(self.debug_dir / fname, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"API 디버그 캡처 저장 실패: {e}")

    def clear(self) -> None:
        self.captured.clear()
        self._seen_signatures.clear()


def walk_json(node: Any, on_dict) -> None:
    """JSON 트리를 재귀적으로 순회하며 각 dict 노드에 콜백을 적용한다."""
    if isinstance(node, dict):
        on_dict(node)
        for value in node.values():
            walk_json(value, on_dict)
    elif isinstance(node, list):
        for item in node:
            walk_json(item, on_dict)
