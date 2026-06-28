"""
Entity Tracker — 키워드 언급량 일별 추적 및 급증 감지.
Qdrant에 일별 카운트를 저장하고 14일 평균 대비 급증을 감지합니다.
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_ENTITY_COLLECTION = "entity_counts"
_DUMMY_VECTOR = [0.0, 0.0, 0.0, 0.0]  # 스토리지 전용 (벡터 검색 미사용)

# 추적 대상 엔티티 — 키: 표시명, 값: 매칭 키워드 목록 (소문자)
TRACKED_ENTITIES: dict[str, list[str]] = {
    # ── 자동차 OEM ────────────────────────────────────────────
    "Tesla":           ["tesla", "fsd"],
    "BMW":             ["bmw"],
    "Toyota":          ["toyota", "lexus"],
    "Hyundai":         ["hyundai", "kia", "현대", "기아"],
    "GM":              ["general motors", " gm "],
    "Ford":            ["ford"],
    "BYD":             ["byd"],
    # ── 자동차 Tier1 ─────────────────────────────────────────
    "Bosch":           ["bosch"],
    "Continental":     ["continental"],
    "Denso":           ["denso"],
    # ── 자동차 SoC ───────────────────────────────────────────
    "NVIDIA":          ["nvidia", "nvidia thor", "nvidia orin", "nvidia drive"],
    "Qualcomm":        ["qualcomm", "snapdragon", "sa8295", "sa8775"],
    "Mobileye":        ["mobileye"],
    "Waymo":           ["waymo"],
    # ── 휴머노이드 업체 ────────────────────────────────────────
    "Figure AI":       ["figure ai", "figure robot"],
    "Boston Dynamics": ["boston dynamics", "atlas"],
    "Agility Robotics":["agility robotics", "digit robot"],
    "1X Technologies": ["1x technologies", "1x robotics"],
    "Unitree":         ["unitree"],
    "Apptronik":       ["apptronik"],
    "Sanctuary AI":    ["sanctuary ai"],
    "Physical Intelligence": ["physical intelligence", "pi zero"],
    # ── 메모리·스토리지 ────────────────────────────────────────
    "Samsung":         ["samsung"],
    "SK하이닉스":      ["sk hynix", "hynix", "sk하이닉스"],
    "Micron":          ["micron"],
    "Kioxia":          ["kioxia"],
    "HBM":             ["hbm"],
    "CXL":             ["cxl"],
    "UFS":             ["ufs 4", "ufs 5", "ufs4", "ufs5"],
}

SPIKE_THRESHOLD = 2.0   # 평균 대비 N배 이상 → 급증
SPIKE_MIN_COUNT = 2     # 최소 언급 횟수 (노이즈 제거)
LOOKBACK_DAYS   = 14    # 비교 기준 일수


def _has_qdrant() -> bool:
    return bool(os.environ.get("QDRANT_URL", "").strip())


def _get_client():
    from qdrant_client import QdrantClient
    url     = os.environ["QDRANT_URL"].strip()
    api_key = os.environ.get("QDRANT_API_KEY", "").strip() or None
    return QdrantClient(url=url, api_key=api_key)


def _date_point_id(date_str: str) -> int:
    raw = f"entity|{date_str}".encode()
    return int.from_bytes(hashlib.md5(raw).digest()[:8], "big")


def _ensure_collection() -> None:
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
    client   = _get_client()
    existing = {c.name for c in client.get_collections().collections}
    if _ENTITY_COLLECTION not in existing:
        client.create_collection(
            collection_name=_ENTITY_COLLECTION,
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        logger.info("[EntityTracker] 컬렉션 생성")
    client.create_payload_index(
        collection_name=_ENTITY_COLLECTION,
        field_name="date",
        field_schema=PayloadSchemaType.KEYWORD,
    )


def count_mentions(articles: list) -> dict[str, int]:
    """기사 전체 텍스트에서 엔티티 언급 횟수 카운트."""
    full_text = " ".join(
        f"{getattr(a, 'title', '')} {getattr(a, 'full_text', '')} {getattr(a, 'summary', '')}"
        for a in articles
    ).lower()

    return {
        entity: sum(full_text.count(kw) for kw in keywords)
        for entity, keywords in TRACKED_ENTITIES.items()
        if sum(full_text.count(kw) for kw in keywords) > 0
    }


def _load_history() -> list[dict]:
    """Qdrant에서 최근 LOOKBACK_DAYS일 카운트 로드."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny
    past_dates = [
        (datetime.now(KST) - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(1, LOOKBACK_DAYS + 1)
    ]
    client  = _get_client()
    results = client.scroll(
        collection_name=_ENTITY_COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="date", match=MatchAny(any=past_dates))]
        ),
        limit=LOOKBACK_DAYS,
        with_payload=True,
    )
    return [p.payload for p in results[0]]


def detect_spikes(today_counts: dict) -> list[dict]:
    """14일 평균 대비 급증 엔티티 감지."""
    try:
        history = _load_history()
    except Exception as e:
        logger.warning("[EntityTracker] 히스토리 로드 실패: %s", e)
        return []

    spikes = []
    for entity, today in today_counts.items():
        if today < SPIKE_MIN_COUNT:
            continue
        past = [h.get("counts", {}).get(entity, 0) for h in history]
        avg  = sum(past) / len(past) if past else 0

        if avg == 0 and today >= SPIKE_MIN_COUNT:
            spikes.append({"entity": entity, "today": today, "avg": 0,
                           "ratio": None, "type": "신규 등장"})
        elif avg > 0 and today >= avg * SPIKE_THRESHOLD:
            spikes.append({"entity": entity, "today": today, "avg": round(avg, 1),
                           "ratio": round(today / avg, 1), "type": "급증"})

    return sorted(spikes, key=lambda x: x["today"], reverse=True)


def store_counts(counts: dict, date_str: str) -> None:
    """오늘 카운트 Qdrant에 저장."""
    if not counts:
        return
    from qdrant_client.models import PointStruct
    _ensure_collection()
    _get_client().upsert(
        collection_name=_ENTITY_COLLECTION,
        points=[PointStruct(
            id=_date_point_id(date_str),
            vector=_DUMMY_VECTOR,
            payload={"date": date_str, "counts": counts},
        )],
    )
    logger.info("[EntityTracker] %s 카운트 저장 (%d개 엔티티)", date_str, len(counts))


def run_entity_tracking(articles: list, date_str: str) -> tuple[str, list[str]]:
    """
    언급량 추적 전체 실행.
    반환값: (spike_report_text, spike_entity_names)
    - spike_report_text : 섹션 11에 주입할 텍스트
    - spike_entity_names: Research Agent 우선 조사용 엔티티 목록
    """
    if not _has_qdrant():
        return "", []
    try:
        _ensure_collection()
        counts = count_mentions(articles)
        spikes = detect_spikes(counts)
        store_counts(counts, date_str)

        if not spikes:
            return "", []

        spike_names = [s["entity"] for s in spikes]
        lines = ["### ⚠️ 언급량 급증 감지 (14일 평균 대비)"]
        for s in spikes:
            if s["type"] == "신규 등장":
                lines.append(f"- **{s['entity']}**: {s['today']}회 언급 🆕 신규 등장")
            else:
                lines.append(
                    f"- **{s['entity']}**: {s['today']}회 (평균 {s['avg']}회 대비 {s['ratio']}배) ⚠️"
                )
        return "\n".join(lines) + "\n", spike_names

    except Exception as e:
        logger.warning("[EntityTracker] 급증 감지 실패: %s", e)
        return "", []
