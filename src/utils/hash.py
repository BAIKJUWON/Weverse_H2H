"""파일 SHA-256 해시 계산 유틸리티 (중복 사진 판별에 사용)."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    """바이트 데이터의 SHA-256 해시를 16진 문자열로 반환한다."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """파일을 청크 단위로 읽어 SHA-256 해시를 계산한다 (대용량 파일 대비)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
