"""이미지(Image) 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ImageItem:
    """게시물에 첨부된 이미지 하나를 표현하는 데이터 클래스."""

    post_id: str
    image_url: str            # 가능한 최고 해상도(원본) 이미지 URL
    local_path: Optional[Path] = None
    sha256: Optional[str] = None
    index: int = 0             # 게시물 내 순번 (파일명에 사용)
