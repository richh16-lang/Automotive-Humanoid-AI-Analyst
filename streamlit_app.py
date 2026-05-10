"""
Inchang's Agent - Edge AI (Auto&Humanoid) 분석 Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Streamlit 기반 실시간 전략 의사결정 지원 대시보드.
5단계 파이프라인: 수집 → Groq 필터 → Gemini 조사 → LLM 합성 → 문서 생성/발송
"""
import io
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── 환경변수 로드 (.env → Streamlit Secrets 순) ──────────────────────────────
# override=True: Windows 시스템 환경변수보다 .env 파일 값을 우선 적용
_env = Path(__file__).parent / ".env"
if _env.exists():
    load_dotenv(_env, override=True)
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ[_k] = _v          # Streamlit Secrets는 항상 덮어쓰기
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ══════════════════════════════════════════════════════════════════════════════
# 페이지 설정
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Inchang's Agent - Edge AI (Auto&Humanoid) 분석",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 글로벌 CSS (다크 모드 + 모바일 최적화) ──────────────────────────────────
st.markdown("""
<style>
/* ── 배경 ─────────────────────────────────── */
.stApp { background-color: #0D1B2A; }
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

/* ── 사이드바 ─────────────────────────────── */
section[data-testid="stSidebar"] { background-color: #0A1628; }

/* ── 메인 실행 버튼 ───────────────────────── */
div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #023E8A 0%, #00B4D8 100%);
    color: #FFFFFF; font-size: 17px; font-weight: 800;
    padding: 14px 28px; border: none; border-radius: 10px;
    width: 100%; letter-spacing: 0.5px;
    box-shadow: 0 4px 15px rgba(0,180,216,0.3);
    transition: all 0.2s ease;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #0077B6 0%, #48CAE4 100%);
    box-shadow: 0 6px 20px rgba(0,180,216,0.45);
    transform: translateY(-1px);
}

/* ── 섹션 카드 (기본) ─────────────────────── */
.sec-card {
    background: #162133; border-left: 4px solid #00B4D8;
    border-radius: 8px; padding: 16px 20px; margin-bottom: 14px;
}
.sec-title { color: #00B4D8; font-size: 15px; font-weight: 700; margin-bottom: 8px; }
.sec-body  { color: #CAE9FF; font-size: 13.5px; line-height: 1.85; }

/* ── 섹션 7·8 강조 카드 ───────────────────── */
.sec-highlight {
    background: linear-gradient(135deg, #0A1F3A 0%, #162133 100%);
    border: 2px solid #00B4D8; border-radius: 10px;
    padding: 18px 22px; margin-bottom: 14px;
    box-shadow: 0 0 18px rgba(0,180,216,0.18);
}
.sec-highlight-title {
    color: #00E5FF; font-size: 15px; font-weight: 800;
    margin-bottom: 10px; letter-spacing: 0.3px;
}
.badge-highlight {
    display: inline-block; background: #00B4D8; color: #0D1B2A;
    font-size: 10px; font-weight: 700; padding: 2px 8px;
    border-radius: 10px; margin-left: 8px; vertical-align: middle;
}

/* ── 기사 카드 ────────────────────────────── */
.art-card {
    background: #1A2840; border: 1px solid #1E3A5F;
    border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
    transition: border-color 0.2s;
}
.art-card:hover { border-color: #00B4D8; }
.art-src   { color: #00B4D8; font-size: 10.5px; font-weight: 700;
             text-transform: uppercase; letter-spacing: 0.6px; }
.art-title { color: #E8F4FD; font-size: 13.5px; font-weight: 500; margin: 4px 0; }
.art-meta  { color: #4A90A4; font-size: 11px; }
.groq-badge { display: inline-block; background: rgba(0,180,216,0.15);
              border: 1px solid #00B4D8; color: #00B4D8;
              font-size: 10px; padding: 1px 7px; border-radius: 8px;
              margin-left: 6px; }

/* ── LLM 로그 ─────────────────────────────── */
.llm-log {
    background: #0A1628; border: 1px solid #1E3A5F;
    border-radius: 6px; padding: 10px 14px; font-size: 12px;
    color: #546E7A; font-family: monospace; max-height: 160px;
    overflow-y: auto;
}
.log-ok   { color: #00E676; }
.log-warn { color: #FFB300; }
.log-err  { color: #FF5252; }
.log-info { color: #546E7A; }

/* ── API 상태 배지 ────────────────────────── */
.ok-dot   { color: #00E676; font-weight: 700; }
.err-dot  { color: #FF5252; font-weight: 700; }
.none-dot { color: #546E7A; font-weight: 700; }

/* ── 탭 ───────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background: #162133; border-radius: 6px 6px 0 0;
    color: #78909C; font-weight: 600; padding: 8px 18px;
}
.stTabs [aria-selected="true"] {
    background: #00B4D8 !important; color: #0D1B2A !important;
}

/* ── 구분선 ───────────────────────────────── */
hr { border-color: #1E3A5F; }

/* ── 메트릭 ───────────────────────────────── */
[data-testid="stMetricValue"] { color: #00B4D8 !important; }
[data-testid="stMetricLabel"] { color: #78909C !important; }

/* ── 모바일 반응형 ────────────────────────── */
@media (max-width: 768px) {
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
    div[data-testid="stButton"] > button[kind="primary"] { font-size: 15px; padding: 12px; }
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════════════════════════════════════
KEYWORDS_DEFAULT = [
    "SDV", "Zonal Architecture", "Humanoid Robot", "Physical AI",
    "Tesla FSD", "NVIDIA DRIVE", "Automotive AI", "Agentic AI",
    "Edge AI", "KV Cache", "HBM", "LPDDR5X", "UFS", "NVMe SSD",
    "PCIe Gen6", "CXL", "WAF", "TBW", "Capacity Planning",
    "Qualcomm", "NVIDIA", "Micron", "Kioxia", "SK Hynix",
    "AUTOSAR", "ISO 26262", "ADAS", "LiDAR",
]

# 섹션 7·8 특별 강조
HIGHLIGHT_SECTIONS = {"메모리", "스토리지 Workload", "Workload", "메모리·스토리지"}

SECTION_COLORS = {
    "핵심 요약": "#00B4D8", "기술적 의미": "#0096C7",
    "AI Agent":  "#48CAE4", "비즈니스":    "#ADE8F4",
    "Ecosystem": "#90E0EF", "향후 전망":   "#0077B6",
    "메모리":    "#00E5FF", "스토리지":    "#00E5FF",
    "지역별":    "#48CAE4", "Why Now":     "#ADE8F4",
}

INDUSTRY_LINKS = [
    ("SemiWiki",      "https://semiwiki.com"),
    ("EE Times",      "https://www.eetimes.com"),
    ("AnandTech",     "https://www.anandtech.com"),
    ("IEEE Spectrum", "https://spectrum.ieee.org"),
    ("Arxiv cs.AR",   "https://arxiv.org/list/cs.AR/recent"),
]


# ══════════════════════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _section_color(title: str) -> str:
    for k, v in SECTION_COLORS.items():
        if k in title:
            return v
    return "#00B4D8"


def _is_highlight_section(title: str) -> bool:
    return any(k in title for k in HIGHLIGHT_SECTIONS)


def _md_to_html(text: str) -> str:
    """마크다운 → Streamlit HTML 변환."""
    import re
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\)]+)\)",
        r'<a href="\2" target="_blank" style="color:#00B4D8;">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong style='color:#E8F4FD'>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code style='background:#1E3A5F;padding:1px 4px;border-radius:3px;color:#90E0EF'>\1</code>", text)
    # 불릿 처리
    lines_html = []
    in_ul = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "• ", "▸ ", "* ")):
            if not in_ul:
                lines_html.append("<ul style='margin:6px 0;padding-left:18px;'>")
                in_ul = True
            lines_html.append(f"<li style='margin:3px 0'>{stripped[2:]}</li>")
        else:
            if in_ul:
                lines_html.append("</ul>")
                in_ul = False
            if stripped:
                lines_html.append(f"<p style='margin:4px 0'>{stripped}</p>")
    if in_ul:
        lines_html.append("</ul>")
    return "\n".join(lines_html)


def _append_log(msg: str, level: str = "info") -> None:
    """LLM 활동 로그 세션 상태에 추가."""
    if "llm_log" not in st.session_state:
        st.session_state["llm_log"] = []
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state["llm_log"].append((ts, level, msg))
    # 최대 50줄 유지
    if len(st.session_state["llm_log"]) > 50:
        st.session_state["llm_log"] = st.session_state["llm_log"][-50:]


# ══════════════════════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar() -> dict:
    """사이드바 렌더링. 설정값 dict 반환."""
    cfg = {}
    with st.sidebar:
        # 타이틀
        st.markdown(
            "<div style='text-align:center;padding:12px 0 6px'>"
            "<span style='font-size:28px'>🔬</span><br>"
            "<span style='color:#00B4D8;font-weight:800;font-size:18px'>"
            "Inchang's Agent</span><br>"
            "<span style='color:#90CAE4;font-size:13px;font-weight:600'>Edge AI (Auto&Humanoid) 분석</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # ── LLM API 상태 ──────────────────────────────────────────────────────
        st.markdown("#### 🤖 LLM 상태")
        try:
            from src.llm_router import get_available_providers
            providers = get_available_providers()
        except Exception:
            providers = []

        for p in providers:
            name, status = p["name"], p["status"]
            if status == "ok":
                dot, label, color = "●", "연결됨", "#00E676"
            elif status == "invalid":
                dot, label, color = "●", "키 오류", "#FF5252"
            else:
                dot, label, color = "○", "미설정", "#546E7A"
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:center;padding:3px 0;border-bottom:1px solid #1E2A40'>"
                f"<span style='color:#CAE9FF;font-size:13px'>{name}</span>"
                f"<span style='color:{color};font-size:12px;font-weight:700'>"
                f"{dot} {label}</span></div>",
                unsafe_allow_html=True,
            )

        ok_count = sum(1 for p in providers if p["status"] == "ok")
        if ok_count == 0:
            st.error("LLM API 키를 1개 이상 .env에 등록하세요.")
        else:
            st.success(f"{ok_count}/{len(providers)}개 활성 — 자동 폴백 준비됨")

        st.markdown("---")

        # ── Notion / Gmail 상태 ───────────────────────────────────────────────
        st.markdown("#### 🔗 연동 서비스")
        services = {
            "Notion": bool(os.environ.get("NOTION_TOKEN")),
            "Gmail":  bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD")),
        }
        for svc, ok in services.items():
            dot = ("● 연결됨" if ok else "○ 미설정")
            color = ("#00E676" if ok else "#546E7A")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
                f"<span style='color:#90A4AE'>{svc}</span>"
                f"<span style='color:{color};font-weight:700;font-size:12px'>{dot}</span></div>",
                unsafe_allow_html=True,
            )

        # Notion 바로가기
        daily_db  = os.environ.get("NOTION_DAILY_DB_ID", "").strip()
        weekly_db = os.environ.get("NOTION_WEEKLY_DB_ID", "").strip()
        if daily_db:
            st.link_button("📋 Daily DB", f"https://www.notion.so/{daily_db}",
                           use_container_width=True)
        if weekly_db:
            st.link_button("📅 Weekly DB", f"https://www.notion.so/{weekly_db}",
                           use_container_width=True)

        st.markdown("---")

        # ── 전문 미디어 바로가기 ──────────────────────────────────────────────
        st.markdown("#### 📰 반도체 전문지")
        for name, url in INDUSTRY_LINKS:
            st.markdown(
                f"<a href='{url}' target='_blank' "
                f"style='color:#00B4D8;font-size:12px;text-decoration:none;"
                f"display:block;padding:3px 0'>↗ {name}</a>",
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── 키워드 설정 ───────────────────────────────────────────────────────
        st.markdown("#### 🔍 분석 키워드")
        selected_kw = st.multiselect(
            label="키워드",
            options=KEYWORDS_DEFAULT,
            default=KEYWORDS_DEFAULT[:16],
            label_visibility="collapsed",
        )
        custom = st.text_input("추가 키워드 (쉼표 구분)",
                               placeholder="TSMC, HBM4, LLM Inference...")
        if custom:
            extras = [k.strip() for k in custom.split(",") if k.strip()]
            selected_kw = list(dict.fromkeys(selected_kw + extras))
        cfg["keywords"] = selected_kw

        st.markdown("---")

        # ── 파이프라인 설정 ───────────────────────────────────────────────────
        st.markdown("#### ⚙️ 파이프라인 설정")
        cfg["hours"]       = st.slider("수집 시간 범위", 6, 48, 26, step=2,
                                        help="최근 N시간 이내 기사 수집")
        cfg["top_n"]       = st.slider("Groq 필터 후 기사 수", 10, 50, 30, step=5)
        cfg["min_score"]   = st.slider("Groq 최소 점수", 3, 8, 4,
                                        help="이 점수 미만 기사 제거")
        cfg["save_notion"] = st.checkbox("Notion 저장", value=True)
        cfg["send_email"]  = st.checkbox("이메일 발송", value=True)

        st.markdown("---")
        last = st.session_state.get("last_run", "없음")
        st.caption(f"마지막 실행: {last}")

    return cfg


# ══════════════════════════════════════════════════════════════════════════════
# 렌더링 컴포넌트
# ══════════════════════════════════════════════════════════════════════════════

def render_meta_banner(analysis: dict) -> None:
    """상단 주요 지표 배너."""
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("분석 날짜",   analysis.get("date", "-"))
    c2.metric("수집 기사",   f"{analysis.get('article_count', 0)}건")
    c3.metric("분석 엔진",   analysis.get("provider", "-"))
    c4.metric("키워드 수",   f"{len(analysis.get('keywords_found', []))}개")

    fm = analysis.get("filter_meta", {})
    rm = analysis.get("research_meta", {})
    groq_label = f"✅ {fm.get('filtered_count', '-')}건" if fm.get("used_groq") else "⬜ 미사용"
    gem_label  = f"✅ {rm.get('researched_count', '-')}건" if rm.get("used_gemini") else "⬜ 미사용"
    c5.metric("Groq/Gemini", f"{groq_label} / {gem_label}")

    attr = analysis.get("model_attribution", "")
    if attr:
        st.markdown(
            f"<div style='background:#0A1628;border-left:3px solid #00B4D8;"
            f"padding:8px 14px;border-radius:4px;color:#546E7A;font-size:12px;"
            f"margin:6px 0 10px'>🤖 {attr}</div>",
            unsafe_allow_html=True,
        )

    notion_url = analysis.get("notion_url", "")
    if notion_url:
        st.link_button("📓 Notion에서 전체 보기", notion_url)


def render_article_cards(articles: list) -> None:
    """수집 기사 카드 렌더링."""
    if not articles:
        st.info("수집된 기사가 없습니다.")
        return

    st.markdown(f"#### 📰 수집 기사 — {len(articles)}건")
    cols = st.columns(2)
    for i, art in enumerate(articles[:24]):
        pub  = art.published.strftime("%m/%d %H:%M") if art.published else "날짜 미상"
        kws  = ", ".join(art.matched_keywords[:3])
        score_badge = (
            f"<span class='groq-badge'>⚡ {art.groq_score}/10</span>"
            if art.groq_score > 0 else ""
        )
        html = (
            f"<div class='art-card'>"
            f"<div class='art-src'>{art.source} · {pub}{score_badge}</div>"
            f"<div class='art-title'>"
            f"<a href='{art.url}' target='_blank' "
            f"style='color:#E8F4FD;text-decoration:none'>{art.title[:80]}</a>"
            f"</div>"
            f"<div class='art-meta'>🏷 {kws}</div>"
            f"</div>"
        )
        with cols[i % 2]:
            st.markdown(html, unsafe_allow_html=True)

    if len(articles) > 24:
        st.caption(f"… 외 {len(articles)-24}건 (분석에는 전체 포함)")


def render_analysis_sections(analysis: dict) -> None:
    """10개 섹션 렌더링 — 섹션 7·8 특별 강조."""
    sections = analysis.get("sections", {})
    if not sections:
        st.warning("섹션 파싱 실패 — Raw 결과를 표시합니다.")
        st.markdown(analysis.get("raw", ""))
        return

    for title, content in sections.items():
        color    = _section_color(title)
        html_body = _md_to_html(content)

        if _is_highlight_section(title):
            # ── 7·8번 섹션 강조 스타일 ─────────────────────────────────────
            st.markdown(
                f"<div class='sec-highlight'>"
                f"<div class='sec-highlight-title'>"
                f"🔥 {title}"
                f"<span class='badge-highlight'>CORE ANALYSIS</span>"
                f"</div>"
                f"<div class='sec-body'>{html_body}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            # ── 일반 섹션 ──────────────────────────────────────────────────
            with st.expander(f"**{title}**", expanded=True):
                st.markdown(
                    f"<div style='border-left:3px solid {color};"
                    f"padding:10px 14px;'>"
                    f"<div class='sec-body'>{html_body}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )


def render_strategy_dashboard(analysis: dict) -> None:
    """임원 보고용 전략 현황판 — 메트릭 / 핵심 인사이트 / 분야별 차트 / 퀵링크."""
    import re
    articles = analysis.get("articles", [])
    sections = analysis.get("sections", {})
    last_run = st.session_state.get("last_run", "-")

    # ── Last Updated 바 ────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='text-align:right;color:#546E7A;font-size:11px;"
        f"margin-bottom:6px'>🕐 Last Updated: <strong style='color:#00B4D8'>"
        f"{last_run}</strong></div>",
        unsafe_allow_html=True,
    )

    # ── 1. Metric Section ──────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📰 수집 기사", f"{analysis.get('article_count', 0)}건")
    m2.metric("🧠 분석 기사", f"{analysis.get('synthesis_count', analysis.get('article_count',0))}건")
    kws = analysis.get("keywords_found", [])
    m3.metric("🏷 매칭 키워드", f"{len(kws)}개")
    # 경쟁사 업데이트: company_news / earnings 카테고리 기사 수
    comp_count = sum(1 for a in articles
                     if getattr(a, "category", "") in ("company_news", "earnings"))
    m4.metric("🏢 경쟁사 업데이트", f"{comp_count}건")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 2. Top 3 핵심 전략 인사이트 ───────────────────────────────────────────
    insight_title = next((t for t in sections if "핵심 요약" in t or "요약" in t), None)
    if insight_title:
        raw_insights = sections[insight_title]
        # 불릿 항목 추출
        bullets = [l.strip().lstrip("-•▸* ").strip()
                   for l in raw_insights.split("\n")
                   if l.strip().startswith(("-", "•", "▸", "*", "1", "2", "3"))]
        top3 = bullets[:3]
    else:
        top3 = []

    st.markdown(
        "<div style='background:linear-gradient(135deg,#0A1F3A,#162133);"
        "border:1px solid #00B4D8;border-radius:10px;padding:18px 22px;margin-bottom:16px'>"
        "<div style='color:#00E5FF;font-size:14px;font-weight:800;margin-bottom:12px'>"
        "⚡ 오늘의 3대 핵심 전략 인사이트</div>",
        unsafe_allow_html=True,
    )
    if top3:
        for idx, insight in enumerate(top3, 1):
            clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", insight)
            clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", clean)
            clean = clean[:200]
            st.markdown(
                f"<div style='display:flex;gap:12px;margin-bottom:10px;align-items:flex-start'>"
                f"<span style='background:#00B4D8;color:#0D1B2A;font-size:11px;font-weight:800;"
                f"padding:3px 8px;border-radius:12px;white-space:nowrap;margin-top:2px'>0{idx}</span>"
                f"<span style='color:#CAE9FF;font-size:13.5px;line-height:1.7'>{clean}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            "<p style='color:#546E7A;font-size:13px'>분석 실행 후 표시됩니다.</p>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # ── 3. Visual Matrix — 분야별 기사 건수 바 차트 ───────────────────────────
    st.markdown("#### 📊 분야별 뉴스 분포")
    CATEGORY_LABELS = {
        "sdv":          "SDV/자율주행",
        "automotive":   "자동차",
        "humanoid":     "휴머노이드",
        "ai":           "AI/알고리즘",
        "semiconductor":"반도체",
        "memory":       "메모리",
        "storage":      "스토리지",
        "research":     "논문",
        "patent":       "특허",
        "company_news": "기업동향",
        "earnings":     "실적/IR",
        "conference":   "컨퍼런스",
        "crossref":     "크로스레퍼런스",
        "korea":        "한국",
    }
    cat_counts: dict[str, int] = {}
    for a in articles:
        cat = getattr(a, "category", "기타")
        label = CATEGORY_LABELS.get(cat, cat)
        cat_counts[label] = cat_counts.get(label, 0) + 1

    if cat_counts:
        sorted_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
        labels = [c[0] for c in sorted_cats]
        values = [c[1] for c in sorted_cats]
        import pandas as pd
        df = pd.DataFrame({"건수": values}, index=labels)
        st.bar_chart(df, color="#00B4D8", height=220)
    else:
        st.caption("기사 수집 후 표시됩니다.")

    # ── 4. Quick Links — 출처 하이퍼링크 버튼 ────────────────────────────────
    source_urls = analysis.get("source_urls", [])
    if source_urls:
        st.markdown("#### 🔗 주요 출처 바로가기")
        # URL에서 도메인 추출해서 버튼 레이블로 사용
        cols = st.columns(4)
        for i, url in enumerate(source_urls[:12]):
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")[:22]
            except Exception:
                domain = f"출처 {i+1}"
            cols[i % 4].link_button(f"↗ {domain}", url, use_container_width=True)


def render_download_buttons(analysis: dict) -> None:
    """Word + Markdown 다운로드 버튼."""
    st.markdown("#### 📥 보고서 다운로드")
    col1, col2, col3 = st.columns(3)

    # Word 다운로드
    word_path = analysis.get("word_path")
    if word_path and Path(word_path).exists():
        with open(word_path, "rb") as f:
            col1.download_button(
                label="⬇ Word 보고서 (.docx)",
                data=f.read(),
                file_name=Path(word_path).name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
    else:
        col1.button("⬇ Word 보고서", disabled=True, use_container_width=True)

    # Markdown 다운로드
    md_path = analysis.get("md_path")
    if md_path and Path(md_path).exists():
        with open(md_path, "rb") as f:
            col2.download_button(
                label="⬇ Markdown (.md)",
                data=f.read(),
                file_name=Path(md_path).name,
                mime="text/markdown",
                use_container_width=True,
            )
    else:
        col2.button("⬇ Markdown", disabled=True, use_container_width=True)

    # 요약 텍스트 복사용
    summary_text = _build_summary_text(analysis)
    col3.download_button(
        label="📋 요약 텍스트 복사",
        data=summary_text.encode("utf-8"),
        file_name=f"summary_{analysis.get('date','today')}.txt",
        mime="text/plain",
        use_container_width=True,
    )


def _build_summary_text(analysis: dict) -> str:
    """공유용 요약 텍스트 생성."""
    lines = [
        f"AI/Semiconductor Daily News [{analysis.get('type','daily').upper()}]",
        f"Automotive/Humanoid and Storage Intelligence",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"날짜: {analysis.get('date','-')} | 기사: {analysis.get('article_count',0)}건",
        f"AI: {analysis.get('model_attribution','-')}",
        "",
    ]
    sections = analysis.get("sections", {})
    for title, content in list(sections.items())[:3]:  # 상위 3개 섹션만
        import re
        clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)
        clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", clean)
        lines.append(f"▶ {title}")
        lines.append(clean[:500])
        lines.append("")
    return "\n".join(lines)


def _load_from_notion(date_str: str) -> dict | None:
    """
    Notion에서 특정 날짜 분석 데이터 로드.
    성공 시 analysis dict 반환, 실패/없음 시 None.
    """
    if not (os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID")):
        return None
    try:
        from src.notion_client import fetch_daily_from_notion
        return fetch_daily_from_notion(date_str)
    except Exception as e:
        _append_log(f"Notion 로드 실패: {e}", "warn")
        return None


def render_llm_log() -> None:
    """하단 LLM 활동 로그 패널."""
    logs = st.session_state.get("llm_log", [])
    if not logs:
        return

    st.markdown("#### 🖥 LLM 활동 로그")
    log_html = ""
    for ts, level, msg in logs[-20:]:  # 최신 20줄
        color = {"ok": "#00E676", "warn": "#FFB300", "err": "#FF5252"}.get(level, "#546E7A")
        log_html += f"<div><span style='color:#334455'>[{ts}]</span> <span style='color:{color}'>{msg}</span></div>"

    st.markdown(
        f"<div class='llm-log'>{log_html}</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 메인 파이프라인 실행
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(cfg: dict) -> dict | None:
    """
    5단계 분석 파이프라인.
    ① 수집 → ② Groq 필터 → ③ Gemini 조사 → ④ LLM 합성 → ⑤ 문서/Notion/이메일
    """
    from src.collector          import run_collection
    from src.groq_filter        import filter_and_rank
    from src.gemini_researcher  import research_articles
    from src.analyzer           import analyze_articles
    from src.word_exporter      import generate_word
    from src.markdown_exporter  import generate_markdown

    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir   = tempfile.gettempdir()
    analysis  = {}

    _append_log("파이프라인 시작", "info")

    with st.status("🚀 실시간 전략 분석 파이프라인 실행 중...",
                   expanded=True) as status_box:

        # ── ① 뉴스 수집 ───────────────────────────────────────────────────────
        status_box.write("📡 **Step 1/5** — RSS·Google News·Arxiv 수집 중...")
        prog = st.progress(0, text="수집 중...")
        try:
            articles = run_collection(hours=cfg["hours"])
            _append_log(f"수집 완료: {len(articles)}건", "ok")
            prog.progress(15, text=f"✅ {len(articles)}건 수집")
            status_box.write(f"✅ 수집 완료: **{len(articles)}건**")
        except Exception as e:
            st.error(f"❌ 수집 실패: {e}")
            _append_log(f"수집 실패: {e}", "err")
            status_box.update(label="❌ 수집 단계 실패", state="error")
            return None

        if not articles:
            st.warning("수집된 기사가 없습니다. 피드 설정을 확인하세요.")
            status_box.update(label="⚠️ 수집 기사 없음", state="error")
            return None

        analysis["articles"] = articles

        # ── ② Groq 필터링 ─────────────────────────────────────────────────────
        status_box.write("⚡ **Step 2/5** — Groq(Llama 3.3 70B)가 반도체 노이즈 필터링 중...")
        prog.progress(22, text="Groq 필터링...")
        try:
            articles, filter_meta = filter_and_rank(
                articles, top_n=cfg["top_n"], min_score=cfg["min_score"]
            )
            if filter_meta.get("used_groq"):
                removed = filter_meta["original_count"] - filter_meta["filtered_count"]
                _append_log(f"Groq 필터: {filter_meta['original_count']}→{filter_meta['filtered_count']}건 (제거 {removed}건)", "ok")
                status_box.write(f"✅ Groq 필터: **{filter_meta['filtered_count']}건** 선별 (비관련 {removed}건 제거)")
            else:
                _append_log("Groq API 키 없음 → 전체 기사 사용", "warn")
                status_box.write(f"⚠️ Groq 키 없음 → 전체 {len(articles)}건 분석 진행")
        except Exception as e:
            _append_log(f"Groq 필터 실패: {e}", "warn")
            status_box.write(f"⚠️ Groq 필터 실패 (전체 기사 사용): {e}")
            filter_meta = {"used_groq": False, "original_count": len(articles),
                           "filtered_count": len(articles)}

        prog.progress(35, text="Groq 완료")

        # ── ③ Gemini 배경 조사 ────────────────────────────────────────────────
        status_box.write("🔭 **Step 3/5** — Gemini 2.0 Flash가 경쟁사 로드맵·기술 배경 대조 중...")
        prog.progress(42, text="Gemini 조사...")
        _append_log("Gemini 배경 조사 시작", "info")
        try:
            articles, research_meta = research_articles(articles, max_articles=15)
            if research_meta.get("used_gemini"):
                cnt = research_meta.get("researched_count", 0)
                _append_log(f"Gemini 조사 완료: {cnt}건 강화", "ok")
                status_box.write(f"✅ Gemini 조사: **{cnt}건** 기사 배경 강화")
            else:
                _append_log("Gemini API 키 없음 또는 할당량 소진", "warn")
                status_box.write("⚠️ Gemini 조사 건너뜀 (API 키 없음 또는 일일 할당량 소진)")
        except Exception as e:
            _append_log(f"Gemini 조사 실패: {e}", "warn")
            status_box.write(f"⚠️ Gemini 조사 실패 (원본 사용): {e}")
            research_meta = {"used_gemini": False}

        prog.progress(55, text="Gemini 완료")

        # ── ④ LLM 합성 분석 ───────────────────────────────────────────────────
        status_box.write("🧠 **Step 4/5** — Multi-LLM 앙상블 10섹션 분석 중...")
        _append_log("LLM 합성 분석 시작", "info")

        llm_placeholder = st.empty()

        def _ui_status(msg: str) -> None:
            """LLM 라우터 → 대시보드 실시간 상태 표시 콜백."""
            llm_placeholder.info(msg)
            _append_log(msg, "ok" if "완료" in msg else "info")

        prog.progress(60, text="LLM 합성 중...")
        try:
            analysis_result = analyze_articles(
                articles,
                date_str=date_str,
                status_fn=_ui_status,
                filter_meta=filter_meta,
                research_meta=research_meta,
            )
            provider = analysis_result.get("provider", "-")
            analysis_result["articles"] = articles   # ← 수집 기사 탭 표시용
            _append_log(f"합성 완료: {provider}", "ok")
            llm_placeholder.success(f"✅ {provider} 합성 완료")
            prog.progress(78, text=f"✅ {provider} 완료")
            status_box.write(f"✅ **{provider}** 10섹션 분석 완료")
        except Exception as e:
            st.error(f"❌ LLM 분석 실패: {e}")
            _append_log(f"LLM 분석 실패: {e}", "err")
            status_box.update(label="❌ LLM 분석 실패", state="error")
            return None

        # ── ⑤ 문서 생성 + Notion + 이메일 ────────────────────────────────────
        status_box.write("📄 **Step 5/5** — Word·Markdown 생성 및 발송 중...")
        prog.progress(82, text="문서 생성 중...")

        # Word 보고서
        word_path = None
        try:
            word_path = generate_word(analysis_result, output_dir=out_dir)
            analysis_result["word_path"] = word_path
            _append_log(f"Word 생성: {Path(word_path).name}", "ok")
            status_box.write(f"✅ Word 보고서 생성: `{Path(word_path).name}`")
        except Exception as e:
            _append_log(f"Word 생성 실패: {e}", "warn")
            status_box.write(f"⚠️ Word 생성 실패: {e}")

        prog.progress(87, text="Markdown 생성...")

        # Markdown
        md_path = None
        try:
            md_path = generate_markdown(analysis_result, output_dir=out_dir)
            analysis_result["md_path"] = md_path
            _append_log(f"Markdown 생성: {Path(md_path).name}", "ok")
            status_box.write(f"✅ Markdown 생성: `{Path(md_path).name}`")
        except Exception as e:
            _append_log(f"Markdown 생성 실패: {e}", "warn")
            status_box.write(f"⚠️ Markdown 생성 실패: {e}")

        prog.progress(91, text="Notion 저장...")

        # Notion 저장
        if cfg["save_notion"] and os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID"):
            try:
                from src.notion_client import save_daily_to_notion
                notion_url = save_daily_to_notion(analysis_result)
                analysis_result["notion_url"] = notion_url
                _append_log("Notion 저장 완료", "ok")
                status_box.write("✅ Notion 저장 완료")
            except Exception as e:
                _append_log(f"Notion 저장 실패: {e}", "warn")
                status_box.write(f"⚠️ Notion 저장 실패: {e}")
        else:
            _append_log("Notion 저장 건너뜀", "info")

        prog.progress(96, text="이메일 발송...")

        # 이메일 발송
        if cfg["send_email"] and os.environ.get("GMAIL_ADDRESS"):
            try:
                from src.email_sender import send_daily_email
                send_daily_email(analysis_result,
                                 word_path=word_path,
                                 md_path=md_path)
                _append_log("이메일 발송 완료", "ok")
                status_box.write("✅ 이메일 발송 완료")
            except Exception as e:
                _append_log(f"이메일 발송 실패: {e}", "warn")
                status_box.write(f"⚠️ 이메일 발송 실패: {e}")
        else:
            _append_log("이메일 발송 건너뜀", "info")

        prog.progress(100, text="✅ 완료!")
        status_box.update(
            label=(f"✅ 분석 완료 — {len(articles)}건 기사 | "
                   f"{analysis_result.get('provider','-')} | {date_str}"),
            state="complete",
            expanded=False,
        )
        _append_log("파이프라인 완료", "ok")

    return analysis_result


# ══════════════════════════════════════════════════════════════════════════════
# Weekly 탭
# ══════════════════════════════════════════════════════════════════════════════

def render_weekly_tab() -> None:
    st.markdown("### 📅 Weekly Intelligence Report")
    st.markdown(
        "<p style='color:#546E7A;font-size:13px'>"
        "최근 7일간 Daily 보고서를 Notion에서 불러와 주간 종합 분석을 생성합니다.</p>",
        unsafe_allow_html=True,
    )

    col_btn, col_info = st.columns([2, 5])
    with col_btn:
        run_weekly = st.button("📅 Weekly 보고서 생성", type="secondary",
                               use_container_width=True)
    with col_info:
        notion_ok = os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID")
        if not notion_ok:
            st.warning("Notion 연동이 필요합니다 (.env에 NOTION_TOKEN 설정)")

    if run_weekly:
        if not (os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID")):
            st.error("Notion 연동 없이는 Weekly 보고서를 생성할 수 없습니다.")
        else:
            with st.status("Weekly 보고서 생성 중...", expanded=True) as ws:
                try:
                    ws.write("📖 Notion에서 Daily 분석 데이터 조회 중...")
                    from src.notion_client import fetch_weekly_analyses
                    daily_list = fetch_weekly_analyses(days=7)
                    ws.write(f"✅ {len(daily_list)}개 Daily 분석 로드")

                    if not daily_list:
                        st.warning("최근 7일 Daily 분석 데이터가 없습니다.")
                        ws.update(label="⚠️ 데이터 없음", state="error")
                        return

                    ws.write("🧠 Weekly LLM 종합 분석 중...")
                    from src.analyzer import analyze_weekly
                    weekly = analyze_weekly(daily_list)
                    ws.write(f"✅ {weekly.get('provider','-')} Weekly 분석 완료")

                    from src.weekly_report import get_week_label
                    week_label = get_week_label()

                    ws.write("💾 Notion 저장 및 이메일 발송...")
                    from src.notion_client import save_weekly_to_notion
                    notion_url = save_weekly_to_notion(weekly, week_label)
                    weekly["notion_url"] = notion_url

                    out_dir = tempfile.gettempdir()
                    from src.word_exporter import generate_word
                    from src.markdown_exporter import generate_markdown
                    word_path = generate_word(weekly, output_dir=out_dir)
                    md_path   = generate_markdown(weekly, output_dir=out_dir)
                    weekly["word_path"] = word_path
                    weekly["md_path"]   = md_path

                    if os.environ.get("GMAIL_ADDRESS"):
                        from src.email_sender import send_weekly_email
                        send_weekly_email(weekly, week_label,
                                          word_path=word_path, md_path=md_path)
                        ws.write("✅ Weekly 이메일 발송 완료")

                    ws.update(label=f"✅ Weekly 완료: {week_label}", state="complete")
                    st.session_state["weekly_analysis"] = weekly
                    _append_log(f"Weekly 완료: {week_label}", "ok")

                except Exception as e:
                    st.error(f"Weekly 생성 실패: {e}")
                    ws.update(label="❌ 실패", state="error")
                    _append_log(f"Weekly 실패: {e}", "err")

    if "weekly_analysis" in st.session_state:
        w = st.session_state["weekly_analysis"]
        render_meta_banner(w)
        render_download_buttons(w)
        st.markdown("---")
        render_analysis_sections(w)


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # 사이드바
    cfg = render_sidebar()

    # ── 헤더 ──────────────────────────────────────────────────────────────────
    st.markdown(
        "<h1 style='color:#00B4D8;font-size:28px;font-weight:900;"
        "margin-bottom:2px;letter-spacing:-0.5px'>"
        "🔬 Inchang's Agent - Edge AI (Auto&amp;Humanoid) 분석"
        "</h1>"
        "<p style='color:#546E7A;font-size:13px;margin-top:0;margin-bottom:8px'>"
        "AI/Semiconductor Daily News &nbsp;|&nbsp; "
        "Automotive / Humanoid / Storage Intelligence"
        "</p>",
        unsafe_allow_html=True,
    )

    # 속도 조절 안내
    fm = st.session_state.get("daily_analysis", {}).get("filter_meta", {})
    rm = st.session_state.get("daily_analysis", {}).get("research_meta", {})
    if rm.get("skipped_count", 0) > 0:
        st.info(
            f"⏱ Gemini 무료 티어 Rate Limit: {rm['skipped_count']}건 조사 건너뜀. "
            "일일 할당량은 자정(UTC)에 초기화됩니다."
        )

    st.markdown("---")

    # ── 앱 첫 로드 시 오늘 Notion 데이터 자동 불러오기 ────────────────────────
    from datetime import timedelta, timezone as _tz
    _KST = _tz(timedelta(hours=9))
    _today_kst = datetime.now(_KST).strftime("%Y-%m-%d")

    if ("daily_analysis" not in st.session_state
            and "notion_auto_loaded" not in st.session_state):
        st.session_state["notion_auto_loaded"] = True   # 재실행 방지
        if os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID"):
            with st.spinner(f"📥 오늘({_today_kst}) Notion 데이터 자동 로드 중..."):
                _auto = _load_from_notion(_today_kst)
            if _auto:
                st.session_state["daily_analysis"] = _auto
                st.session_state["last_run"] = f"{_today_kst} (Notion)"
                _append_log(f"Notion 자동 로드: {_today_kst}", "ok")
                st.rerun()

    # ── 메인 버튼 행: 실행 + 과거 데이터 불러오기 ────────────────────────────
    col_btn, col_hist, col_kw = st.columns([2, 2, 4])

    with col_btn:
        run_clicked = st.button(
            "▶  실시간 전략 분석 실행",
            type="primary",
            use_container_width=True,
            help="뉴스 수집 → Groq 필터 → Gemini 조사 → LLM 합성 전체 파이프라인 실행",
        )

    with col_hist:
        show_picker = st.button(
            "📅 과거 데이터 불러오기",
            use_container_width=True,
            help="Notion에 저장된 특정 날짜의 분석 결과를 불러옵니다",
        )

    with col_kw:
        kw_preview = ", ".join(cfg["keywords"][:6])
        more = f" 외 {len(cfg['keywords'])-6}개" if len(cfg["keywords"]) > 6 else ""
        st.markdown(
            f"<div style='padding:11px 14px;background:#0A1628;border-radius:8px;"
            f"color:#546E7A;font-size:12.5px'>"
            f"🔍 <strong style='color:#CAE9FF'>{kw_preview}{more}</strong> | "
            f"최근 {cfg['hours']}시간 | 상위 {cfg['top_n']}건 | "
            f"Groq 점수≥{cfg['min_score']}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── 과거 데이터 날짜 피커 ──────────────────────────────────────────────────
    if show_picker or st.session_state.get("show_date_picker"):
        st.session_state["show_date_picker"] = True
        import datetime as _dt
        with st.container():
            st.markdown(
                "<div style='background:#0A1628;border:1px solid #1E3A5F;"
                "border-radius:8px;padding:16px 20px;margin:8px 0'>",
                unsafe_allow_html=True,
            )
            pc1, pc2, pc3 = st.columns([2, 1, 1])
            with pc1:
                selected_date = st.date_input(
                    "조회할 날짜 선택",
                    value=_dt.date.fromisoformat(_today_kst),
                    min_value=_dt.date(2025, 1, 1),
                    max_value=_dt.date.fromisoformat(_today_kst),
                    label_visibility="collapsed",
                )
            with pc2:
                fetch_clicked = st.button("📥 불러오기", use_container_width=True, type="secondary")
            with pc3:
                if st.button("✕ 닫기", use_container_width=True):
                    st.session_state["show_date_picker"] = False
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            if fetch_clicked:
                _date_str = selected_date.isoformat()
                with st.spinner(f"📥 {_date_str} Notion 데이터 로드 중..."):
                    _hist = _load_from_notion(_date_str)
                if _hist:
                    st.session_state["daily_analysis"] = _hist
                    st.session_state["last_run"] = f"{_date_str} (Notion)"
                    st.session_state["show_date_picker"] = False
                    _append_log(f"Notion 과거 로드: {_date_str}", "ok")
                    st.rerun()
                else:
                    st.warning(
                        f"⚠️ {_date_str} 날짜의 분석 데이터가 Notion에 없습니다. "
                        "날짜를 다시 선택하거나 실시간 분석을 실행하세요."
                    )

    # ── 파이프라인 실행 ────────────────────────────────────────────────────────
    if run_clicked:
        result = run_pipeline(cfg)
        if result:
            st.session_state["daily_analysis"] = result
            st.session_state["last_run"] = datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")
            st.session_state["show_date_picker"] = False
            st.rerun()

    # ── 탭 ────────────────────────────────────────────────────────────────────
    tab_daily, tab_articles, tab_weekly, tab_log = st.tabs([
        "📊 Daily Analysis", "🗞 수집 기사", "📅 Weekly Report", "🖥 활동 로그"
    ])

    # Daily 분석 결과
    with tab_daily:
        if "daily_analysis" not in st.session_state:
            notion_ok = bool(os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID"))
            if notion_ok:
                notice = (
                    f"<p style='color:#546E7A;font-size:12px'>"
                    f"오늘({_today_kst}) Notion에 저장된 분석이 없거나 아직 실행되지 않았습니다.<br>"
                    f"<strong style='color:#00B4D8'>▶ 실시간 전략 분석 실행</strong>으로 새로 생성하거나 "
                    f"<strong style='color:#00B4D8'>📅 과거 데이터 불러오기</strong>로 이전 날짜를 조회하세요."
                    f"</p>"
                )
            else:
                notice = (
                    "<p style='color:#546E7A;font-size:12px'>"
                    "상단의 <strong style='color:#00B4D8'>▶ 실시간 전략 분석 실행</strong> "
                    "버튼을 클릭하세요.<br>"
                    "<span style='font-size:12px'>약 2~5분 소요 · 이메일 자동 발송</span>"
                    "</p>"
                )
            st.markdown(
                "<div style='text-align:center;padding:60px 20px;color:#546E7A'>"
                "<div style='font-size:48px;margin-bottom:16px'>🔬</div>"
                "<h3 style='color:#1E3A5F'>분석 결과가 없습니다</h3>"
                f"{notice}"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            analysis = st.session_state["daily_analysis"]

            # ── 전략 현황판 (상단) ─────────────────────────────────────────────
            render_strategy_dashboard(analysis)

            st.markdown("---")

            # ── 메타 배너 + 다운로드 + 이메일 ─────────────────────────────────
            render_meta_banner(analysis)
            col_dl, col_mail = st.columns([3, 1])
            with col_dl:
                render_download_buttons(analysis)
            with col_mail:
                st.markdown("#### 📧 이메일 발송")
                if st.button("📧 지금 발송", use_container_width=True,
                             help="분석 결과를 이메일로 즉시 발송"):
                    if os.environ.get("GMAIL_ADDRESS"):
                        try:
                            from src.email_sender import send_daily_email
                            send_daily_email(
                                analysis,
                                word_path=analysis.get("word_path"),
                                md_path=analysis.get("md_path"),
                            )
                            st.success("✅ 발송 완료!")
                            _append_log("이메일 즉시 발송 완료", "ok")
                        except Exception as e:
                            st.error(f"발송 실패: {e}")
                            _append_log(f"이메일 발송 실패: {e}", "err")
                    else:
                        st.error("GMAIL_ADDRESS가 설정되지 않았습니다.")

            st.markdown("---")

            # ── 10개 섹션 상세 분석 (하단) ────────────────────────────────────
            st.markdown("### 📋 상세 분석 리포트")
            render_analysis_sections(analysis)

    # 수집 기사
    with tab_articles:
        if "daily_analysis" in st.session_state:
            render_article_cards(
                st.session_state["daily_analysis"].get("articles", [])
            )
        else:
            st.info("분석을 실행하면 수집된 기사 목록이 표시됩니다.")

    # Weekly
    with tab_weekly:
        render_weekly_tab()

    # LLM 활동 로그
    with tab_log:
        st.markdown("### 🖥 LLM 활동 로그 (실시간)")
        st.markdown(
            "<p style='color:#546E7A;font-size:12px'>"
            "파이프라인 단계별 LLM 전환, Rate Limit 경고, 처리 결과를 확인합니다.</p>",
            unsafe_allow_html=True,
        )
        render_llm_log()

        if st.button("🗑 로그 초기화"):
            st.session_state["llm_log"] = []
            st.rerun()

    # ── 푸터 ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#1E3A5F;font-size:11px;padding:8px'>"
        "Inchang's Agent - Edge AI (Auto&amp;Humanoid) 분석 &nbsp;·&nbsp; "
        "Multi-LLM: Claude → Gemini → GPT → DeepSeek → Groq → Mistral &nbsp;·&nbsp; "
        "Auto-fallback enabled"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
