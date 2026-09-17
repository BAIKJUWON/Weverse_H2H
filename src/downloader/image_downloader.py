"""이미지 다운로드 모듈.

인증이 필요한 이미지 URL이 있을 수 있으므로, requests가 아니라 Playwright의 persistent
context(context.request)를 사용해 브라우저와 동일한 쿠키/세션으로 다운로드한다.
실패 시 최대 retry_count 회 재시도하고, 그래도 실패하면 기록만 남기고 다음 이미지로 넘어간다.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext

from src.utils.checkpoint import checkpoint
from src.utils.hash import sha256_bytes

logger = logging.getLogger("h2h_archiver")


class ImageDownloadError(Exception):
    pass


def download_image(
    context: BrowserContext,
    url: str,
    dest_path: Path,
    retry_count: int = 3,
    min_interval_sec: float = 0.0,
) -> Optional[str]:
    """이미지를 dest_path에 저장하고 SHA-256 해시를 반환한다. 실패 시 None."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: Optional[Exception] = None
    for attempt in range(1, retry_count + 1):
        checkpoint(f"download_image: {dest_path.name} 시도 {attempt} 요청 전 ({url[:80]})")
        try:
            response = context.request.get(url, timeout=30000)
            checkpoint(f"download_image: {dest_path.name} 응답 수신")
            if not response.ok:
                raise ImageDownloadError(f"HTTP {response.status}")
            data = response.body()
            if not data:
                raise ImageDownloadError("빈 응답")

            digest = sha256_bytes(data)
            with open(dest_path, "wb") as f:
                f.write(data)
            checkpoint(f"download_image: {dest_path.name} 파일 쓰기 완료")

            if min_interval_sec > 0:
                time.sleep(min_interval_sec)
            return digest
        except Exception as e:
            last_error = e
            logger.warning(f"이미지 다운로드 실패 (시도 {attempt}/{retry_count}): {e}")
            time.sleep(min(2 * attempt, 5))

    logger.error(f"이미지 다운로드 최종 실패 (재시도 {retry_count}회 소진): {last_error}")
    return None
