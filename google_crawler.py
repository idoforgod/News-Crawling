import os
import json
import logging
import base64
import re
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import trafilatura
from typing import List, Dict, Optional
from sot_guardian import SOTGuardian
from network_guard import NetworkGuard
from total_war_scraper import TotalWarScraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 실패 기사 최대 재시도 라운드 수
MAX_RETRY_ROUNDS = 3


class GoogleNewsCrawler:
    def __init__(self, sot_path: str = "database/news/news_sot.jsonl", total_war: TotalWarScraper = None):
        self.guardian = SOTGuardian(sot_path)
        self.net_guard = NetworkGuard()
        self.total_war = total_war or TotalWarScraper()

    def _get_headers(self) -> Dict:
        return self.net_guard.get_rotated_headers()

    def decode_url(self, google_url: str) -> str:
        """2-tier Google News URL 디코딩: protobuf 파싱 → googlenewsdecoder 폴백"""
        # Tier A: 오프라인 protobuf 파싱
        try:
            match = re.search(r'articles/([^?]+)', google_url)
            if not match:
                return google_url
            encoded = match.group(1)
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            raw = base64.urlsafe_b64decode(encoded)

            # protobuf 파싱: 각 필드에서 URL 추출
            urls = []
            i = 0
            while i < len(raw):
                if i + 1 >= len(raw):
                    break
                tag = raw[i]
                wire_type = tag & 0x07
                if wire_type == 2:  # length-delimited (string)
                    i += 1
                    length = 0
                    shift = 0
                    while i < len(raw):
                        b = raw[i]
                        length |= (b & 0x7F) << shift
                        shift += 7
                        i += 1
                        if not (b & 0x80):
                            break
                    if i + length <= len(raw):
                        try:
                            field_str = raw[i:i+length].decode('utf-8', errors='ignore')
                            if field_str.startswith('http'):
                                urls.append(field_str)
                        except Exception:
                            pass
                    i += length
                elif wire_type == 0:  # varint
                    i += 1
                    while i < len(raw) and raw[i] & 0x80:
                        i += 1
                    i += 1
                else:
                    break
            if urls:
                result = max(urls, key=len)
                logger.info(f"[Google] Protobuf 디코딩 성공: {result[:60]}...")
                return result
        except Exception:
            pass

        # Tier B: googlenewsdecoder 라이브러리 폴백
        try:
            from googlenewsdecoder import new_decoderv1
            decoded = new_decoderv1(google_url, interval=1)
            if decoded and decoded.get("decoded_url"):
                logger.info(f"[Google] googlenewsdecoder 성공: {decoded['decoded_url'][:60]}...")
                return decoded["decoded_url"]
        except Exception as e:
            logger.warning(f"[Google] googlenewsdecoder 실패: {e}")

        return google_url

    def search_news(self, query: str) -> List[Dict]:
        """RSS 기반 검색 → 실패 시 웹 크롤링 폴백"""
        articles = self._search_via_rss(query)
        if not articles:
            logger.warning("[Google] RSS 수집 실패 → 웹 크롤링 폴백 가동")
            articles = self._search_via_web(query)
        return articles

    def _search_via_rss(self, query: str) -> List[Dict]:
        search_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=ko&gl=KR&ceid=KR:ko"
        response = self.net_guard.robust_request(search_url, self._get_headers())

        articles = []
        if response:
            try:
                soup = BeautifulSoup(response.text, 'xml')
                for item in soup.select("item"):
                    articles.append({"title": item.title.text, "google_url": item.link.text, "date": item.pubDate.text})
            except Exception as e:
                logger.error(f"[Google] RSS 파싱 실패: {e}")
        return articles

    def _search_via_web(self, query: str) -> List[Dict]:
        """RSS 실패 시 Google News 웹 페이지 직접 크롤링"""
        search_url = f"https://news.google.com/search?q={query}+when:1d&hl=ko&gl=KR&ceid=KR:ko"
        tw_result = self.total_war.scrape_with_all_means(search_url)
        if not tw_result:
            # Total War도 실패 시 일반 Google 검색으로 폴백
            search_url = f"https://www.google.com/search?q={query}&tbm=nws&tbs=qdr:d"
            response = self.net_guard.robust_request(search_url, self._get_headers())
            if not response:
                return []
            html = response.text
        else:
            return []  # Total War은 page_source를 반환하지 않으므로, 아래 로직으로 진행

        articles = []
        try:
            soup = BeautifulSoup(html, 'lxml')
            for link in soup.select("a[href*='/url?']"):
                href = link.get("href", "")
                url_match = re.search(r'/url\?q=(https?://[^&]+)', href)
                if url_match:
                    real_url = url_match.group(1)
                    title = link.get_text(strip=True) or ""
                    if title and len(title) > 5:
                        articles.append({
                            "title": title,
                            "google_url": real_url,
                            "date": datetime.now().strftime("%Y-%m-%d")
                        })
            logger.info(f"[Google] 웹 크롤링 폴백으로 {len(articles)}개 기사 발견")
        except Exception as e:
            logger.error(f"[Google] 웹 크롤링 폴백 파싱 실패: {e}")
        return articles

    def crawl_article(self, info: Dict) -> Optional[Dict]:
        # google_url이 이미 실제 URL인 경우 (웹 크롤링 폴백) decode 불필요
        if 'google_url' in info and 'news.google.com' in info['google_url']:
            url = self.decode_url(info['google_url'])
        else:
            url = info.get('google_url', info.get('url', ''))

        # P1: URL 기반 조기 중복 검사 — 네트워크 요청 전에 차단
        if self.guardian.is_url_known(url):
            logger.info(f"[SOT Guardian] URL already in SOT, skipping: {url}")
            return None

        # 1차 시도: 표준 고속 추출
        response = self.net_guard.robust_request(url, self._get_headers())
        content = trafilatura.extract(response.text) if response else None

        # 2차 시도: 실패 시 Total War 가동
        if not content or len(content) < 300:
            tw_result = self.total_war.scrape_with_all_means(url)
            if tw_result:
                article = {
                    "title": tw_result['title'], "date": info['date'], "content": tw_result['content'],
                    "url": url, "source": "google", "wf_id": "wf1", "lang": "ko"
                }
                if self.guardian.save_article(article): return article

        if content:
            article = {"title": info['title'], "date": info['date'], "content": content, "url": url, "source": "google", "wf_id": "wf1", "lang": "ko"}
            if self.guardian.save_article(article): return article

        logger.error(f"❌ [MISSION FAIL] Google 수집 실패 (재시도 대상): {url}")
        return None

    def run(self, query: str):
        articles = self.search_news(query)
        logger.info(f"[Google] 발견된 기사: {len(articles)}개")

        # 1차 수집
        failed_infos = []
        for info in articles:
            result = self.crawl_article(info)
            url = self.decode_url(info.get('google_url', ''))
            if result is None and not self.guardian.is_url_known(url):
                failed_infos.append(info)

        # 실패 기사 재시도 (최대 MAX_RETRY_ROUNDS 라운드)
        for round_num in range(1, MAX_RETRY_ROUNDS + 1):
            if not failed_infos:
                break
            logger.warning(f"🔄 [Google] 재시도 라운드 {round_num}/{MAX_RETRY_ROUNDS}: {len(failed_infos)}개 실패 기사")
            time.sleep(5 * round_num)
            still_failed = []
            for info in failed_infos:
                result = self.crawl_article(info)
                url = self.decode_url(info.get('google_url', ''))
                if result is None and not self.guardian.is_url_known(url):
                    still_failed.append(info)
            failed_infos = still_failed

        if failed_infos:
            logger.error(f"⚠️ [Google] 최종 미수집 기사: {len(failed_infos)}개")
        else:
            logger.info(f"✅ [Google] 모든 기사 수집 완료")
