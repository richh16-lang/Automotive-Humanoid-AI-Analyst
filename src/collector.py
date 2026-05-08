"""RSS 피드 + 웹 스크래핑으로 키워드 뉴스를 수집합니다."""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "feeds.yaml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class Article:
    title: str
    url: str
    source: str
    category: str
    published: Optional[datetime]
    summary: str = ""
    full_text: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "category": self.category,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
            "full_text": self.full_text[:3000],  # Claude 전송 시 크기 제한
            "matched_keywords": self.matched_keywords,
        }


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _contains_keyword(text: str, keywords: list[str]) -> list[str]:
    """대소문자 무시하여 매칭된 키워드 목록 반환."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def _parse_published(entry) -> Optional[datetime]:
    """feedparser entry에서 UTC datetime 추출."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import time as _time
                ts = _time.mktime(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    return None


def _is_recent(dt: Optional[datetime], hours: int = 26) -> bool:
    """수집 범위: 지난 N시간 이내."""
    if dt is None:
        return True  # 날짜 없으면 일단 포함
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    return dt >= cutoff


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_rss(url: str) -> feedparser.FeedParserDict:
    return feedparser.parse(url, request_headers=HEADERS)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def _fetch_html(url: str, timeout: int = 10) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_article_text(url: str) -> str:
    """기사 본문 텍스트 추출 (최대 3000자)."""
    try:
        html = _fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
            tag.decompose()
        # 일반적인 기사 본문 태그 우선
        for selector in ["article", "main", ".article-body", ".post-content", "#content"]:
            block = soup.select_one(selector)
            if block:
                text = block.get_text(separator=" ", strip=True)
                return re.sub(r"\s+", " ", text)[:3000]
        return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))[:3000]
    except Exception as e:
        logger.debug("본문 추출 실패 %s: %s", url, e)
        return ""


def collect_from_rss(feed_cfg: dict, keywords: list[str], hours: int = 26) -> list[Article]:
    """단일 RSS 피드에서 키워드 매칭 기사 수집."""
    articles: list[Article] = []
    try:
        feed = _fetch_rss(feed_cfg["url"])
    except Exception as e:
        logger.warning("RSS 수집 실패 [%s]: %s", feed_cfg["name"], e)
        return articles

    for entry in feed.entries:
        title = getattr(entry, "title", "")
        summary = getattr(entry, "summary", "")
        link = getattr(entry, "link", "")
        published = _parse_published(entry)

        if not _is_recent(published, hours):
            continue

        matched = _contains_keyword(title + " " + summary, keywords)
        if not matched:
            continue

        full_text = _extract_article_text(link) if link else ""

        articles.append(
            Article(
                title=title,
                url=link,
                source=feed_cfg["name"],
                category=feed_cfg.get("category", "general"),
                published=published,
                summary=BeautifulSoup(summary, "lxml").get_text()[:500],
                full_text=full_text,
                matched_keywords=matched,
            )
        )
        logger.debug("수집: [%s] %s", feed_cfg["name"], title[:60])

    return articles


def collect_from_scrape(site_cfg: dict, keywords: list[str]) -> list[Article]:
    """CSS 셀렉터 기반 웹 스크래핑."""
    articles: list[Article] = []
    try:
        html = _fetch_html(site_cfg["url"])
        soup = BeautifulSoup(html, "lxml")
        links = soup.select(site_cfg.get("selector", "article h2 a"))
        for a in links[:20]:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not href.startswith("http"):
                from urllib.parse import urljoin
                href = urljoin(site_cfg["url"], href)
            matched = _contains_keyword(title, keywords)
            if not matched:
                continue
            articles.append(
                Article(
                    title=title,
                    url=href,
                    source=site_cfg["name"],
                    category=site_cfg.get("category", "general"),
                    published=None,
                    matched_keywords=matched,
                )
            )
    except Exception as e:
        logger.warning("스크래핑 실패 [%s]: %s", site_cfg["name"], e)
    return articles


def deduplicate(articles: list[Article]) -> list[Article]:
    """URL 기준 중복 제거."""
    seen: set[str] = set()
    result: list[Article] = []
    for art in articles:
        key = art.url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            result.append(art)
    return result


def run_collection(hours: int = 26) -> list[Article]:
    """전체 수집 파이프라인 실행."""
    cfg = _load_config()
    keywords: list[str] = cfg["keywords"]
    all_articles: list[Article] = []

    logger.info("RSS 피드 수집 시작 (%d개 피드)", len(cfg["rss_feeds"]))
    for feed_cfg in cfg["rss_feeds"]:
        arts = collect_from_rss(feed_cfg, keywords, hours)
        logger.info("  [%s] %d건", feed_cfg["name"], len(arts))
        all_articles.extend(arts)

    logger.info("웹 스크래핑 시작 (%d개 사이트)", len(cfg.get("scrape_sites", [])))
    for site_cfg in cfg.get("scrape_sites", []):
        arts = collect_from_scrape(site_cfg, keywords)
        logger.info("  [%s] %d건", site_cfg["name"], len(arts))
        all_articles.extend(arts)

    unique = deduplicate(all_articles)
    logger.info("수집 완료: 총 %d건 (중복 제거 후)", len(unique))
    return unique
