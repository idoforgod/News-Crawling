import os
import json
import hashlib
import logging
from filelock import FileLock, Timeout
from typing import Dict, Set

logger = logging.getLogger(__name__)

class SOTGuardian:
    """
    SOT의 무결성과 MECE(빠짐없이, 중복없이)를 지키는 전담 에이전트.
    FileLock을 통해 동시 다발적인 에이전트 쓰기에서도 파일 손상을 막습니다.
    """
    _instance = None

    def __new__(cls, sot_path: str = "database/news/news_sot.jsonl"):
        if cls._instance is None:
            cls._instance = super(SOTGuardian, cls).__new__(cls)
            cls._instance.sot_path = sot_path
            cls._instance.lock_path = f"{sot_path}.lock"
            # 초기화 시 한 번만 기존 SOT를 스캔하여 메모리에 적재 (속도 최적화)
            cls._instance.seen_content_hashes = cls._instance._load_sot_hashes()
        return cls._instance

    def _load_sot_hashes(self) -> Set[str]:
        hashes = set()
        urls = set()
        if os.path.exists(self.sot_path):
            with open(self.sot_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if 'title' in data and 'content' in data:
                            fingerprint = self._generate_fingerprint(data['title'], data['content'])
                            hashes.add(fingerprint)
                        if 'url' in data:
                            urls.add(data['url'])
                    except json.JSONDecodeError:
                        continue
        self.seen_urls = urls
        logger.info(f"[SOT Guardian] 초기화 완료: {len(hashes)}개 해시 지문, {len(urls)}개 URL 적재")
        return hashes

    def _generate_fingerprint(self, title: str, content: str) -> str:
        """제목과 본문 앞 100자를 활용해 내용 기반 고유 지문 생성"""
        safe_content = content[:100] if content else ""
        return hashlib.md5((title + safe_content).encode('utf-8')).hexdigest()

    def is_url_known(self, url: str) -> bool:
        """URL 기반 조기 중복 검사 — 크롤링 시작 전에 호출하여 불필요한 네트워크 요청 차단"""
        return url in self.seen_urls

    def is_duplicate(self, title: str, content: str) -> bool:
        """크롤러들이 본문 파싱 직후 즉각적인 중복 여부를 묻기 위해 사용"""
        fingerprint = self._generate_fingerprint(title, content)
        return fingerprint in self.seen_content_hashes

    def save_article(self, article: Dict) -> bool:
        """
        4대 필수 항목 검증, 내용 중복 재검증 후 Mutex Lock을 걸고 SOT에 안전하게 저장합니다.
        """
        # 1. 4대 절대 원칙 검사 (Schema Validation)
        required_keys = ["title", "date", "content", "url"]
        missing_keys = [k for k in required_keys if not article.get(k)]
        
        if missing_keys:
            logger.warning(f"[SOT Guardian] 필수 항목 누락 거부: {article.get('url')} (누락: {missing_keys})")
            return False

        # 2. 다중 에이전트에 의한 동시 접근 대비 내용 기반 지문 재검증
        fingerprint = self._generate_fingerprint(article['title'], article['content'])
        if fingerprint in self.seen_content_hashes:
            logger.warning(f"[SOT Guardian] 중복 데이터 병합 거부 (Semantic Duplication): {article['title'][:20]}")
            return False

        # 3. 데이터 일관성을 위한 기본 메타데이터 강제 주입
        if "source" not in article:
            article["source"] = "unknown"
        if "collected_at" not in article:
            from datetime import datetime
            article["collected_at"] = datetime.now().isoformat()
        
        # 언어와 워크플로우 ID 강제 (향후 WF1/WF2 식별용)
        if "lang" not in article:
            article["lang"] = "ko" # 기본값 한국어

        # 4. Atomic Write (동시성 제어)
        try:
            with FileLock(self.lock_path, timeout=10):
                # Lock 획득 후 파일에 쓰기
                with open(self.sot_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(article, ensure_ascii=False) + "\n")
                # 메모리에 지문 및 URL 등록 (동일 인스턴스를 공유하는 다른 에이전트들이 즉시 인지하도록)
                self.seen_content_hashes.add(fingerprint)
                if article.get('url'):
                    self.seen_urls.add(article['url'])
                return True
        except Timeout:
            logger.error(f"[SOT Guardian] Lock 획득 시간 초과. 저장 실패: {article['title'][:20]}")
            return False
        except Exception as e:
            logger.error(f"[SOT Guardian] SOT 쓰기 치명적 오류: {e}")
            return False
