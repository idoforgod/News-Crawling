import os
import json
import time
import requests
import logging
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from sot_guardian import SOTGuardian
from network_guard import NetworkGuard
from total_war_scraper import TotalWarScraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 실패 기사 최대 재시도 라운드 수
MAX_RETRY_ROUNDS = 3


class NaverNewsCrawler:
    def __init__(self, sot_path: str = "database/news/news_sot.jsonl", total_war: TotalWarScraper = None):
        self.guardian = SOTGuardian(sot_path)
        self.net_guard = NetworkGuard()
        self.total_war = total_war or TotalWarScraper()
        self.session = requests.Session()

    def _get_headers(self) -> Dict:
        return self.net_guard.get_rotated_headers()

    def search_news(self, query: str) -> List[str]:
        urls = []
        page = 0
        consecutive_empty = 0
        while page < 10:  # 최대 100개 기사 (일간 스캔에 충분)
            start = page * 10 + 1
            search_url = f"https://search.naver.com/search.naver?where=news&query={query}&pd=1&start={start}"

            # 7대 원칙 적용된 요청
            response = self.net_guard.robust_request(search_url, self._get_headers())
            if not response: break

            try:
                # 5. 파싱 오류 검사
                soup = BeautifulSoup(response.text, 'lxml')
                links = soup.select("a")
                found_new = False
                for link in links:
                    href = link.get('href', '')
                    if "n.news.naver.com/mnews/article" in href:
                        clean_url = href.split("?")[0]
                        if clean_url not in urls:
                            urls.append(clean_url)
                            found_new = True
                if not found_new:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        logger.info(f"[Naver] 연속 {consecutive_empty}페이지 신규 기사 없음 → 조기 종료")
                        break
                else:
                    consecutive_empty = 0
                page += 1
            except Exception as e:
                logger.error(f"[Naver] 5. 파싱 실패: {e}")
                break

        return list(set(urls))

    def crawl_article(self, url: str) -> Optional[Dict]:
        # P1: URL 기반 조기 중복 검사 — 네트워크 요청 전에 차단
        if self.guardian.is_url_known(url):
            logger.info(f"[SOT Guardian] URL already in SOT, skipping: {url}")
            return None

        # 1-4단계 및 6단계 원칙 적용
        response = self.net_guard.robust_request(url, self._get_headers())

        article_data = None
        if response:
            try:
                soup = BeautifulSoup(response.text, 'lxml')
                title_elem = soup.select_one("#title_area span, .media_end_head_headline")
                title = title_elem.get_text(strip=True) if title_elem else ""

                date_elem = soup.select_one(".media_end_head_info_datestamp_time, .t11")
                date_str = date_elem.get_text(strip=True) if date_elem else ""

                content_elem = soup.select_one("#dic_area, #newsct_article")
                if content_elem:
                    for unwanted in content_elem.select(".article_footer, .img_desc, script, style"): unwanted.decompose()
                    content = content_elem.get_text(strip=True)
                    if len(content) > 200:
                        article_data = {"title": title, "date": date_str, "content": content}
            except: pass

        # [절대 기준] 수집 실패 시 Total War 가동
        if not article_data:
            tw_result = self.total_war.scrape_with_all_means(url)
            if tw_result:
                article_data = {
                    "title": tw_result['title'],
                    "date": datetime.now().strftime("%Y-%m-%d"),  # 일자 누락 시 오늘 날짜
                    "content": tw_result['content']
                }

        if article_data:
            article = {**article_data, "url": url, "source": "naver", "wf_id": "wf1", "lang": "ko"}
            if self.guardian.save_article(article):
                return article

        logger.error(f"❌ [MISSION FAIL] Naver 수집 실패 (재시도 대상): {url}")
        return None

    def run(self, query: str):
        urls = self.search_news(query)
        logger.info(f"[Naver] 발견된 기사 URL: {len(urls)}개")

        # 1차 수집
        failed_urls = []
        for url in urls:
            result = self.crawl_article(url)
            if result is None and not self.guardian.is_url_known(url):
                failed_urls.append(url)

        # 실패 기사 재시도 (최대 MAX_RETRY_ROUNDS 라운드)
        for round_num in range(1, MAX_RETRY_ROUNDS + 1):
            if not failed_urls:
                break
            logger.warning(f"🔄 [Naver] 재시도 라운드 {round_num}/{MAX_RETRY_ROUNDS}: {len(failed_urls)}개 실패 기사")
            time.sleep(5 * round_num)  # 라운드마다 대기 시간 증가
            still_failed = []
            for url in failed_urls:
                result = self.crawl_article(url)
                if result is None and not self.guardian.is_url_known(url):
                    still_failed.append(url)
            failed_urls = still_failed

        if failed_urls:
            logger.error(f"⚠️ [Naver] 최종 미수집 기사: {len(failed_urls)}개")
        else:
            logger.info(f"✅ [Naver] 모든 기사 수집 완료")
