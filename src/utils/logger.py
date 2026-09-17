"""날짜별 로그 파일을 생성하고, 민감 정보가 로그에 남지 않도록 필터링하는 모듈."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

# 로그에 절대 남으면 안 되는 패턴 (쿠키 값, Authorization 헤더, 토큰 등)
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(session[_-]?id\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
]


class _SensitiveDataFilter(logging.Filter):
    """로그 레코드에서 민감 정보로 의심되는 문자열을 마스킹한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pattern in _SENSITIVE_PATTERNS:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logger(log_dir: Path, name: str = "h2h_archiver") -> logging.Logger:
    """날짜별 로그 파일(logs/YYYY-MM-DD.log)과 콘솔 출력을 갖춘 로거를 생성한다."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now():%Y-%m-%d}.log"

    logger = logging.getLogger(name)
    if logger.handlers:
        # 이미 초기화된 경우 재사용 (중복 핸들러 방지)
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.addFilter(_SensitiveDataFilter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.addFilter(_SensitiveDataFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
