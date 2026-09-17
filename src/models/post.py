"""게시물(Post) 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    """Weverse 게시물 하나를 표현하는 데이터 클래스."""

    post_id: str
    post_url: str
    author_name: str                 # 화면에 표시된 작성자 닉네임 (참고용)
    author_member_id: Optional[str]  # 작성자의 고정 식별자 (판별 기준)
    published_at: datetime
    content: str = ""
    category: str = "unknown"        # "member" | "group" | "unknown"
    member_folder: str = "UNKNOWN"   # 저장될 폴더명 (CARMEN, JIWOO, ..., GROUP, UNKNOWN)
    image_urls: list[str] = field(default_factory=list)
