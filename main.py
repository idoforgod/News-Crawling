import logging
import os
import json
import time
from datetime import datetime
from naver_crawler import NaverNewsCrawler
from google_crawler import GoogleNewsCrawler
from google_en_crawler import GoogleEnNewsCrawler
from sot_guardian import SOTGuardian
from total_war_scraper import TotalWarScraper

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 전체 파이프라인 최대 재시도 횟수 (각 크롤러 내부 재시도와 별도)
MAX_PIPELINE_RETRIES = 3
PIPELINE_RETRY_DELAY = 30  # 초


def main():
    query_ko = "인공지능 에이전트"
    query_en = "AI Agents OR Agentic AI"  # 글로벌 수집을 위한 영문 확장 쿼리
    sot_path = "database/news/news_sot.jsonl"
    archive_dir = "database/news/archive"

    # SOT 디렉토리 자동 생성
    os.makedirs(os.path.dirname(sot_path), exist_ok=True)

    logger.info("=" * 50)
    logger.info("📡 [MULTI-WORKFLOW] 통합 환경스캐닝 엔진 가동")
    logger.info("=" * 50)

    # 공유 TotalWarScraper 인스턴스 (브라우저 재사용으로 성능 최적화)
    total_war = TotalWarScraper()

    try:
        for pipeline_attempt in range(1, MAX_PIPELINE_RETRIES + 1):
            if pipeline_attempt > 1:
                logger.warning(f"🔄 [PIPELINE] 전체 재시도 {pipeline_attempt}/{MAX_PIPELINE_RETRIES} (대기 {PIPELINE_RETRY_DELAY}s)")
                time.sleep(PIPELINE_RETRY_DELAY)

            try:
                # [WF1] 국내 뉴스 수집 단계
                logger.info("🟢 [PHASE 1] 국내 환경스캐닝(WF1) 시작")
                naver = NaverNewsCrawler(sot_path=sot_path, total_war=total_war)
                naver.run(query_ko)
                google_kr = GoogleNewsCrawler(sot_path=sot_path, total_war=total_war)
                google_kr.run(query_ko)
                logger.info("✅ PHASE 1 완료.")

                # [WF2] 글로벌 뉴스 수집 단계
                logger.info("🔵 [PHASE 2] 글로벌 환경스캐닝(WF2) 시작")
                google_en = GoogleEnNewsCrawler(sot_path=sot_path, total_war=total_war)
                en_articles = google_en.run(query_en)

                if en_articles:
                    logger.info(f"📍 {len(en_articles)}개의 영문 기사가 확보되었습니다. 울트라 지능의 현지화 작업을 대기합니다.")
                    for art in en_articles:
                        print(f"TRANSLATION_REQUIRED: {art['url']}|{art['title']}")

                logger.info("✅ PHASE 2 원천 데이터 확보 완료.")
                break  # 성공 시 반복 종료

            except Exception as e:
                logger.error(f"❌ [PIPELINE] 파이프라인 오류 발생: {e}")
                if pipeline_attempt >= MAX_PIPELINE_RETRIES:
                    logger.error(f"❌ [PIPELINE] 최대 재시도 도달. 수집된 데이터로 진행합니다.")

        # [PHASE 3] 통합 보고서 산출은 모든 SOT 적재가 끝난 후 에이전트에 의해 수동/자동 호출됩니다.
        logger.info("🏁 모든 워크플로우 임무를 완료했습니다. 통합 보고서 생성을 준비하십시오.")
    finally:
        # 브라우저 인스턴스 명시적 종료 (리소스 누수 방지)
        total_war.close()


if __name__ == "__main__":
    main()
