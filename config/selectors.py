"""Weverse 사이트 구조(DOM selector, 네트워크 API 응답 필드명)를 한곳에 모아둔 설정 파일.

Weverse의 HTML class명이나 내부 API 응답 구조가 바뀌면 이 파일만 수정하면 되도록
`weverse_collector.py`는 여기 정의된 값만 참조하고 직접 selector 문자열을 갖지 않는다.

전략:
1) 1순위: 브라우저가 이미 수신한 내부 API(JSON) 응답을 가로채 파싱한다 (network capture).
   -> DOM 구조 변경에 가장 덜 민감하다.
2) 2순위: 위 방식이 실패하면 DOM selector 후보들을 순서대로 시도한다 (fallback).
   role / aria-label / data-* 속성을 우선하고, 특정 CSS class 하나에는 의존하지 않는다.
"""

# ── 커뮤니티 기본 정보 ────────────────────────────────────────────────
COMMUNITY_BASE_URL = "https://weverse.io"


def community_url(slug: str) -> str:
    return f"{COMMUNITY_BASE_URL}/{slug}"


def community_feed_url(slug: str) -> str:
    return f"{COMMUNITY_BASE_URL}/{slug}/feed"


def community_artist_tab_url(slug: str) -> str:
    return f"{COMMUNITY_BASE_URL}/{slug}/artist"


def community_members_tab_url(slug: str) -> str:
    # 2026-09-14 확인: Weverse에는 별도의 "/members" 경로가 없다. Artist 탭의 artistMembers는
    # 최근 활동(Moment)이 있는 멤버만 들어있어 8명 전체가 안 나올 수 있다. 반면 커뮤니티
    # 홈(Highlight) 탭 응답에는 전체 멤버가 artistProfiles 배열로 들어있으므로 이쪽을 쓴다.
    return community_url(slug)


def post_url(slug: str, post_id: str) -> str:
    return f"{COMMUNITY_BASE_URL}/{slug}/artist/{post_id}"


# ── 로그인 여부 판단 ──────────────────────────────────────────────────
# 다음 문자열/요소 중 하나라도 감지되면 "로그인이 필요한 상태"로 간주한다.
LOGIN_REQUIRED_URL_FRAGMENTS = ["/login", "/signin", "accounts.weverse.io"]
LOGIN_REQUIRED_TEXT_HINTS = ["로그인", "Log in", "Sign in", "로그인이 필요"]
# 로그인이 되어 있을 때 나타나는 요소 후보 (하나라도 발견되면 로그인 상태로 판단).
# 2026-09-14 실제 로그인/비로그인 화면을 스크린샷+DOM으로 각각 비교해 갱신함
# (data/login_debug_check, data/_fresh_logged_out_debug 참고).
# 주의: 'DM' 버튼은 비로그인 상태에서도 노출되어 지표로 쓸 수 없음이 확인됨 - 제외.
# 'Notification'(알림) 버튼은 로그인 상태에서만 나타나는 것을 확인함.
LOGGED_IN_INDICATOR_SELECTORS = [
    "button:has-text('Notification')",
    "button:has-text('알림')",
]

# ── 네트워크 API 응답에서 게시물/작성자/이미지를 찾기 위한 힌트 ─────────
# 2026-09-14 실제 캡처로 확인: Weverse는 커뮤니티 데이터를
# global.apis.naver.com/weverse/wevweb/community/v1.0/community-<id>/<TAB>/tabContent
# 형태의 API로 가져온다 ("wmsgpad="는 이 요청을 포함한 거의 모든 API 호출에 공통으로
# 붙는 쿼리 파라미터일 뿐, 별도의 노이즈 엔드포인트가 아님 - 제외 목록에 넣으면 안 된다).
# "tabContent"만으로도 충분히 정확하게 매칭되고, DM/구매/배너 등 무관한 API 호출은
# 자연히 걸러진다.
API_URL_HINTS = ["tabContent", "weversewebapi"]

# 명시적으로 제외할 URL 패턴 (현재는 없음 - 위 힌트 자체가 이미 충분히 좁다).
API_URL_EXCLUDE_HINTS: list[str] = []

# 게시물 객체를 식별하기 위한 키 이름 후보 (대소문자 그대로 매칭 시도)
# 2026-09-14 실제 tabContent API 응답으로 확인한 진짜 스키마에 맞춰 갱신함
# (data/_tabcontent_sample.json 참고: global.apis.naver.com/.../community-235/ARTIST/tabContent).
POST_ID_KEYS = ["postId", "post_id", "id", "contentId"]
AUTHOR_OBJECT_KEYS = ["author", "writer", "communityUser", "communityTabId", "artist", "member"]
AUTHOR_ID_KEYS = ["memberId", "communityArtistId", "profileId", "userId", "artistId", "id"]
AUTHOR_NAME_KEYS = ["profileName", "nickname", "name", "artistName"]
PUBLISHED_AT_KEYS = ["publishedAt", "publishAt", "createdAt", "publishTime"]
CONTENT_TEXT_KEYS = ["plainBody", "body", "content", "text"]

# Artist 탭 tabContent 응답의 artistMembers[] 안에 있는 "공식 프로필" 객체 -
# 실제 멤버 8명의 고정 식별자(memberId)와 정식 이름(officialName)이 여기 들어있다.
# 화면 닉네임보다 이게 더 신뢰할 수 있는 출처이므로 멤버 식별자 확인 1순위로 쓴다.
OFFICIAL_PROFILE_OBJECT_KEY = "artistOfficialProfile"
OFFICIAL_NAME_KEYS = ["officialName"]

# 게시물 안에서 "이 게시물이 속한 커뮤니티" 정보를 찾기 위한 키 (다른 아티스트 커뮤니티 콘텐츠
# 혼입 방지용 안전장치). 실제로는 post.community.urlPath / communityId 형태로 온다.
POST_COMMUNITY_OBJECT_KEY = "community"
COMMUNITY_URL_PATH_KEYS = ["urlPath", "communityUrlPath"]

# 이미지 정보를 담은 배열 키 후보. 실제 응답은 orderedAttachments 처럼 사진/영상이 섞인
# 배열로 오며, 각 항목이 {"type": "photo", "data": {...}} 형태로 한 겹 감싸져 있을 수 있다.
PHOTO_LIST_KEYS = ["orderedAttachments", "photos", "images", "attachedPhotos", "photoList"]
# 사진이 아닌 첨부(영상 등)를 걸러내기 위한 type 값 목록. 이 목록에 없으면 사진으로 간주하지 않는다.
PHOTO_TYPE_VALUES = ["photo", "PHOTO", "image", "IMAGE"]
# 이미지 URL 필드 우선순위 (앞에 있을수록 고해상도/원본일 가능성이 높음)
IMAGE_URL_KEYS_PRIORITY = [
    "originImgUrl", "original", "originalUrl", "sourceUrl", "largeUrl",
    "url", "imageUrl", "downloadUrl",
]
# 아래 키워드가 URL 필드명에 포함되어 있으면 썸네일로 간주하고 제외한다.
THUMBNAIL_URL_HINT_KEYWORDS = ["thumb", "thumbnail", "small", "preview", "_w=", "resize"]

# ── DOM fallback selector (네트워크 캡처 실패 시에만 사용) ───────────────
DOM_POST_CARD_CANDIDATES = [
    "article",
    "[data-testid*='post']",
    "[role='article']",
]
DOM_AUTHOR_NAME_CANDIDATES = [
    "[data-testid*='author']",
    "[aria-label*='작성자']",
    "header a[href*='/artist/']",
]
DOM_IMAGE_CANDIDATES = [
    "img[srcset]",
    "img[src*='weverse']",
    "picture img",
]

# ── 공식 단체(Group) 계정 판별 ───────────────────────────────────────
# members.json의 official_account.member_id 와 일치하면 무조건 GROUP으로 분류한다.
GROUP_NAME_HINTS = ["HEARTS2HEARTS", "하츠투하츠", "OFFICIAL"]
