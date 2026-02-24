import logging
from bs4 import BeautifulSoup
import trafilatura
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class TotalWarScraper:
    """
    모든 표준 크롤링이 실패했을 때 최후의 수단으로 가동.
    브라우저 에뮬레이션을 총동원하여 '반드시' 임무 완수.
    브라우저 인스턴스를 재사용하여 반복 호출 시 성능 최적화.
    """
    def __init__(self):
        self.driver = None
        self._consecutive_failures = 0
        self._MAX_FAILURES_BEFORE_RESTART = 3

    def _init_stealth_browser(self):
        import undetected_chromedriver as uc
        options = uc.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        return uc.Chrome(options=options)

    def _ensure_browser(self):
        """브라우저 lazy init + 연속 실패 시 재생성"""
        if self.driver and self._consecutive_failures >= self._MAX_FAILURES_BEFORE_RESTART:
            logger.warning("[TOTAL WAR] 연속 실패 한도 도달, 브라우저 재시작")
            self._kill_browser()

        if not self.driver:
            logger.info("[TOTAL WAR] 브라우저 인스턴스 초기화")
            self.driver = self._init_stealth_browser()
            self._consecutive_failures = 0

    def _kill_browser(self):
        """내부 브라우저 정리"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def close(self):
        """외부에서 명시적으로 브라우저를 종료할 때 사용"""
        logger.info("[TOTAL WAR] 브라우저 명시적 종료")
        self._kill_browser()

    def scrape_with_all_means(self, url: str) -> Optional[Dict]:
        """
        BS4 -> Trafilatura -> Browser Emulation 순으로 모든 무기 사용
        브라우저 인스턴스를 재사용하여 성능 최적화.
        """
        logger.warning(f"🚀 [TOTAL WAR] 직접 접속 및 브라우저 에뮬레이션 가동: {url}")

        try:
            self._ensure_browser()
            self.driver.get(url)

            # WebDriverWait: 5초 내 콘텐츠 감지 시 조기 탈출
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.TAG_NAME, "p"))
                )
            except Exception:
                pass  # 타임아웃이어도 진행 (일부 사이트는 p 태그 없이 구성)

            html = self.driver.page_source
            soup = BeautifulSoup(html, 'lxml')

            # 1. Trafilatura 재시도 (렌더링된 HTML 기반)
            content = trafilatura.extract(html)

            # 2. 실패 시 텍스트 밀도 기반 강제 추출
            if not content or len(content) < 300:
                p_tags = soup.select("p")
                content = "\n".join([p.get_text(strip=True) for p in p_tags if len(p.get_text(strip=True)) > 20])

            title = ""
            title_candidates = [soup.title.string if soup.title else None, soup.find("h1"), soup.find("h2")]
            for cand in title_candidates:
                if cand:
                    title = cand.get_text(strip=True) if hasattr(cand, 'get_text') else str(cand)
                    break

            if content and len(content) > 200:
                logger.info(f"✅ [TOTAL WAR] 임무 완수: {title[:20]}")
                self._consecutive_failures = 0
                return {"title": title, "content": content}

            self._consecutive_failures += 1
            return None

        except Exception as e:
            logger.error(f"[TOTAL WAR] 최후의 수단마저 실패: {e}")
            self._consecutive_failures += 1
            return None
