"""Playwright로 실제 설치된 Google Chrome을 실행/제어하는 모듈.

중요한 제약 (절대 구현하지 않음):
- 카카오/위버스 계정 비밀번호 자동 입력
- CAPTCHA 우회
- 2단계 인증 우회
- 쿠키 탈취 또는 다른 프로필에서 인증정보 강제 추출

이 모듈은 "Weverse Collector 전용 Chrome 프로필"의 persistent context만 열고,
로그인 여부만 판단한다. 로그인 자체는 항상 사용자가 직접 수행한다.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from config import selectors
from src.utils.checkpoint import checkpoint

logger = logging.getLogger("h2h_archiver")

# Chrome은 동일한 user-data-dir(프로필 폴더)을 두 프로세스가 동시에 열 수 없다
# (프로필 잠금). "Chrome 열기"와 "사진 저장 시작"이 같은 자동화 프로필을 쓰므로,
# 이 앱 안에서 같은 프로필이 이미 열려 있으면 즉시 알기 쉬운 오류로 막는다.
_active_profiles_lock = threading.Lock()
_active_profiles: set[str] = set()


class ChromeProfileBusyError(RuntimeError):
    pass


class ChromeManager:
    """자동화 전용 Chrome 프로필의 persistent context 를 관리한다."""

    def __init__(self, profile_dir: Path, headless: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self._profile_key = str(profile_dir.resolve())
        self._registered = False

    def launch(self) -> BrowserContext:
        """자동화 전용 Chrome 프로필로 persistent context를 연다.

        같은 프로필 폴더(data/chrome_profile)를 다른 Chrome 창이 이미 사용 중이면
        Chrome이 프로필 잠금으로 즉시 종료되므로, 그 경우를 미리 감지해 알기 쉬운
        오류 메시지로 안내한다 ("Chrome 열기" 창을 닫지 않고 저장을 시작한 경우 등).
        """
        with _active_profiles_lock:
            if self._profile_key in _active_profiles:
                raise ChromeProfileBusyError(
                    "이미 같은 Chrome 프로필 창이 열려 있습니다. "
                    "열려 있는 Chrome 창을 닫은 후 다시 시도해 주세요."
                )
            _active_profiles.add(self._profile_key)
        self._registered = True

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Chrome 시작")
        checkpoint("launch: sync_playwright().start() 호출 전")
        try:
            self._playwright = sync_playwright().start()
            checkpoint("launch: playwright 시작됨, launch_persistent_context 호출 전")
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel="chrome",
                headless=self.headless,
                viewport={"width": 1400, "height": 900},
            )
            checkpoint("launch: launch_persistent_context 완료")
        except Exception as e:
            self._unregister()
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            raise ChromeProfileBusyError(
                "Chrome을 시작하지 못했습니다. 같은 프로필을 사용하는 다른 Chrome 창이 "
                "열려 있지 않은지 확인하고 다시 시도해 주세요. "
                f"(원인: {type(e).__name__})"
            ) from e
        return self.context

    def _unregister(self) -> None:
        if self._registered:
            with _active_profiles_lock:
                _active_profiles.discard(self._profile_key)
            self._registered = False

    def is_connected(self) -> bool:
        """이 인스턴스가 이미 살아 있는 Chrome persistent context를 들고 있는지 확인한다.

        살아 있으면 재사용해서 로그인 세션이 유지되도록 한다 (Chrome을 완전히 껐다 켜면
        Weverse 같은 세션 쿠키는 브라우저 기본 동작상 삭제되므로, 재시작 자체를 피한다).
        """
        if self.context is None:
            return False
        try:
            _ = self.context.pages
            return True
        except Exception:
            return False

    def new_page(self) -> Page:
        if self.context is None:
            raise RuntimeError("launch()를 먼저 호출해야 합니다.")
        pages = self.context.pages
        return pages[0] if pages else self.context.new_page()

    def check_login_status(self, page: Page, slug: str, debug_dir: Optional[Path] = None) -> bool:
        """Weverse 커뮤니티 페이지 접속 후 로그인 상태를 판단한다.

        비밀번호 입력이나 CAPTCHA 우회 없이, 이미 로그인되어 있는지만 확인한다.
        """
        url = selectors.community_url(slug)
        checkpoint(f"check_login_status: goto({url}) 호출 전")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        checkpoint("check_login_status: goto 완료")
        page.wait_for_timeout(1500)
        checkpoint("check_login_status: wait_for_timeout 완료")

        if debug_dir is not None:
            self._dump_login_debug(page, debug_dir)

        current_url = page.url
        for fragment in selectors.LOGIN_REQUIRED_URL_FRAGMENTS:
            if fragment in current_url:
                logger.info("Weverse 로그인 필요 (로그인 페이지로 리다이렉트됨)")
                return False

        # 로그인 필요 문구(예: '로그인', 'Login' 버튼)가 있으면, 다른 어떤 긍정 신호보다
        # 이걸 우선한다 - 로그인 전용이라고 생각했던 요소가 실제로는 비로그인 상태에서도
        # 노출되는 경우가 있어(예: 이 사이트의 'DM' 버튼), 부정 신호를 먼저 확인하는 게 더 안전하다.
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            pass
        if any(hint in body_text for hint in selectors.LOGIN_REQUIRED_TEXT_HINTS):
            logger.info("Weverse 로그인 필요 (로그인 안내 문구 감지)")
            return False

        for candidate in selectors.LOGGED_IN_INDICATOR_SELECTORS:
            try:
                if page.locator(candidate).first.is_visible(timeout=1000):
                    logger.info("Weverse 로그인 확인")
                    return True
            except Exception:
                continue

        # 판단 불가 시 안전하게 "미로그인"으로 처리 (거짓 긍정 방지)
        logger.info("로그인 상태를 명확히 판단하지 못했습니다. 미로그인으로 간주합니다.")
        return False

    def _dump_login_debug(self, page: Page, debug_dir: Path) -> None:
        """로그인 판단 시점의 화면을 스크린샷 + DOM 구조 요약으로 남긴다.

        selectors.py의 로그인 판단 selector가 실제 사이트와 맞는지 확인/수정할 때 쓴다.
        쿠키, Authorization 헤더, 토큰 등은 절대 포함하지 않는다 - 화면에 보이는 구조와
        짧은 텍스트 조각만 남긴다 (닉네임 등 사용자 본인 데이터는 포함될 수 있음).
        """
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%H%M%S")

            screenshot_path = debug_dir / f"login_{stamp}.png"
            page.screenshot(path=str(screenshot_path))

            inventory = page.evaluate(
                """
                () => {
                    const els = document.querySelectorAll(
                        '[data-testid], [aria-label], [role], nav, header, button, a[href]'
                    );
                    const results = [];
                    let count = 0;
                    for (const el of els) {
                        if (count >= 250) break;
                        results.push({
                            tag: el.tagName.toLowerCase(),
                            testid: el.getAttribute('data-testid'),
                            aria: el.getAttribute('aria-label'),
                            role: el.getAttribute('role'),
                            href: el.tagName.toLowerCase() === 'a' ? el.getAttribute('href') : null,
                            text: (el.innerText || '').slice(0, 40),
                        });
                        count++;
                    }
                    return { url: location.href, title: document.title, elements: results };
                }
                """
            )
            json_path = debug_dir / f"login_{stamp}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(inventory, f, ensure_ascii=False, indent=2)

            logger.info(f"로그인 판단 디버그 저장: {screenshot_path.name}, {json_path.name}")
        except Exception as e:
            logger.debug(f"로그인 디버그 캡처 실패 (무시하고 계속 진행): {e}")

    def close(self) -> None:
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        finally:
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
            self.context = None
            self._playwright = None
            self._unregister()
