"""Hearts2Hearts Weverse Archiver 메인 GUI (PySide6).

Chrome/Playwright 작업은 모두 worker.py의 BrowserWorker(단일 백그라운드 스레드)에서
실행되며, 이 파일은 화면 표시와 사용자 입력만 담당한다
(GUI 스레드에서 Playwright를 직접 호출하지 않음).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QComboBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.worker import BrowserWorker
from src.utils.logger import setup_logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.json"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config.example.json"
LOG_DIR = PROJECT_ROOT / "logs"

logger = setup_logger(LOG_DIR)


class QtLogHandler(logging.Handler):
    """logging 모듈의 로그를 GUI 로그 패널로 전달하는 핸들러."""

    def __init__(self, append_fn):
        super().__init__()
        self._append_fn = append_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._append_fn(self.format(record))
        except Exception:
            pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hearts2Hearts Weverse Archiver")
        self.resize(560, 640)

        self.config = self._load_config()
        self._build_ui()
        self._attach_log_handler()

        # Chrome/Playwright 작업을 전담하는 단일 백그라운드 스레드.
        # 이 스레드 안에서 Chrome을 한 번만 열고 앱이 끝날 때까지 재사용한다
        # (Playwright sync API는 자신을 시작한 스레드에서만 쓸 수 있고,
        #  Chrome을 완전히 껐다 켜면 로그인 세션도 풀리기 때문).
        profile_dir = PROJECT_ROOT / self.config.get("browser_profile", "./data/chrome_profile")
        members_json_path = PROJECT_ROOT / self.config.get(
            "members_config_path", "./data/members_runtime.json"
        )
        slug = self.config.get("community_slug", "hearts2hearts")
        self._browser_worker = BrowserWorker(profile_dir, members_json_path, slug)
        self._browser_worker.chrome_opened.connect(self._on_chrome_opened)
        self._browser_worker.progress.connect(self._on_progress)
        self._browser_worker.login_required.connect(self._on_login_required)
        self._browser_worker.finished_ok.connect(self._on_finished_ok)
        self._browser_worker.failed.connect(self._on_failed)
        self._browser_worker.setStackSize(16 * 1024 * 1024)  # Playwright의 greenlet 디스패처 대비 여유
        self._browser_worker.start()

    # ── UI 구성 ──────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        # 저장 위치
        path_group = QGroupBox("저장 위치")
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.config.get("download_root", "./Hearts2Hearts_Archive"))
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_btn)
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # 탐색 모드
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("탐색 모드"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("최신 게시물만 확인", "latest")
        self.mode_combo.addItem("전체 아카이브 구축", "full")
        if self.config.get("scan_mode") == "full":
            self.mode_combo.setCurrentIndex(1)
        mode_layout.addWidget(self.mode_combo)
        layout.addLayout(mode_layout)

        # 로그인 상태
        login_layout = QHBoxLayout()
        login_layout.addWidget(QLabel("Chrome 로그인 상태"))
        self.login_status_label = QLabel("● 확인 필요")
        self.login_status_label.setStyleSheet("color: gray;")
        login_layout.addWidget(self.login_status_label)
        login_layout.addStretch()
        layout.addLayout(login_layout)

        # 버튼
        self.chrome_open_btn = QPushButton("Chrome 열기 (직접 로그인, 창은 닫지 않아도 됨)")
        self.chrome_open_btn.clicked.connect(self._on_open_chrome)
        layout.addWidget(self.chrome_open_btn)

        self.start_btn = QPushButton("사진 저장 시작")
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)

        # 진행 상태
        layout.addWidget(QLabel("진행 상태"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.current_label = QLabel("현재 처리: -")
        layout.addWidget(self.current_label)

        # 통계
        stats_group = QGroupBox("결과")
        stats_layout = QVBoxLayout()
        self.new_posts_label = QLabel("새 게시물 : 0")
        self.new_images_label = QLabel("새 사진   : 0")
        self.dup_label = QLabel("중복 제외 : 0")
        self.error_label = QLabel("오류      : 0")
        for w in (self.new_posts_label, self.new_images_label, self.dup_label, self.error_label):
            stats_layout.addWidget(w)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # 로그 패널
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("로그"))
        open_log_folder_btn = QPushButton("로그 폴더 열기")
        open_log_folder_btn.clicked.connect(self._on_open_log_folder)
        log_header.addStretch()
        log_header.addWidget(open_log_folder_btn)
        layout.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        layout.addWidget(self.log_view)

        self.setCentralWidget(central)

    def _attach_log_handler(self) -> None:
        handler = QtLogHandler(self._append_log)
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    # ── 설정 로드/저장 ───────────────────────────────────────────────
    def _load_config(self) -> dict:
        """로컬 설정을 읽고, 없으면 공개용 예제 설정을 기본값으로 사용합니다.

        config.json은 개인 저장 경로 등이 들어갈 수 있어 Git에 포함하지 않습니다.
        """
        for path in (CONFIG_PATH, CONFIG_EXAMPLE_PATH):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.error(f"설정 파일 읽기 실패 ({path.name}): {e}")
        return {}

    def _save_config(self) -> None:
        self.config["download_root"] = self.path_edit.text()
        self.config["scan_mode"] = self.mode_combo.currentData()
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"설정 저장 실패: {e}")

    # ── 이벤트 핸들러 ────────────────────────────────────────────────
    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self.path_edit.text())
        if chosen:
            self.path_edit.setText(chosen)

    def _on_open_log_folder(self) -> None:
        try:
            os.startfile(str(LOG_DIR))  # Windows 전용
        except Exception as e:
            QMessageBox.warning(self, "오류", f"로그 폴더를 열 수 없습니다: {e}")

    def _on_open_chrome(self) -> None:
        self._set_buttons_busy(True)
        self._browser_worker.submit_open_chrome()
        QMessageBox.information(
            self,
            "안내",
            "Chrome 창이 열립니다. 카카오 계정으로 직접 로그인해 주세요.\n"
            "비밀번호나 인증 절차는 이 프로그램이 대신 처리하지 않습니다.\n\n"
            "로그인 후 이 Chrome 창은 그대로 두고(닫지 마세요) 프로그램으로 돌아와 "
            "'사진 저장 시작'을 누르면 같은 로그인 세션을 이어서 사용합니다.\n"
            "(Chrome을 완전히 껐다 켜면 로그인 세션이 풀릴 수 있습니다.)",
        )

    def _on_chrome_opened(self) -> None:
        self._set_buttons_busy(False)

    def _set_buttons_busy(self, busy: bool) -> None:
        """한 번에 하나의 작업만 Chrome을 쓰도록, 두 버튼이 동시에 눌리지 않게 막는다."""
        self.chrome_open_btn.setEnabled(not busy)
        self.start_btn.setEnabled(not busy)

    def _on_start(self) -> None:
        self._save_config()
        download_root = Path(self.path_edit.text())
        if not download_root.is_absolute():
            download_root = PROJECT_ROOT / download_root

        db_path = PROJECT_ROOT / self.config.get("database_path", "./data/archive.db")
        scan_mode = self.mode_combo.currentData()
        limit = int(self.config.get("recent_post_limit", 10))
        retry_count = int(self.config.get("retry_count", 3))
        min_interval = float(self.config.get("request_min_interval_sec", 1.5))
        debug_dir = (PROJECT_ROOT / "data" / "api_debug") if self.config.get("debug_capture_api") else None

        self._set_buttons_busy(True)
        self.progress_bar.setValue(0)
        self.current_label.setText("현재 처리: 준비 중...")

        self._browser_worker.submit_archive(
            db_path=db_path,
            download_root=download_root,
            scan_mode=scan_mode,
            recent_post_limit=limit,
            retry_count=retry_count,
            min_interval_sec=min_interval,
            debug_dir=debug_dir,
        )

    def _on_progress(self, idx: int, total: int, description: str) -> None:
        if total > 0:
            self.progress_bar.setValue(int(idx / total * 100))
        self.current_label.setText(f"현재 처리: {description} ({idx}/{total})")

    def _on_login_required(self) -> None:
        self.login_status_label.setText("● 로그인 필요")
        self.login_status_label.setStyleSheet("color: red;")
        self._set_buttons_busy(False)
        QMessageBox.warning(
            self,
            "로그인 필요",
            "로그인이 필요합니다. Chrome에서 직접 로그인한 후 다시 실행해 주세요.\n\n"
            "'Chrome 열기'로 로그인하고, 창은 닫지 말고 그대로 둔 채 "
            "'사진 저장 시작'을 다시 눌러주세요.",
        )

    def _on_finished_ok(self, stats: dict) -> None:
        self.login_status_label.setText("● 로그인됨")
        self.login_status_label.setStyleSheet("color: green;")
        self.new_posts_label.setText(f"새 게시물 : {stats['new_posts']}")
        self.new_images_label.setText(f"새 사진   : {stats['new_images']}")
        self.dup_label.setText(f"중복 제외 : {stats['duplicates']}")
        self.error_label.setText(f"오류      : {stats['errors']}")
        self.progress_bar.setValue(100)
        self.current_label.setText("현재 처리: 완료")
        self._set_buttons_busy(False)

        for item in stats.get("classified", []):
            logger.info(
                f"POST ID: {item['post_id']} / AUTHOR: {item['author']} -> "
                f"{item['member_folder']} ({item['category']}) / IMAGES: {item['image_count']}"
            )

    def _on_failed(self, message: str) -> None:
        self._set_buttons_busy(False)
        if "인터넷" in message or "ERR_INTERNET" in message or "net::" in message:
            QMessageBox.critical(self, "오류", "인터넷 연결을 확인해 주세요.")
        else:
            QMessageBox.critical(self, "오류", f"작업 중 오류가 발생했습니다:\n{message}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 오버라이드 메서드명)
        """프로그램 종료 시 백그라운드 스레드에 정리를 요청하고 끝날 때까지 기다린다."""
        self._browser_worker.request_stop()
        self._browser_worker.wait(10000)
        super().closeEvent(event)
