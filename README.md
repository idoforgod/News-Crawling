# News-Crawling

AI 에이전트 기반 멀티소스 뉴스 크롤링 시스템. Naver, Google News(한국어/영어)에서 뉴스를 수집하고 단일 진실 원천(SOT)에 중복 없이 적재합니다.

## Architecture

```
main.py                  # 파이프라인 오케스트레이터
├── Phase 1: 국내 환경스캐닝 (WF1)
│   ├── NaverNewsCrawler      → naver_crawler.py
│   └── GoogleNewsCrawler     → google_crawler.py
├── Phase 2: 글로벌 환경스캐닝 (WF2)
│   └── GoogleEnNewsCrawler   → google_en_crawler.py
│
├── NetworkGuard              → network_guard.py    # 7대 원칙 기반 요청 가드
├── SOTGuardian               → sot_guardian.py     # 중복 방지 + 원자적 쓰기
└── TotalWarScraper           → total_war_scraper.py # 최후 수단 브라우저 에뮬레이션
```

## Core Components

### NetworkGuard
7대 원칙(URL 유효성, 네트워크 연결, 인증/차단 감지, 응답 코드 분석, 파싱 오류, 속도 제한, 로깅)을 적용한 요청 모듈. User-Agent 로테이션 풀(7종)을 순환하며 차단을 우회합니다.

### SOTGuardian
JSONL 기반 Single Source of Truth 관리자. Singleton 패턴으로 인스턴스를 공유하며, MD5 해시 지문(제목+본문 100자)과 URL 기반 이중 중복 검사를 수행합니다. `FileLock`으로 동시 쓰기 시 데이터 무결성을 보장합니다.

### TotalWarScraper
표준 크롤링(requests + trafilatura)이 실패했을 때 가동되는 최후 수단. `undetected-chromedriver`로 헤드리스 브라우저를 구동하고, 렌더링된 HTML에서 trafilatura 재추출 또는 텍스트 밀도 기반 강제 추출을 시도합니다. 브라우저 인스턴스를 재사용하여 성능을 최적화합니다.

### Google News URL Decoder
Google News의 난독화된 URL을 2단계로 디코딩합니다:
1. **Tier A**: 오프라인 protobuf 파싱 (외부 요청 없이 base64 → protobuf에서 URL 추출)
2. **Tier B**: `googlenewsdecoder` 라이브러리 폴백

## Data Flow

```
[Naver / Google KR / Google EN]
        │
        ▼
  NetworkGuard (robust_request)
        │
        ▼  ── 실패 시 ──▶ TotalWarScraper (브라우저 에뮬레이션)
        │                        │
        ▼                        ▼
  trafilatura (본문 추출)    렌더링 HTML에서 재추출
        │                        │
        └──────────┬─────────────┘
                   ▼
          SOTGuardian (중복 검사 → 원자적 쓰기)
                   │
                   ▼
        database/news/news_sot.jsonl
```

## SOT Schema

```jsonl
{
  "title": "기사 제목",
  "date": "2025-02-24",
  "content": "기사 본문 전체",
  "url": "https://...",
  "source": "naver | google | google_global",
  "wf_id": "wf1 | wf2",
  "lang": "ko | en",
  "collected_at": "2025-02-24T12:00:00"
}
```

## Retry Strategy

| Level | Component | 재시도 횟수 | 지연 전략 |
|-------|-----------|-------------|-----------|
| L1 | NetworkGuard | 5회 | Exponential backoff + jitter |
| L2 | 각 크롤러 | 3라운드 | 라운드마다 5s × round_num |
| L3 | Pipeline (main) | 3회 | 고정 30s |

## Setup

```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### Requirements

- Python 3.10+
- Chrome 브라우저 (TotalWarScraper용)

## Usage

```bash
python main.py
```

기본 검색 쿼리:
- **국내(WF1)**: `"인공지능 에이전트"` (Naver + Google KR)
- **글로벌(WF2)**: `"AI Agents OR Agentic AI"` (Google EN)

수집된 데이터는 `database/news/news_sot.jsonl`에 누적 저장됩니다.

## Project Structure

```
News-Crawling/
├── main.py                 # 파이프라인 엔트리포인트
├── naver_crawler.py        # 네이버 뉴스 크롤러
├── google_crawler.py       # 구글 뉴스 한국어 크롤러
├── google_en_crawler.py    # 구글 뉴스 영어 크롤러
├── network_guard.py        # 네트워크 요청 가드
├── sot_guardian.py         # SOT 무결성 관리자
├── total_war_scraper.py    # 최후 수단 브라우저 스크래퍼
├── requirements.txt        # Python 의존성
├── database/
│   └── news/               # 수집 데이터 저장소
│       └── news_sot.jsonl  # 단일 진실 원천
└── prompt/
    └── crawling-skill-sample.md  # 크롤링 스킬 레퍼런스
```

## License

Private
