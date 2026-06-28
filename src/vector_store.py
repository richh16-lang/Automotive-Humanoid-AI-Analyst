"""
Qdrant Vector DB — 분석 기억 저장소.
매일 분석 결과를 섹션 단위로 벡터화·저장하고,
오늘 기사와 의미적으로 유사한 과거 인사이트를 검색합니다.

환경변수:
  QDRANT_URL     : Qdrant Cloud 클러스터 URL (필수)
  QDRANT_API_KEY : Qdrant Cloud API 키 (필수)
  GEMINI_API_KEY : 임베딩용 (기존 키 재사용)
"""
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

_COLLECTION = "news_analyzer_memory"
_VECTOR_DIM = 1024  # Mistral mistral-embed 고정 차원
_EMBED_MODEL = "mistral-embed"


# ──────────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────────

def _has_qdrant() -> bool:
    return bool(os.environ.get("QDRANT_URL", "").strip())


def _get_client():
    from qdrant_client import QdrantClient
    url     = os.environ["QDRANT_URL"].strip()
    api_key = os.environ.get("QDRANT_API_KEY", "").strip() or None
    return QdrantClient(url=url, api_key=api_key)


def _embed(text: str, task: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    from mistralai import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    resp = client.embeddings.create(
        model=_EMBED_MODEL,
        inputs=[text[:8000]],
    )
    return resp.data[0].embedding


def _point_id(date_str: str, section_title: str) -> int:
    """date + section 조합으로 결정론적 uint64 ID 생성 (upsert 멱등성 보장)."""
    raw = f"{date_str}|{section_title}".encode()
    return int.from_bytes(hashlib.md5(raw).digest()[:8], "big")


def _ensure_collection() -> None:
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
    client   = _get_client()
    existing = {c.name for c in client.get_collections().collections}
    if _COLLECTION not in existing:
        client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
        )
        logger.info("[Qdrant] 컬렉션 생성: %s", _COLLECTION)
    client.create_payload_index(
        collection_name=_COLLECTION,
        field_name="date",
        field_schema=PayloadSchemaType.KEYWORD,
    )


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def index_daily_report(analysis: dict) -> int:
    """
    오늘 분석 결과를 섹션 단위로 Qdrant에 저장.
    이미 저장된 날짜는 upsert로 덮어씀.
    반환값: 저장된 포인트 수
    """
    if not _has_qdrant():
        return 0

    from qdrant_client.models import PointStruct

    sections = analysis.get("sections", {})
    date_str = analysis.get("date", "")
    keywords = analysis.get("keywords_found", [])[:20]

    if not sections or not date_str:
        logger.warning("[Qdrant] 인덱싱 스킵 — sections 또는 date 없음")
        return 0

    _ensure_collection()
    client = _get_client()

    points = []
    for section_title, content in sections.items():
        if not content or len(content) < 50:
            continue

        text_to_embed = f"{section_title}\n\n{content}"
        try:
            vector = _embed(text_to_embed)
        except Exception as e:
            logger.warning("[Qdrant] 임베딩 실패 (%s): %s", section_title, e)
            continue

        points.append(PointStruct(
            id=_point_id(date_str, section_title),
            vector=vector,
            payload={
                "date":          date_str,
                "section_title": section_title,
                "content":       content[:3000],
                "keywords":      keywords,
            },
        ))

    if points:
        client.upsert(collection_name=_COLLECTION, points=points)
        logger.info("[Qdrant] %d개 섹션 인덱싱 완료 (%s)", len(points), date_str)

    return len(points)


def search_memory(query: str, top_k: int = 5, exclude_date: str | None = None) -> list[dict]:
    """
    쿼리와 의미적으로 유사한 과거 인사이트 검색.
    반환값: [{date, section_title, content, score}, ...]
    """
    if not _has_qdrant():
        return []

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = _get_client()
        vector = _embed(query[:2000], task="RETRIEVAL_QUERY")

        search_filter = None
        if exclude_date:
            search_filter = Filter(
                must_not=[FieldCondition(key="date", match=MatchValue(value=exclude_date))]
            )

        results = client.query_points(
            collection_name=_COLLECTION,
            query=vector,
            limit=top_k,
            query_filter=search_filter,
        )

        return [
            {
                "date":          r.payload.get("date", ""),
                "section_title": r.payload.get("section_title", ""),
                "content":       r.payload.get("content", ""),
                "score":         round(r.score, 3),
            }
            for r in results.points
        ]
    except Exception as e:
        import traceback
        logger.warning("[Qdrant] 검색 실패: %s\n%s", e, traceback.format_exc())
        return []


def build_memory_context(articles_summary: str, date_str: str) -> str:
    """
    오늘 기사 핵심어로 관련 과거 기억 검색 → 프롬프트 주입용 텍스트 반환.
    Qdrant 미설정 시 빈 문자열 반환 (파이프라인 중단 없음).
    """
    if not _has_qdrant():
        return ""

    memories = search_memory(articles_summary[:2000], top_k=5, exclude_date=date_str)
    if not memories:
        return ""

    lines = [
        "## 📚 과거 관련 인사이트 (참고용)",
        "오늘 기사와 의미적으로 유사한 과거 보고서 섹션입니다.",
        "트렌드 연속성·기업 포지션 변화·컨텍스트 이상 감지에 활용하세요.\n",
    ]
    for m in memories:
        lines.append(f"[{m['date']} | {m['section_title']}]")
        preview = m["content"][:600]
        if len(m["content"]) > 600:
            preview += "..."
        lines.append(preview)
        lines.append("")

    lines.append("---\n")
    return "\n".join(lines)
