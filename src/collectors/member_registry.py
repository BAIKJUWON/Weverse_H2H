"""config/members.json 을 로드하여 게시물 작성자를 멤버 폴더로 분류하는 모듈.

분류 원칙 (요청사항 5~8번):
- 위버스 표시 닉네임은 자주 바뀔 수 있으므로 "고정 식별자(member_id)"를 최우선으로 사용한다.
- member_id 매핑이 아직 없는 멤버는 별칭(aliases) 문자열 매칭으로 보조 판별하되,
  이 경우 근거가 약하다는 사실을 로그에 남긴다.
- 공식 단체 계정으로 판별되면 GROUP, 무엇도 확신할 수 없으면 UNKNOWN 으로 분류한다.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from config import selectors

logger = logging.getLogger("h2h_archiver")


class MemberRegistry:
    def __init__(self, members_json_path: Path):
        self.path = members_json_path
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            template_path = Path(__file__).resolve().parents[2] / "config" / "members.json"
            if self.path.resolve() != template_path.resolve():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(template_path, self.path)
                logger.info(f"런타임 멤버 레지스트리 생성: {self.path}")

        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @property
    def community_slug(self) -> str:
        return self._data.get("community_slug", "hearts2hearts")

    @property
    def members(self) -> list[dict]:
        return self._data["members"]

    @property
    def official_account(self) -> dict:
        return self._data["official_account"]

    def unresolved_members(self) -> list[str]:
        """member_id 가 아직 채워지지 않은 멤버 이름 목록."""
        return [m["name"] for m in self.members if not m.get("member_id")]

    def set_member_id(self, name: str, member_id: str, profile_url: Optional[str] = None) -> bool:
        for m in self.members:
            if m["name"] == name:
                m["member_id"] = member_id
                if profile_url:
                    m["profile_url"] = profile_url
                return True
        return False

    def set_official_account_id(self, member_id: str, profile_url: Optional[str] = None) -> None:
        self._data["official_account"]["member_id"] = member_id
        if profile_url:
            self._data["official_account"]["profile_url"] = profile_url

    def classify(self, author_id: Optional[str], author_name: Optional[str]) -> tuple[str, str]:
        """(member_folder, category) 를 반환한다. category 는 'member' | 'group' | 'unknown'."""

        # 1순위: 고정 식별자 매칭
        official = self.official_account
        if author_id and official.get("member_id") and author_id == official["member_id"]:
            return "GROUP", "group"

        if author_id:
            for m in self.members:
                if m.get("member_id") and author_id == m["member_id"]:
                    return m["name"], "member"

        # 2순위 (보조): 공식 계정 이름 힌트
        if author_name:
            name_upper = author_name.upper()
            if any(hint.upper() in name_upper for hint in selectors.GROUP_NAME_HINTS + official.get("aliases", [])):
                logger.info(f"작성자 '{author_name}' 를 이름 힌트로 GROUP 분류 (고정 식별자 미확인)")
                return "GROUP", "group"

            for m in self.members:
                if any(alias.upper() == name_upper for alias in m.get("aliases", [])):
                    logger.info(
                        f"작성자 '{author_name}' 를 닉네임 매칭으로 '{m['name']}' 분류 "
                        f"(고정 식별자 미확인 - 참고용 보조 판별)"
                    )
                    return m["name"], "member"

        logger.warning(f"작성자를 판별할 수 없어 UNKNOWN 분류함 (author_id={author_id}, author_name={author_name})")
        return "UNKNOWN", "unknown"
