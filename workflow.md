# News-Crawling Workflow — 완전 복제 매뉴얼

> 이 문서 하나만으로 다른 프로젝트에서 동일한 알고리즘과 워크플로우를 완벽하게 재현할 수 있도록 설계되었다.
> 모든 상수, 임계값, 폴백 체인, 의사결정 분기, 코드 패턴을 빠짐없이 기술한다.

---

## 목차

1. [설계 철학](#1-설계-철학)
2. [시스템 전체 아키텍처](#2-시스템-전체-아키텍처)
3. [컴포넌트 1: NetworkGuard — 네트워크 요청 가드](#3-컴포넌트-1-networkguard--네트워크-요청-가드)
4. [컴포넌트 2: SOTGuardian — 데이터 무결성 관리자](#4-컴포넌트-2-sotguardian--데이터-무결성-관리자)
5. [컴포넌트 3: TotalWarScraper — 최후 수단 브라우저 에뮬레이션](#5-컴포넌트-3-totalwarscraper--최후-수단-브라우저-에뮬레이션)
6. [컴포넌트 4: 크롤러 공통 패턴](#6-컴포넌트-4-크롤러-공통-패턴)
7. [소스별 크롤러 상세](#7-소스별-크롤러-상세)
8. [파이프라인 오케스트레이터 (main.py)](#8-파이프라인-오케스트레이터-mainpy)
9. [3계층 재시도 전략 상세](#9-3계층-재시도-전략-상세)
10. [Google News URL 디코딩 알고리즘](#10-google-news-url-디코딩-알고리즘)
11. [데이터 스키마 및 저장 형식](#11-데이터-스키마-및-저장-형식)
12. [새 프로젝트에 복제하는 절차](#12-새-프로젝트에-복제하는-절차)
13. [의존성 및 환경 구성](#13-의존성-및-환경-구성)
14. [확장 가이드: 새로운 소스 추가](#14-확장-가이드-새로운-소스-추가)

---

## 1. 설계 철학

### 1.1 절대 원칙: "반드시 수집한다"

이 시스템의 핵심 사상은 **"한 건도 놓치지 않는다"**이다. 모든 설계는 이 원칙에서 출발한다:

- 한 가지 방법이 실패하면, 다음 방법을 시도한다 (다단계 폴백)
- 한 라운드가 실패하면, 시간을 두고 다시 시도한다 (다계층 재시도)
- 모든 수단이 실패하면, 브라우저를 직접 띄운다 (Total War)

### 1.2 MECE (Mutually Exclusive, Collectively Exhaustive)

수집 데이터는 **중복 없이, 빠짐없이** 관리된다:

- URL 기반 조기 중복 차단 → 네트워크 요청 자체를 방지
- 내용 기반 해시 지문 중복 검사 → 동일 기사의 다른 URL 방어
- FileLock 원자적 쓰기 → 동시 실행 시 데이터 무결성 보장

### 1.3 공유 리소스 최적화

- TotalWarScraper의 브라우저 인스턴스는 **전체 파이프라인에서 1개만** 생성하여 공유
- SOTGuardian은 **Singleton 패턴**으로 모든 크롤러가 동일한 인메모리 해시셋을 참조
- 인스턴스 주입(Dependency Injection) 패턴으로 리소스 전달

---

## 2. 시스템 전체 아키텍처

### 2.1 파일 구조

```
project_root/
├── main.py                 # 파이프라인 오케스트레이터
├── network_guard.py        # [컴포넌트 1] 네트워크 요청 가드
├── sot_guardian.py          # [컴포넌트 2] SOT 무결성 관리자
├── total_war_scraper.py     # [컴포넌트 3] 최후 수단 브라우저 에뮬레이션
├── naver_crawler.py         # [소스 크롤러] 네이버 뉴스
├── google_crawler.py        # [소스 크롤러] 구글 뉴스 한국어
├── google_en_crawler.py     # [소스 크롤러] 구글 뉴스 영어
├── requirements.txt
└── database/
    └── news/
        └── news_sot.jsonl   # 단일 진실 원천 (Single Source of Truth)
```

### 2.2 의존성 그래프

```
main.py
 ├── NaverNewsCrawler
 │    ├── SOTGuardian (Singleton)
 │    ├── NetworkGuard (인스턴스)
 │    └── TotalWarScraper (주입받음)
 ├── GoogleNewsCrawler
 │    ├── SOTGuardian (동일 Singleton)
 │    ├── NetworkGuard (인스턴스)
 │    └── TotalWarScraper (동일 인스턴스)
 └── GoogleEnNewsCrawler
      ├── SOTGuardian (동일 Singleton)
      ├── NetworkGuard (인스턴스)
      └── TotalWarScraper (동일 인스턴스)
```

**핵심**: TotalWarScraper 1개, SOTGuardian 1개가 모든 크롤러에 걸쳐 공유된다.

### 2.3 실행 흐름 타임라인

```
[시작]
  │
  ├─ TotalWarScraper 인스턴스 생성 (브라우저는 아직 미생성, lazy init)
  │
  ├─ PHASE 1: 국내 환경스캐닝 (WF1)
  │   ├─ NaverNewsCrawler.run("인공지능 에이전트")
  │   │   ├─ search_news() → URL 목록 수집
  │   │   ├─ 1차 수집: crawl_article() × N건
  │   │   └─ 실패 기사 재시도 (최대 3라운드)
  │   │
  │   └─ GoogleNewsCrawler.run("인공지능 에이전트")
  │       ├─ search_news() → RSS → 폴백: 웹 크롤링
  │       ├─ 1차 수집: crawl_article() × N건
  │       └─ 실패 기사 재시도 (최대 3라운드)
  │
  ├─ PHASE 2: 글로벌 환경스캐닝 (WF2)
  │   └─ GoogleEnNewsCrawler.run("AI Agents OR Agentic AI")
  │       ├─ search_news() → RSS → 폴백: 웹 크롤링
  │       ├─ 1차 수집: crawl_article() × N건
  │       └─ 실패 기사 재시도 (최대 3라운드)
  │
  └─ [종료] TotalWarScraper.close() → 브라우저 명시적 종료
```

---

## 3. 컴포넌트 1: NetworkGuard — 네트워크 요청 가드

### 3.1 역할

모든 HTTP 요청의 **단일 게이트웨이**. 7대 원칙을 적용하여 안정적 요청을 보장한다.

### 3.2 7대 원칙

| # | 원칙 | 구현 |
|---|------|------|
| 1 | URL 유효성 | `urllib.parse.urlparse`로 scheme + netloc 존재 확인 |
| 2 | 네트워크 연결 | `requests.get(timeout=15, allow_redirects=True)` |
| 3 | 인증/차단 감지 | 401, 403, 407 → UA 로테이션 후 재시도 |
| 4 | 응답 코드 분석 | 200만 성공, 나머지는 재시도 또는 로깅 |
| 5 | 파싱 오류 | 호출자(크롤러)에서 try/except로 처리 |
| 6 | 속도 제한 | 429 → `min(10 * (attempt+1), 60)`초 대기 |
| 7 | 상세 로깅 | 모든 예외를 URL과 함께 로깅 |

### 3.3 User-Agent 로테이션 풀

```python
_UA_POOL = [
    # Chrome (Mac/Win/Linux) — 3종
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ... Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ... Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ... Chrome/124.0.0.0 Safari/537.36",
    # Safari (Mac) — 1종
    "Mozilla/5.0 (Macintosh; ...) AppleWebKit/605.1.15 ... Version/17.4 Safari/605.1.15",
    # Firefox (Win/Mac) — 2종
    "Mozilla/5.0 (Windows NT 10.0; ...; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; ...; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge (Win) — 1종
    "Mozilla/5.0 (Windows NT 10.0; ...) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]
```

**로테이션 방식**: 순환 인덱스 (`_ua_index = (_ua_index + 1) % len(_UA_POOL)`). 랜덤이 아닌 순환으로, 연속 요청 시 항상 다른 UA를 사용한다.

### 3.4 robust_request 상세 알고리즘

```
함수: robust_request(url, headers) → Response | None

1. URL 유효성 검증 (scheme + netloc)
   └─ 실패 → return None

2. for attempt in 0..4 (최대 5회):
   │
   ├─ attempt == 0: 전달받은 headers 사용 (없으면 로테이션된 UA)
   ├─ attempt > 0: 강제 UA 로테이션 + 지연
   │   └─ 지연 = base_delay(2.0) × (attempt+1) + random(1~3)초
   │       attempt 1: 4.0 + 1~3 = 5~7초
   │       attempt 2: 6.0 + 1~3 = 7~9초
   │       attempt 3: 8.0 + 1~3 = 9~11초
   │       attempt 4: 10.0 + 1~3 = 11~13초
   │
   ├─ requests.get(url, headers, timeout=15, allow_redirects=True)
   │
   ├─ status == 200 → return response ✅
   │
   ├─ status ∈ {401, 403, 407} → 차단 감지, UA 로테이션으로 다음 시도
   │
   ├─ status == 429 → 속도 제한
   │   └─ 추가 대기: min(10 × (attempt+1), 60)초
   │       attempt 0: 10초, attempt 1: 20초, ... attempt 4: 50초
   │
   ├─ ConnectionError → 서버 연결 실패 로깅
   └─ 기타 Exception → 상세 에러 로깅

3. 5회 모두 실패 → return None
```

### 3.5 핵심 상수

| 상수 | 값 | 용도 |
|------|-----|------|
| `max_retries` | 5 | 단일 URL 최대 요청 시도 |
| `base_delay` | 2.0초 | 재시도 지연 기준값 |
| `timeout` | 15초 | HTTP 요청 타임아웃 |
| `429 max wait` | 60초 | 속도 제한 시 최대 대기 |
| UA 풀 크기 | 7종 | 순환 로테이션 |

### 3.6 복제 시 주의사항

- `get_rotated_headers(extra_headers)`는 base UA에 extra를 **merge**한다. 크롤러에서 추가 헤더가 필요하면 여기서 주입.
- **UA 로테이션 덮어쓰기 주의**: `robust_request` 재시도 시 `get_rotated_headers(headers)`를 호출하는데, 호출자가 전달한 `headers`에 `User-Agent` 키가 포함되어 있으면 새로 로테이션한 UA를 덮어쓴다. 현재 크롤러들은 `_get_headers()`로 이미 UA가 포함된 헤더를 전달하므로, 실질적으로 같은 URL의 재시도에서는 **동일한 UA**가 사용된다. 재시도마다 다른 UA를 강제하려면, 호출자가 UA 없이 추가 헤더만 전달하거나 `robust_request` 내부에서 UA를 항상 덮어쓰도록 수정해야 한다.
- 초기 `_ua_index`는 `random.randint(0, len-1)`로 시작점을 랜덤화한다 → 여러 인스턴스가 동시에 돌아도 같은 UA로 시작하지 않음.

---

## 4. 컴포넌트 2: SOTGuardian — 데이터 무결성 관리자

### 4.1 역할

JSONL 파일 기반 Single Source of Truth의 **유일한 쓰기 게이트**. 모든 크롤러는 이 컴포넌트를 통해서만 데이터를 저장한다.

### 4.2 Singleton 패턴

```python
class SOTGuardian:
    _instance = None

    def __new__(cls, sot_path):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sot_path = sot_path
            cls._instance.lock_path = f"{sot_path}.lock"
            cls._instance.seen_content_hashes = cls._instance._load_sot_hashes()
        return cls._instance
```

**왜 Singleton인가**: 3개의 크롤러가 각자 `SOTGuardian(sot_path)`을 호출하지만, 실제로는 동일한 인메모리 해시셋을 공유한다. 크롤러 A가 저장한 기사를 크롤러 B가 즉시 인지할 수 있다.

### 4.3 이중 중복 검사 메커니즘

```
[크롤링 시작 전]
    │
    ├─ is_url_known(url) → seen_urls(Set) 조회
    │   └─ True → 네트워크 요청 자체를 하지 않음 (대역폭 절약)
    │
[본문 추출 성공 후]
    │
    └─ save_article(article) 내부:
        ├─ 4대 필수 항목 검증: title, date, content, url
        │   조건: `not article.get(k)` → 키 누락뿐 아니라 빈 문자열("")/None도 거부
        │   └─ 하나라도 falsy → return False (거부)
        │
        ├─ 내용 기반 지문 재검증:
        │   fingerprint = MD5(title + content[:100])
        │   └─ seen_content_hashes에 존재 → return False (거부)
        │
        ├─ 메타데이터 강제 주입:
        │   ├─ source: 없으면 "unknown"
        │   ├─ collected_at: 없으면 datetime.now().isoformat()
        │   └─ lang: 없으면 "ko"
        │
        └─ FileLock 획득 (timeout=10초) → 원자적 쓰기
            ├─ JSONL append: json.dumps(article, ensure_ascii=False) + "\n"
            │   (ensure_ascii=False: 한글이 유니코드 이스케이프 없이 원문 그대로 저장)
            ├─ seen_content_hashes.add(fingerprint)
            ├─ seen_urls.add(url)
            └─ return True

        예외 처리:
            ├─ filelock.Timeout → Lock 획득 시간 초과, return False
            └─ Exception → 치명적 오류 로깅, return False
```

### 4.4 공개 API: is_duplicate

`save_article` 내부에서 자동으로 중복 검사가 수행되지만, 크롤러가 저장 전에 명시적으로 중복 여부만 확인하고 싶을 때 사용할 수 있는 별도 메서드가 존재한다:

```python
def is_duplicate(self, title: str, content: str) -> bool:
    fingerprint = self._generate_fingerprint(title, content)
    return fingerprint in self.seen_content_hashes
```

현재 크롤러에서는 직접 호출하지 않지만, 향후 "본문 추출 후 저장 전에 미리 걸러내기" 패턴에서 활용 가능하다.

### 4.5 해시 지문 생성 알고리즘 (공통 핵심)

```python
def _generate_fingerprint(title: str, content: str) -> str:
    safe_content = content[:100] if content else ""
    return hashlib.md5((title + safe_content).encode('utf-8')).hexdigest()
```

**왜 content[:100]인가**: 전체 본문을 해싱하면 비용이 크고, 동일 기사의 약간 다른 버전(광고 텍스트 차이 등)을 놓칠 수 있다. 제목 + 본문 앞 100자는 기사의 **핵심 정체성**을 충분히 표현한다.

### 4.6 초기화 시 기존 데이터 로드

```python
def _load_sot_hashes(self):
    hashes = set()
    urls = set()
    if os.path.exists(self.sot_path):
        with open(self.sot_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'title' in data and 'content' in data:
                        hashes.add(self._generate_fingerprint(data['title'], data['content']))
                    if 'url' in data:
                        urls.add(data['url'])
                except json.JSONDecodeError:
                    continue  # 손상된 줄은 건너뜀 (JSONL 복원력)
    self.seen_urls = urls
    return hashes
```

**중요**: 프로그램 재시작 시에도 이전에 수집한 모든 데이터의 지문이 메모리에 로드된다. 따라서 동일 기사를 절대 중복 수집하지 않는다.

### 4.7 핵심 상수

| 상수 | 값 | 용도 |
|------|-----|------|
| 지문 해시 | MD5 | 속도 우선 (보안 목적 아님) |
| 지문 범위 | title + content[:100] | 핵심 정체성 식별 |
| FileLock timeout | 10초 | 동시성 제어 대기 한도 |
| 필수 키 | title, date, content, url | 4대 절대 원칙 |

### 4.8 복제 시 주의사항

- **Singleton은 sot_path를 무시한다**: `__new__`는 `_instance`가 존재하면 인자와 무관하게 기존 인스턴스를 반환한다. 따라서 최초 `SOTGuardian("path_a")` 호출 후 `SOTGuardian("path_b")`를 호출해도 `path_a`의 인스턴스가 반환된다. 다른 sot_path가 필요하면 반드시 `SOTGuardian._instance = None`으로 리셋 후 재생성해야 한다.
- `_instance = None`은 클래스 변수이므로, 테스트 시 또는 sot_path 변경 시 `SOTGuardian._instance = None`으로 리셋해야 한다.
- JSONL 형식은 **append-only**. 삭제/수정은 별도 관리 스크립트로 처리한다.

---

## 5. 컴포넌트 3: TotalWarScraper — 최후 수단 브라우저 에뮬레이션

### 5.1 역할

표준 크롤링(requests + trafilatura)이 **모두 실패**했을 때만 가동되는 최후의 수단. JavaScript 렌더링이 필요한 사이트, 강력한 봇 차단 사이트를 돌파한다.

### 5.2 브라우저 생명주기

```
[Lazy Initialization]
생성자에서 driver = None. 실제 브라우저는 첫 scrape_with_all_means() 호출 시 생성.

[재사용]
한 번 생성된 브라우저는 파이프라인 종료까지 계속 재사용.
매 호출 시 driver.get(url)로 새 페이지만 로드.

[자동 재시작]
연속 실패 3회(self._MAX_FAILURES_BEFORE_RESTART) 도달 시:
  → 기존 브라우저 quit() → 새 브라우저 생성
  → 연속 실패 카운터 리셋

[명시적 종료]
main.py의 finally 블록에서 total_war.close() 호출.
```

### 5.3 브라우저 설정

```python
import undetected_chromedriver as uc

options = uc.ChromeOptions()
options.add_argument('--headless')              # GUI 없이 실행
options.add_argument('--no-sandbox')            # 컨테이너 환경 호환
options.add_argument('--disable-dev-shm-usage') # 메모리 이슈 방지
options.add_argument('--window-size=1920,1080') # 일반 데스크톱 해상도 위장
driver = uc.Chrome(options=options)
```

**왜 undetected_chromedriver인가**: 일반 Selenium은 `navigator.webdriver = true`를 노출하여 봇으로 탐지된다. `uc.Chrome`은 이 플래그를 자동으로 숨기고, Chrome DevTools Protocol 지문도 위장한다.

### 5.4 scrape_with_all_means 상세 알고리즘

```
함수: scrape_with_all_means(url) → {"title": str, "content": str} | None

1. _ensure_browser()
   ├─ 연속 실패 >= 3 → 브라우저 종료 후 재생성
   └─ driver가 None → 새 브라우저 초기화

2. driver.get(url)

3. WebDriverWait(driver, 5) — <p> 태그 감지 시 조기 탈출
   └─ 타임아웃이어도 진행 (일부 사이트는 <p> 없이 구성)

4. html = driver.page_source
   soup = BeautifulSoup(html, 'lxml')

5. 본문 추출 시도 1: trafilatura
   content = trafilatura.extract(html)

6. 본문 추출 시도 2: 텍스트 밀도 기반 강제 추출
   조건: content가 없거나 len(content) < 300
   방법: soup.select("p") → 20자 이상인 <p> 태그만 추출 → "\n" 조인

7. 제목 추출 (우선순위):
   ① soup.title.string
   ② soup.find("h1").get_text()
   ③ soup.find("h2").get_text()

8. 성공 판정: content 존재 AND len(content) > 200
   ├─ 성공 → 연속 실패 카운터 리셋, return {"title", "content"}
   └─ 실패 → 연속 실패 +1, return None
```

### 5.5 핵심 상수

| 상수 | 값 | 용도 |
|------|-----|------|
| `_MAX_FAILURES_BEFORE_RESTART` | 3 | 연속 실패 시 브라우저 재시작 |
| WebDriverWait timeout | 5초 | 페이지 로딩 대기 |
| 본문 최소 길이 (trafilatura 실패 판정) | 300자 | 텍스트 밀도 추출로 전환 |
| 본문 최소 길이 (최종 성공 판정) | 200자 | 유효한 기사로 인정 |
| `<p>` 태그 최소 길이 | 20자 | 광고/네비게이션 텍스트 필터링 |

### 5.6 복제 시 주의사항

- `undetected_chromedriver`는 Chrome 브라우저가 시스템에 설치되어 있어야 한다.
- Headless 모드에서도 `--window-size=1920,1080`을 설정해야 모바일 버전 페이지를 받지 않는다.
- `uc.Chrome()`은 초기 생성 시 5~10초 소요. **반복 호출 시 반드시 인스턴스를 재사용**해야 한다.

---

## 6. 컴포넌트 4: 크롤러 공통 패턴

### 6.1 모든 크롤러에 공통되는 구조

```python
class AnyCrawler:
    def __init__(self, sot_path, total_war=None):
        self.guardian = SOTGuardian(sot_path)          # Singleton 공유
        self.net_guard = NetworkGuard()                 # 인스턴스 개별 생성
        self.total_war = total_war or TotalWarScraper() # 주입 또는 신규 생성

    def search_news(self, query) -> List:
        """1단계: 검색 결과에서 기사 URL/메타데이터 목록 수집"""
        ...

    def crawl_article(self, info) -> Optional[Dict]:
        """2단계: 개별 기사 본문 수집 + SOT 저장"""
        ...

    def run(self, query):
        """3단계: 검색 → 1차 수집 → 실패 재시도"""
        ...
```

### 6.2 crawl_article 공통 흐름

모든 크롤러의 `crawl_article`은 동일한 4단계를 따른다:

```
STEP 1: URL 기반 조기 중복 검사
    if guardian.is_url_known(url):
        return None  ← 네트워크 요청 자체를 하지 않음

STEP 2: 표준 수집 (requests + trafilatura 또는 BS4 파싱)
    response = net_guard.robust_request(url, headers)
    content = 추출 시도

STEP 3: 실패 시 Total War 가동
    if content 없음 or len(content) < 임계값:
        tw_result = total_war.scrape_with_all_means(url)

STEP 4: SOT에 저장
    article = {title, date, content, url, source, wf_id, lang}
    guardian.save_article(article)  ← 내부에서 중복 재검증 + 원자적 쓰기
```

### 6.3 run() 공통 흐름 — 재시도 루프

```
MAX_RETRY_ROUNDS = 3

1. articles = search_news(query)

2. 1차 수집:
   failed = []
   for item in articles:
       result = crawl_article(item)
       if result is None AND not guardian.is_url_known(url):
           failed.append(item)

3. 재시도 루프:
   for round in 1..3:
       if not failed: break
       sleep(5 * round)  ← 5초, 10초, 15초로 점진적 증가
       still_failed = []
       for item in failed:
           result = crawl_article(item)
           if result is None AND not guardian.is_url_known(url):
               still_failed.append(item)
       failed = still_failed

4. 최종 보고:
   if failed: 경고 로그 (미수집 기사 수)
   else: 성공 로그
```

**핵심**: 재시도 판정 시 `not guardian.is_url_known(url)` 조건이 있다. 이전 라운드에서 다른 크롤러가 같은 URL을 수집했다면 재시도 대상에서 제외된다.

### 6.4 본문 최소 길이 임계값 (소스별 차이)

| 소스 | 표준 수집 실패 판정 | Total War 가동 조건 |
|------|---------------------|---------------------|
| Naver | BS4 파싱 결과 < 200자 | 파싱 자체 실패 |
| Google KR | trafilatura 결과 < 300자 | content 없음 or < 300자 |
| Google EN | trafilatura 결과 < 500자 | content 없음 or < 500자 |

**왜 Google EN이 500자인가**: 영문 기사는 한글보다 평균 길이가 길고, 300자 미만의 영문 추출 결과는 대부분 불완전하다.

---

## 7. 소스별 크롤러 상세

### 7.1 NaverNewsCrawler

#### 검색 알고리즘 (search_news)

```
URL 패턴: https://search.naver.com/search.naver?where=news&query={query}&pd=1&start={start}
  - pd=1: 최근 1일 이내
  - start: 페이지네이션 (1, 11, 21, ...)

페이지 순회:
  - 최대 10페이지 (100건)
  - 연속 2페이지에서 신규 기사 0건 → 조기 종료

기사 URL 추출:
  - soup.select("a") 전체에서
  - href에 "n.news.naver.com/mnews/article" 포함된 링크만
  - 쿼리스트링 제거: href.split("?")[0]
  - 중복 제거: list(set(urls))
```

#### 본문 파싱 (crawl_article)

```
제목 셀렉터: "#title_area span" 또는 ".media_end_head_headline"
날짜 셀렉터: ".media_end_head_info_datestamp_time" 또는 ".t11"
본문 셀렉터: "#dic_area" 또는 "#newsct_article"

본문 정제:
  - 제거 대상: ".article_footer", ".img_desc", "script", "style"
  - decompose() 후 get_text(strip=True)
  - 최소 200자 이상만 유효

출력 article 필드:
  source: "naver"
  wf_id: "wf1"
  lang: "ko"
```

### 7.2 GoogleNewsCrawler (한국어)

#### 검색 알고리즘 — 2단계 폴백

```
[Tier 1] RSS 수집:
URL: https://news.google.com/rss/search?q={query}+when:1d&hl=ko&gl=KR&ceid=KR:ko
파싱: BeautifulSoup(xml) → soup.select("item")
추출: title, link (google_url), pubDate

    │
    └─ RSS 결과 0건
         │
         ▼

[Tier 2] 웹 크롤링 폴백:
URL A: https://news.google.com/search?q={query}+when:1d&hl=ko&gl=KR&ceid=KR:ko
  → TotalWarScraper로 시도
  → TotalWar 성공/실패 모두 return [] (TotalWar는 {title,content}만 반환하므로
    검색 결과 페이지에서 기사 URL 목록을 추출하는 용도로는 사용 불가)
  → TotalWar 실패 시에만 아래 URL B로 폴백

URL B: https://www.google.com/search?q={query}&tbm=nws&tbs=qdr:d
  → NetworkGuard.robust_request()
  → soup.select("a[href*='/url?']")
  → regex로 실제 URL 추출: /url?q=(https?://[^&]+)
  → 제목 6자 이상만 유효 (len(title) > 5)
```

#### 본문 수집 — Google URL 디코딩 포함

```
1. google_url이 news.google.com 도메인이면 → decode_url() 실행
   (decode_url 알고리즘은 §10에 상세 기술)

2. 표준 수집: net_guard.robust_request() + trafilatura.extract()

3. 실패 (없음 or < 300자) → total_war.scrape_with_all_means()

출력 article 필드:
  source: "google"
  wf_id: "wf1"
  lang: "ko"
```

### 7.3 GoogleEnNewsCrawler (영어)

구조는 GoogleNewsCrawler와 **거의 동일**하나, 다음 항목이 다르다:

| 항목 | Google KR | Google EN |
|------|-----------|-----------|
| RSS hl/gl/ceid | `hl=ko&gl=KR&ceid=KR:ko` | `hl=en-US&gl=US&ceid=US:en` |
| 웹 크롤링 폴백 | Google News → Google 검색 | Google 검색만 |
| Total War 가동 임계값 | 300자 | **500자** |
| source 필드 | `"google"` | `"google_global"` |
| wf_id 필드 | `"wf1"` | `"wf2"` |
| lang 필드 | `"ko"` | `"en"` |
| run() 반환값 | 없음 | **results 리스트 반환** (번역 대기용) |

**run()의 차이점**: GoogleEnNewsCrawler.run()은 수집된 기사 목록을 **return**한다. main.py에서 이 리스트를 받아 `TRANSLATION_REQUIRED:` 시그널을 출력한다.

---

## 8. 파이프라인 오케스트레이터 (main.py)

### 8.1 상세 알고리즘

```python
def main():
    query_ko = "인공지능 에이전트"
    query_en = "AI Agents OR Agentic AI"
    sot_path = "database/news/news_sot.jsonl"

    # 디렉토리 자동 생성
    os.makedirs(os.path.dirname(sot_path), exist_ok=True)

    # 공유 리소스 생성
    total_war = TotalWarScraper()  # 브라우저는 lazy init

    try:
        for pipeline_attempt in 1..3:
            if pipeline_attempt > 1:
                sleep(30)  # 파이프라인 레벨 재시도 대기

            try:
                # PHASE 1: 국내 (WF1)
                NaverNewsCrawler(sot_path, total_war).run(query_ko)
                GoogleNewsCrawler(sot_path, total_war).run(query_ko)

                # PHASE 2: 글로벌 (WF2)
                en_articles = GoogleEnNewsCrawler(sot_path, total_war).run(query_en)

                # 번역 필요 기사 시그널 출력
                if en_articles:
                    for art in en_articles:
                        print(f"TRANSLATION_REQUIRED: {art['url']}|{art['title']}")

                break  # 성공 시 루프 탈출

            except Exception:
                if pipeline_attempt >= 3:
                    # 최대 재시도 도달 → 수집된 데이터로 진행
                    pass

    finally:
        total_war.close()  # 반드시 브라우저 종료
```

### 8.2 리소스 관리 패턴

```
try:
    ... 모든 크롤링 작업 ...
finally:
    total_war.close()  ← 예외 발생 여부와 무관하게 반드시 실행
```

이 패턴은 **Chrome 프로세스 좀비 방지**에 필수적이다. `finally`가 없으면 예외 시 Chrome 프로세스가 시스템에 남는다.

### 8.3 TotalWarScraper 주입 패턴

```python
total_war = TotalWarScraper()  # 1개만 생성

naver = NaverNewsCrawler(sot_path=sot_path, total_war=total_war)      # 주입
google_kr = GoogleNewsCrawler(sot_path=sot_path, total_war=total_war)  # 동일 인스턴스 주입
google_en = GoogleEnNewsCrawler(sot_path=sot_path, total_war=total_war) # 동일 인스턴스 주입
```

각 크롤러의 생성자에서는:
```python
self.total_war = total_war or TotalWarScraper()  # 주입 없으면 자체 생성
```

---

## 9. 3계층 재시도 전략 상세

이 시스템의 가장 핵심적인 설계. 3개 레이어가 각각 다른 범위의 실패를 담당한다.

### 9.1 전체 재시도 구조도

```
┌─────────────────────────────────────────────────────────┐
│ L3: Pipeline (main.py)                                   │
│ 재시도: 3회 | 대기: 30초 고정 | 범위: 전체 파이프라인     │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ L2: Crawler (각 크롤러의 run())                     │  │
│  │ 재시도: 3라운드 | 대기: 5×round초 | 범위: 실패 기사들 │  │
│  │                                                     │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │ L1: NetworkGuard (robust_request)             │   │  │
│  │  │ 재시도: 5회 | 대기: exponential+jitter         │   │  │
│  │  │ 범위: 단일 HTTP 요청                          │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 9.2 최악의 경우 총 시도 횟수 계산

단일 기사에 대한 최대 시도 횟수:
```
L1 × L2 = 5회(NetworkGuard) × 4라운드(1차+3재시도) = 20회의 HTTP 요청
+ Total War 시도 4회 (각 라운드마다 1회)
= 최대 24회의 접근 시도

이것이 L3에 의해 3번 반복될 수 있으므로:
이론적 최대 = 24 × 3 = 72회
```

### 9.3 각 레이어의 대기 시간 상세

**L1 (NetworkGuard)**:
```
attempt 0: 즉시
attempt 1: 2.0×2 + random(1,3) = 5~7초
attempt 2: 2.0×3 + random(1,3) = 7~9초
attempt 3: 2.0×4 + random(1,3) = 9~11초
attempt 4: 2.0×5 + random(1,3) = 11~13초
+ 429 추가 대기: 10, 20, 30, 40, 50초

L1 총 대기 (최악): ~50초 + 150초(429) = ~200초
```

**L2 (Crawler run)**:
```
round 1: sleep(5×1) = 5초
round 2: sleep(5×2) = 10초
round 3: sleep(5×3) = 15초

L2 추가 대기: 30초
```

**L3 (Pipeline)**:
```
attempt 2: sleep(30)
attempt 3: sleep(30)

L3 추가 대기: 60초
```

---

## 10. Google News URL 디코딩 알고리즘

Google News RSS의 기사 URL은 `https://news.google.com/rss/articles/...` 형태로 난독화되어 있다. 실제 기사 URL을 얻으려면 디코딩이 필요하다.

### 10.1 2-Tier 디코딩 체인

```
입력: "https://news.google.com/rss/articles/CBMi..."

[Tier A: 오프라인 Protobuf 파싱] — 외부 요청 없음, 빠름
    │
    ├─ 성공 → 실제 URL 반환
    │
    └─ 실패
         │
         ▼
[Tier B: googlenewsdecoder 라이브러리] — 외부 요청 있음, 느림
    │
    ├─ 성공 → 실제 URL 반환
    │
    └─ 실패 → 원본 google_url 그대로 반환
```

### 10.2 Tier A: Protobuf 파싱 상세

```python
# 1. URL에서 base64 인코딩된 부분 추출
match = re.search(r'articles/([^?]+)', google_url)
encoded = match.group(1)

# 2. base64 패딩 보정
padding = len(encoded) % 4
if padding:
    encoded += '=' * (4 - padding)

# 3. base64 디코딩
raw = base64.urlsafe_b64decode(encoded)

# 4. Protobuf 수동 파싱 (라이브러리 없이)
urls = []
i = 0
while i < len(raw):
    if i + 1 >= len(raw):  # 경계 검사: 최소 2바이트 필요
        break
    tag = raw[i]
    wire_type = tag & 0x07  # 하위 3비트 = wire type

    if wire_type == 2:  # length-delimited (문자열)
        i += 1
        # varint로 길이 읽기
        length = 0
        shift = 0
        while i < len(raw):
            b = raw[i]
            length |= (b & 0x7F) << shift
            shift += 7
            i += 1
            if not (b & 0x80):
                break

        # 경계 검사 후 문자열 추출
        if i + length <= len(raw):
            try:
                field_str = raw[i:i+length].decode('utf-8', errors='ignore')
                if field_str.startswith('http'):
                    urls.append(field_str)
            except Exception:
                pass
        i += length

    elif wire_type == 0:  # varint (숫자 필드, 건너뜀)
        i += 1
        while i < len(raw) and raw[i] & 0x80:
            i += 1
        i += 1

    else:
        break  # 알 수 없는 wire type → 파싱 중단

# 5. 여러 URL 중 가장 긴 것 선택 (실제 기사 URL이 보통 가장 길다)
result = max(urls, key=len)
```

### 10.3 Tier B: googlenewsdecoder

```python
from googlenewsdecoder import new_decoderv1
decoded = new_decoderv1(google_url, interval=1)
# interval=1: Google 서버 요청 간 1초 대기
if decoded and decoded.get("decoded_url"):
    return decoded["decoded_url"]
```

### 10.4 디코딩 적용 조건

```python
# decode가 필요한 경우: google_url에 "news.google.com"이 포함된 경우만
if 'google_url' in info and 'news.google.com' in info['google_url']:
    url = self.decode_url(info['google_url'])
else:
    # 웹 크롤링 폴백에서 이미 실제 URL을 추출한 경우
    url = info.get('google_url', info.get('url', ''))
```

---

## 11. 데이터 스키마 및 저장 형식

### 11.1 JSONL 형식

파일: `database/news/news_sot.jsonl`

한 줄 = 한 기사. 각 줄은 독립된 JSON 객체.

```json
{"title":"AI 에이전트의 미래","date":"2025-02-24","content":"기사 본문 전체...","url":"https://news.naver.com/...","source":"naver","wf_id":"wf1","lang":"ko","collected_at":"2025-02-24T12:00:00.000000"}
```

### 11.2 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `title` | string | **필수** | 기사 제목 |
| `date` | string | **필수** | 기사 발행일 (다양한 형식 허용) |
| `content` | string | **필수** | 기사 본문 전체 (최소 200자 이상) |
| `url` | string | **필수** | 기사 원본 URL (중복 검사 키) |
| `source` | string | 자동 | `"naver"` / `"google"` / `"google_global"` |
| `wf_id` | string | 자동 | `"wf1"` (국내) / `"wf2"` (글로벌) |
| `lang` | string | 자동 | `"ko"` / `"en"` |
| `collected_at` | string | 자동 | ISO 8601 타임스탬프 |

### 11.3 왜 JSONL인가

- **Append-only**: 동시 쓰기 안전. 여러 프로세스가 파일 끝에 추가만 한다.
- **스트리밍 읽기**: 전체 파일을 메모리에 로드하지 않고 한 줄씩 처리 가능.
- **복구 용이**: 한 줄이 손상되어도 나머지 줄은 정상.
- **도구 호환**: `jq`, `pandas.read_json(lines=True)` 등과 즉시 호환.

---

## 12. 새 프로젝트에 복제하는 절차

### 12.1 Step 1: 인프라 컴포넌트 복사 (수정 없이 재사용)

다음 3개 파일은 **어떤 크롤링 프로젝트에서든 수정 없이** 그대로 사용할 수 있다:

```
network_guard.py    → 그대로 복사
sot_guardian.py     → 그대로 복사 (sot_path만 변경)
total_war_scraper.py → 그대로 복사
```

### 12.2 Step 2: 새 소스 크롤러 작성

§6의 공통 패턴을 따라 새 크롤러를 작성한다:

```python
from sot_guardian import SOTGuardian
from network_guard import NetworkGuard
from total_war_scraper import TotalWarScraper

class NewSourceCrawler:
    def __init__(self, sot_path, total_war=None):
        self.guardian = SOTGuardian(sot_path)
        self.net_guard = NetworkGuard()
        self.total_war = total_war or TotalWarScraper()

    def search_news(self, query):
        # 소스별 검색 로직 구현
        # RSS, API, 웹 크롤링 등
        return [{"title": ..., "url": ..., "date": ...}, ...]

    def crawl_article(self, info):
        url = info['url']

        # STEP 1: 조기 중복 검사
        if self.guardian.is_url_known(url):
            return None

        # STEP 2: 표준 수집
        response = self.net_guard.robust_request(url, self.net_guard.get_rotated_headers())
        content = None
        if response:
            # 소스별 파싱 로직 (BS4, trafilatura 등)
            content = self._parse_content(response.text)

        # STEP 3: 실패 시 Total War
        if not content or len(content) < 임계값:
            tw_result = self.total_war.scrape_with_all_means(url)
            if tw_result:
                article = {
                    "title": tw_result['title'],
                    "date": info['date'],
                    "content": tw_result['content'],
                    "url": url,
                    "source": "new_source",
                    "wf_id": "wf_n",
                    "lang": "xx"
                }
                if self.guardian.save_article(article):
                    return article

        # STEP 4: 표준 수집 성공 시 저장
        if content:
            article = {
                "title": info['title'],
                "date": info['date'],
                "content": content,
                "url": url,
                "source": "new_source",
                "wf_id": "wf_n",
                "lang": "xx"
            }
            if self.guardian.save_article(article):
                return article

        return None

    def run(self, query):
        items = self.search_news(query)
        MAX_RETRY_ROUNDS = 3

        # 1차 수집
        failed = []
        for item in items:
            result = self.crawl_article(item)
            if result is None and not self.guardian.is_url_known(item['url']):
                failed.append(item)

        # 재시도 루프
        for round_num in range(1, MAX_RETRY_ROUNDS + 1):
            if not failed:
                break
            time.sleep(5 * round_num)
            still_failed = []
            for item in failed:
                result = self.crawl_article(item)
                if result is None and not self.guardian.is_url_known(item['url']):
                    still_failed.append(item)
            failed = still_failed
```

### 12.3 Step 3: 파이프라인 오케스트레이터 작성

```python
from total_war_scraper import TotalWarScraper

def main():
    sot_path = "database/{domain}/sot.jsonl"
    os.makedirs(os.path.dirname(sot_path), exist_ok=True)

    total_war = TotalWarScraper()

    try:
        for attempt in range(1, 4):  # 최대 3회
            if attempt > 1:
                time.sleep(30)
            try:
                # Phase별 크롤러 실행
                CrawlerA(sot_path, total_war).run(query)
                CrawlerB(sot_path, total_war).run(query)
                break
            except Exception:
                if attempt >= 3:
                    pass  # 수집된 데이터로 진행
    finally:
        total_war.close()
```

### 12.4 Step 4: 검증 체크리스트

- [ ] NetworkGuard가 5회 재시도 + UA 로테이션을 수행하는가?
- [ ] SOTGuardian이 Singleton으로 동작하는가?
- [ ] 이중 중복 검사(URL + 해시 지문)가 작동하는가?
- [ ] FileLock이 동시 쓰기를 방지하는가?
- [ ] TotalWarScraper가 표준 수집 실패 시에만 가동되는가?
- [ ] 브라우저 인스턴스가 finally에서 반드시 종료되는가?
- [ ] 3계층 재시도(L1-L2-L3)가 모두 동작하는가?
- [ ] JSONL에 4대 필수 필드가 모두 기록되는가?

---

## 13. 의존성 및 환경 구성

### 13.1 requirements.txt

```
requests>=2.31.0
httpx>=0.25.0
aiohttp>=3.9.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
fake-useragent>=1.4.0
selenium>=4.15.0
undetected-chromedriver>=3.5.0
pandas>=2.0.0
trafilatura>=1.6.0
filelock>=3.12.0
googlenewsdecoder>=0.1.7
```

> **참고**: `httpx`, `aiohttp`, `fake-useragent`, `pandas`는 현재 코드에서 직접 import하지 않으나, 확장 시 비동기 크롤링(httpx/aiohttp), UA 생성(fake-useragent), 데이터 분석(pandas)에 사용할 수 있도록 포함되어 있다.

### 13.2 각 패키지의 역할

| 패키지 | 사용처 | 역할 |
|--------|--------|------|
| `requests` | NetworkGuard | HTTP 요청의 기본 엔진 |
| `beautifulsoup4` | 모든 크롤러, TotalWarScraper | HTML 파싱 |
| `lxml` | BS4 파서 백엔드 | 고속 HTML/XML 파싱 |
| `trafilatura` | Google 크롤러, TotalWarScraper | 기사 본문 자동 추출 |
| `filelock` | SOTGuardian | 파일 수준 뮤텍스 락 |
| `selenium` | TotalWarScraper | WebDriverWait 등 유틸리티 |
| `undetected-chromedriver` | TotalWarScraper | 봇 탐지 우회 브라우저 |
| `googlenewsdecoder` | Google 크롤러 | Google News URL 디코딩 Tier B |

### 13.3 시스템 요구사항

- Python 3.10+
- Chrome 브라우저 (TotalWarScraper용, 버전 자동 매칭)
- 충분한 디스크 공간 (JSONL 누적 저장)

### 13.4 설치 명령

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 14. 확장 가이드: 새로운 소스 추가

### 14.1 RSS 기반 소스 추가 시

Google News 크롤러의 `_search_via_rss` 패턴을 따른다:

```python
def _search_via_rss(self, query):
    rss_url = f"https://example.com/rss?q={query}"
    response = self.net_guard.robust_request(rss_url, self._get_headers())
    if not response:
        return []
    soup = BeautifulSoup(response.text, 'xml')
    return [
        {"title": item.title.text, "url": item.link.text, "date": item.pubDate.text}
        for item in soup.select("item")
    ]
```

### 14.2 API 기반 소스 추가 시

NetworkGuard를 그대로 활용하되, 헤더에 API 키를 주입:

```python
def search_via_api(self, query):
    api_url = f"https://api.example.com/search?q={query}"
    headers = self.net_guard.get_rotated_headers({"Authorization": "Bearer ..."})
    response = self.net_guard.robust_request(api_url, headers)
    if not response:
        return []
    return response.json()['articles']
```

### 14.3 웹 크롤링 기반 소스 추가 시

Naver 크롤러의 `search_news` 패턴을 따른다. 핵심은 **페이지네이션 + 조기 종료 조건**:

```python
def search_news(self, query):
    urls = []
    consecutive_empty = 0

    for page in range(max_pages):
        response = self.net_guard.robust_request(url_for_page(page), headers)
        new_urls = self._extract_urls(response)

        if not new_urls:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
        else:
            consecutive_empty = 0
            urls.extend(new_urls)

    return list(set(urls))
```

### 14.4 새 소스에서 trafilatura 사용 시

trafilatura는 **범용 기사 본문 추출기**로, 대부분의 뉴스 사이트에서 작동한다:

```python
import trafilatura

content = trafilatura.extract(response.text)
# content가 None이거나 짧으면 → Total War로 폴백
```

trafilatura가 실패하는 경우:
- JavaScript 렌더링 필요 사이트 → TotalWarScraper가 처리
- 비표준 HTML 구조 → BS4 수동 파싱 추가

### 14.5 다국어 확장 시

GoogleEnNewsCrawler를 기반으로 RSS 파라미터만 변경:

```python
# 일본어
rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=ja&gl=JP&ceid=JP:ja"

# 중국어 (간체)
rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

# 독일어
rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=de&gl=DE&ceid=DE:de"
```

각 언어별 크롤러에서 `lang` 필드와 `wf_id`를 적절히 설정한다.

---

## 부록: 로깅 규칙

모든 모듈에서 동일한 로깅 형식을 사용한다:

```python
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
```

로그 레벨 사용 규칙:
- `INFO`: 정상 진행 (기사 발견, 수집 완료, 브라우저 초기화)
- `WARNING`: 폴백 가동, 재시도, 차단 감지
- `ERROR`: 수집 실패, 파싱 실패, 치명적 오류
