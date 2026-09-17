# 💗 Hearts2Hearts Weverse Archiver

> **하투하 사진은 못 참습니다.**  
> Hearts2Hearts를 좋아해서 직접 만든 **비공식·비영리 개인 팬 아카이브 프로젝트**입니다.

CARMEN · JIWOO · YUHA · STELLA · JUUN · A-NA · IAN · YE-ON 💞

특히 게시물이 쌓일수록 사진을 멤버별로 다시 찾기 귀찮아서,
**“그냥 내가 보는 하투하 사진은 내가 깔끔하게 정리해서 보자”**라는 생각으로 만들었습니다.

이 프로그램은 사용자가 직접 로그인한 Weverse 세션에서 Hearts2Hearts 커뮤니티의 게시물을 확인하고,
게시물에 첨부된 이미지를 멤버별 폴더로 정리해 **개인 보관용으로 저장**합니다.

---

## ✨ 주요 기능

- Hearts2Hearts 커뮤니티만 대상으로 동작
- 멤버별 자동 분류
  - `CARMEN`
  - `JIWOO`
  - `YUHA`
  - `STELLA`
  - `JUUN`
  - `A-NA`
  - `IAN`
  - `YE-ON`
  - `GROUP`
  - `UNKNOWN`
- 게시물 날짜 / 게시물 ID 기준 폴더 정리
- SQLite 기반 중복 게시물 관리
- URL + 파일 해시 기반 이미지 중복 방지
- PySide6 GUI
- Playwright 기반 Chrome 제어
- 사용자가 직접 로그인한 세션 재사용
- 오프라인 파이프라인 테스트 포함

저장 구조 예시는 다음과 같습니다.

```text
<저장 위치>/Hearts2Hearts/Weverse/
├─ CARMEN/
├─ JIWOO/
├─ YUHA/
├─ STELLA/
├─ JUUN/
├─ A-NA/
├─ IAN/
├─ YE-ON/
├─ GROUP/
└─ UNKNOWN/
```

각 게시물은 아래 형태로 저장됩니다.

```text
JIWOO/
└─ 2026/
   └─ 09/
      └─ 2026-09-17_<POST_ID>/
         ├─ 20260917_JIWOO_<POST_ID>_001.jpg
         ├─ 20260917_JIWOO_<POST_ID>_002.jpg
         └─ metadata.json
```

---

## 🩷 왜 만들었나요?

그냥 **하투하를 좋아해서 만들었습니다.**

위버스에 올라오는 사진을 저장하다 보면 다운로드 폴더에 뒤섞이고,
나중에는 “이 사진 지우였나, 이안이었나, 단체였나…” 하면서 다시 찾게 됩니다.

그래서 직접:

**Weverse 확인 → 작성자 분류 → 사진 다운로드 → 중복 제거 → 멤버별 정리**

과정을 하나로 묶었습니다.

포트폴리오용으로 억지로 만든 프로젝트라기보다는,
**진짜 제가 쓰려고 만든 덕질 자동화 프로그램**에 가깝습니다. 💗

---

## 🚀 설치

### 1. 저장소 받기

```bash
git clone <YOUR_REPOSITORY_URL>
cd Hearts2Hearts_Weverse_Archiver
```

### 2. Python 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. Chrome 설치 확인

이 프로그램은 Playwright에 내장된 Chromium이 아니라,
시스템에 설치된 **Google Chrome**을 사용합니다.

### 4. 선택 사항: 개인 설정 만들기

기본값 그대로 써도 실행할 수 있습니다.
개인 저장 위치를 지정하려면:

```text
config.example.json
```

을 복사해:

```text
config.json
```

으로 만든 뒤 수정하면 됩니다.

`config.json`은 개인 경로가 들어갈 수 있기 때문에 `.gitignore`에 포함되어 있습니다.

멤버 식별 정보는 실행 중 `data/members_runtime.json`에 따로 생성됩니다.
따라서 Git에 포함되는 `config/members.json` 원본은 실행 후에도 깨끗하게 유지됩니다.

---

## ▶ 실행

### GUI

```bash
python main.py
```

1. `Chrome 열기`를 누릅니다.
2. 열린 Chrome에서 사용자가 직접 Weverse에 로그인합니다.
3. Chrome 창을 그대로 둔 상태에서 프로그램으로 돌아옵니다.
4. `사진 저장 시작`을 누릅니다.

프로그램은 비밀번호를 입력하거나 인증을 우회하지 않습니다.

---

## 🧪 콘솔 테스트

```bash
python test_run.py
```

다음 순서로 확인합니다.

1. Hearts2Hearts 커뮤니티 확인
2. 멤버 식별 정보 확인
3. 최근 게시물 분류
4. 이미지 저장

---

## 🧪 오프라인 테스트

실제 Weverse에 접속하지 않고 파싱/분류/중복 처리 흐름을 확인할 수 있습니다.

```bash
python tests/test_pipeline_offline.py
```

---

## 🔐 로그인과 개인정보 처리 원칙

이 프로젝트는 공개 저장소에 다음 데이터를 **포함하지 않습니다.**

- Chrome 사용자 프로필
- 로그인 쿠키
- 세션 정보
- 비밀번호
- 인증 토큰
- 개인 NAS / 로컬 저장 경로
- 실제 다운로드한 Hearts2Hearts 사진
- Weverse API 디버그 캡처
- 개인 로그 및 SQLite DB

실행 중 생성되는 해당 데이터는 `.gitignore`로 제외됩니다.

### 이 프로그램이 하지 않는 것

- 카카오 / Weverse 비밀번호 자동 입력
- CAPTCHA 우회
- 2단계 인증 우회
- 다른 Chrome 프로필의 쿠키 탈취
- 로그인하지 않은 상태에서 제한 콘텐츠 접근 시도
- 아티스트 사진을 이 저장소에 재배포

로그인이 만료되면 우회하지 않고 사용자가 다시 직접 로그인해야 합니다.

---

## ⚠ 사용 범위

이 프로젝트는 **개인적·비영리적 팬 아카이빙을 목적으로 만든 소프트웨어**입니다.

사용자는 자신의 이용 환경과 관련 법령, 서비스 이용약관을 확인하고 책임 있게 사용해야 합니다.
특히 유료·멤버십·접근 제한 콘텐츠를 우회하거나 제3자에게 재배포하는 용도로 사용하는 것을 의도하지 않습니다.

이 저장소에는 Hearts2Hearts의 사진, 영상 또는 Weverse 게시물 원본이 포함되어 있지 않습니다.

---

## 📌 비공식 프로젝트 안내

**Unofficial fan-made project.**

이 프로젝트는 Hearts2Hearts, SM Entertainment, Weverse Company와
제휴·승인·후원 관계가 없는 개인 팬 프로젝트입니다.

`Hearts2Hearts`, `Weverse` 및 관련 명칭과 제3자 콘텐츠의 권리는
각 권리자에게 있습니다.

MIT 라이선스는 이 저장소의 **직접 작성한 소스코드**에만 적용됩니다.
자세한 내용은 [`NOTICE.md`](NOTICE.md)를 참고해 주세요.

---

## 🛠 기술 스택

- Python
- PySide6
- Playwright
- SQLite
- Google Chrome

---

## 💗 Fan note

하츠투하츠 8명 전부 응원합니다.

이 저장소는 거창한 공식 도구가 아니라,
**팬 한 명이 사진 정리하다가 결국 프로그램까지 만들어버린 결과물**입니다.

덕질도 데이터 정리가 필요합니다. 😎
