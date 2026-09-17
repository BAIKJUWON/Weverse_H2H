"""경로 관련 유틸리티. pathlib 기반으로 작성하여 로컬 드라이브, 네트워크 드라이브(Z:\\),
UNC 경로(\\\\NAS\\...) 어디에도 동일하게 동작하도록 한다 (향후 시놀로지 NAS 연동 대비)."""
from __future__ import annotations

import re
from pathlib import Path

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Windows 파일/폴더명으로 사용할 수 없는 문자를 제거하고 길이를 제한한다."""
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    if not cleaned:
        cleaned = "UNKNOWN"
    return cleaned[:max_len]


def ensure_dir(path: Path) -> Path:
    """디렉터리가 없으면 생성하고 경로를 반환한다."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def member_dir(download_root: Path, member_folder: str) -> Path:
    """멤버(또는 GROUP/UNKNOWN) 폴더 경로를 반환한다.

    구조: <download_root>/Hearts2Hearts/Weverse/<MEMBER>
    """
    return download_root / "Hearts2Hearts" / "Weverse" / sanitize_filename(member_folder)


def post_dir(member_folder_path: Path, published_at, post_id: str) -> Path:
    """게시물 단위 폴더 경로: <member>/<YYYY>/<MM>/<YYYY-MM-DD>_<POSTID>"""
    year = f"{published_at.year:04d}"
    month = f"{published_at.month:02d}"
    day_folder = f"{published_at:%Y-%m-%d}_{sanitize_filename(post_id)}"
    return member_folder_path / year / month / day_folder
