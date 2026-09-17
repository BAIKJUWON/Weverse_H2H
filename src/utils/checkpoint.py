"""네이티브 크래시(Python 예외로 안 잡히는 종류) 진단용 체크포인트 로거.

Chrome 렌더러가 힙 손상 등으로 즉사하면 일반 logging은 버퍼링/스레드 타이밍 때문에
마지막 몇 줄이 파일에 기록되기 전에 프로세스가 죽을 수 있다. 이 함수는 매 호출마다
즉시 flush+fsync로 디스크에 써서, 죽기 직전 정확히 어느 단계였는지 남긴다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

_CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "data" / "_checkpoint.log"


def checkpoint(step: str) -> None:
    try:
        _CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CHECKPOINT_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S.')}{int(time.time()*1000)%1000:03d} {step}\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass
