import time
import random
import requests
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# User-Agent 로테이션 풀 — 차단 우회용
_UA_POOL: List[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


class NetworkGuard:
    """
    7대 원칙(URL 유효성, 네트워크, 인증, 응답코드, 파싱, 속도제한, 로깅)을
    수행하며 최적의 요청 전략을 결정하는 지능형 가드.
    차단 감지 시 User-Agent 로테이션으로 실시간 우회.
    """
    def __init__(self):
        self.max_retries = 5
        self.base_delay = 2.0
        self._ua_index = random.randint(0, len(_UA_POOL) - 1)

    def get_rotated_headers(self, extra_headers: Dict = None) -> Dict:
        """매 요청마다 User-Agent를 순환하여 차단 우회"""
        self._ua_index = (self._ua_index + 1) % len(_UA_POOL)
        headers = {"User-Agent": _UA_POOL[self._ua_index]}
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def validate_url(self, url: str) -> bool:
        """1. URL 유효성 검증"""
        parsed = urllib.parse.urlparse(url)
        return all([parsed.scheme, parsed.netloc])

    def robust_request(self, url: str, headers: Dict = None) -> Optional[requests.Response]:
        if not self.validate_url(url):
            logger.error(f"[NetworkGuard] 1. 유효하지 않은 URL: {url}")
            return None

        for attempt in range(self.max_retries):
            try:
                # 재시도 시 UA 로테이션 적용 (차단 우회)
                req_headers = self.get_rotated_headers(headers) if attempt > 0 else (headers or self.get_rotated_headers())

                # 2. 네트워크 연결 및 6. 속도 제한(지연) 처리
                if attempt > 0:
                    delay = self.base_delay * (attempt + 1) + random.uniform(1, 3)
                    logger.info(f"[NetworkGuard] 6. 재시도 {attempt}회차 지연: {delay:.1f}s (UA 로테이션 적용)")
                    time.sleep(delay)

                response = requests.get(url, headers=req_headers, timeout=15, allow_redirects=True)

                # 4. 응답 코드 분석
                status = response.status_code
                if status == 200:
                    return response

                # 3. 인증/권한 차단 감지 → UA 로테이션으로 우회
                if status in [401, 403, 407]:
                    logger.warning(f"[NetworkGuard] 3. 차단 감지({status}). UA 로테이션 후 재시도: {url}")
                elif status == 429:
                    wait_time = min(10 * (attempt + 1), 60)
                    logger.warning(f"[NetworkGuard] 6. 속도 제한(429) 감지. {wait_time}s 대기 후 재시도.")
                    time.sleep(wait_time)
                else:
                    logger.error(f"[NetworkGuard] 4. 비정상 응답({status}): {url}")

            except requests.exceptions.ConnectionError:
                logger.error(f"[NetworkGuard] 2. 서버 연결 실패: {url}")
            except Exception as e:
                # 7. 상세 에러 로깅
                logger.error(f"[NetworkGuard] 7. 예외 발생: {str(e)} | URL: {url}")

        return None
