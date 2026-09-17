"""Hearts2Hearts Weverse Archiver 실행 진입점."""
from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    # 한글 로그/콘솔 출력이 깨지지 않도록 UTF-8을 강제한다.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# 어느 경로에서 실행하더라도 프로젝트 루트를 import 경로에 추가한다.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.main_window import MainWindow  # noqa: E402
from src.utils.checkpoint import checkpoint  # noqa: E402


def main() -> None:
    checkpoint("=== main.py 새 실행 시작 ===")
    app = QApplication(sys.argv)
    checkpoint("QApplication 생성됨")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
