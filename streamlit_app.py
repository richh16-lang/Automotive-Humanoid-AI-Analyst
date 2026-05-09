"""
Automotive / AI Semiconductor Strategy Dashboard
Streamlit 기반 웹 대시보드 — 뉴스 수집·분석·시각화
"""
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── 환경변수 로드 (로컬 .env 우선, Streamlit Cloud secrets 보조) ─────────────
load_dotenv(Path(__file__).parent / ".env")
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Semiconductor Strategy Brief",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* 전체 배경 */
.stApp { background-color: #0D1B2A; }

/* 카드 스타일 */
.section-card {
    background: #162133;
    border-left: 4px solid #00B4D8;
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 14px;
}
.section-title {
    color: #00B4D8;
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 8px;
}
.section-body {
    color: #CAE9FF;
    font-size: 14px;
    line-height: 1.75;
}

/* 기사 카드 */
.article-card {
    background: #1A2840;
    border: 1px solid #1E3A5F;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 8px;
}
.article-source {
    color: #00B4D8;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.article-title {
    color: #E8F4FD;
    font-size: 14px;
    font-weight: 500;
    margin: 4px 0;
}
.article-kw {
    color: #4A90A4;
    font-size: 11px;
}

/* API 상태 배지 */
.status-ok   { color: #00E676; font-weight: 700; }
.status-err  { color: #FF5252; font-weight: 700; }
.status-none { color: #546E7A; font-weight: 700; }

/* 메인 버튼 강조 */
div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #023E8A, #00B4D8);
    color: white;
    font-size: 16px;
    font-weight: 700;
    padding: 12px 32px;
    border: none;
    border-radius: 8px;
    width: 100%;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #0077B6, #48CAE4);
}

/* 탭 스타일 */
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    background: #162133;
    border-radius: 6px 6px 0 0;
    color: #90A4AE;
    font-weight: 600;
    padding: 8px 20px;
}
.stTabs [aria-selected="true"] {
    background: #00B4D8 !important;
    color: #0D1B2A !important;
}

/* 사이드바 */
section[data-testid="stSidebar"] { background-color: #0A1628; }
</style>
""", unsafe_allow_html=True)

# ── 로깅 설정 ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ── 기본 키워드 ────────────────────────────────────────────────────────────────
DEFAULT_KEYWORDS = [
    "SDV", "ADV", "Humanoid Robot", "Tesla FSD", "NVIDIA DRIVE",
    "Automotive AI", "Physical AI", "Agentic AI",
    "Automotive Memory", "UFS", "SSD", "Storage", "Edge AI",
    "Qualcomm", "KV cache",
]

SECTION_COLORS = {
    "핵심 요약": "#00B4D8", "기술적 의미": "#0096C7",
    "AI Agent":  "#48CAE4", "비즈니스 영향": "#ADE8F4",
    "Ecosystem": "#90E0EF", "향후 전망": "#023E8A",
    "메모리":    "#0077B6", "스토리지":     "#00B4D8",
    "지역별":    "#48CAE4", "Why Now":      "#ADE8F4",
}

def _section_color(title: str) -> str:
    for k, v in SECTION_COLORS.items():
        if k in title:
            return v
    return "#00B4D8"


# ══════════════════════════════════════════════════════════════════════════════
# API 상태 확인
# ══════════════════════════════════════════════════════════════════════════════

def _check_api_status() -> dict[str, str]:
    """API 키 존재 여부 및 포맷 기본 검증."""
    from src.llm_router import get_available_providers
    result = {p["name"]: p["status"] for p in get_available_providers()}
    result["Notion"] = "ok" if os.environ.get("NOTION_TOKEN") else "none"
    result["Gmail"]  = "ok" if os.environ.get("GMAIL_ADDRESS") else "none"
    return result

def _status_badge(state: str) -> str:
    if state == "ok":
        return '<span class="status-ok">● 연결됨</span>'
    if state in ("invalid", "error"):
        return '<span class="status-err">● 키 오류</span>'
    return '<span class="status-none">○ 미설정</span>'


# ══════════════════════════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar() -> list[str]:
    with st.sidebar:
        st.markdown("## ⚡ Semiconductor Brief")
        st.markdown("---")

        # ── API 상태 ──────────────────────────────────────────────────────────
        st.markdown("### 🔌 LLM API 상태")
        api_status = _check_api_status()

        ALL_LLMS = [
            ("Claude",   "유료",    "#00B4D8"),
            ("Gemini",   "무료 1.5k/일", "#48CAE4"),
            ("GPT",      "유료",    "#90E0EF"),
            ("DeepSeek", "무료★",   "#ADE8F4"),
            ("Groq",     "무료 14k/일", "#00E676"),
            ("Mistral",  "무료 티어", "#B0BEC5"),
        ]
        llm_rows = ""
        for name, tier, color in ALL_LLMS:
            badge = _status_badge(api_status.get(name, "none"))
            llm_rows += (
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:center;margin:5px 0;padding:3px 0;"
                f"border-bottom:1px solid #1E3A5F'>"
                f"<div><span style='color:{color};font-weight:600'>{name}</span>"
                f"<span style='color:#546E7A;font-size:10px;margin-left:6px'>{tier}</span></div>"
                f"{badge}</div>"
            )
        st.markdown(llm_rows, unsafe_allow_html=True)

        llm_ok = sum(1 for n, _, _ in ALL_LLMS if api_status.get(n) == "ok")
        if llm_ok == 0:
            st.error("LLM API 키를 1개 이상 .env에 등록하세요.")
        else:
            st.success(f"LLM {llm_ok}/6개 활성 — 자동 폴백 준비됨")

        st.markdown("---")

        # ── 기타 서비스 상태 ──────────────────────────────────────────────────
        st.markdown("### 🗂 연동 서비스")
        for svc in ["Notion", "Gmail"]:
            badge = _status_badge(api_status[svc])
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;margin:4px 0'>"
                f"<span style='color:#90A4AE'>{svc}</span>{badge}</div>",
                unsafe_allow_html=True,
            )

        # Notion 바로가기
        daily_db  = os.environ.get("NOTION_DAILY_DB_ID", "")
        weekly_db = os.environ.get("NOTION_WEEKLY_DB_ID", "")
        if daily_db:
            st.link_button("📋 Daily DB 열기",
                           f"https://www.notion.so/{daily_db}", use_container_width=True)
        if weekly_db:
            st.link_button("📅 Weekly DB 열기",
                           f"https://www.notion.so/{weekly_db}", use_container_width=True)

        st.markdown("---")

        # ── 키워드 설정 ───────────────────────────────────────────────────────
        st.markdown("### 🔍 분석 키워드")
        selected_kw = st.multiselect(
            label="키워드 선택 (추가/제거 가능)",
            options=DEFAULT_KEYWORDS,
            default=DEFAULT_KEYWORDS,
            label_visibility="collapsed",
        )
        custom_kw = st.text_input("커스텀 키워드 추가 (쉼표 구분)",
                                  placeholder="예: TSMC, HBM4, CXL")
        if custom_kw:
            extras = [k.strip() for k in custom_kw.split(",") if k.strip()]
            selected_kw = list(dict.fromkeys(selected_kw + extras))

        st.markdown("---")
        st.caption(f"마지막 실행: {st.session_state.get('last_run', '없음')}")

    return selected_kw


# ══════════════════════════════════════════════════════════════════════════════
# 뉴스 기사 카드 렌더링
# ══════════════════════════════════════════════════════════════════════════════

def render_article_cards(articles: list) -> None:
    st.markdown(f"#### 📰 수집된 기사 ({len(articles)}건)")
    cols = st.columns(2)
    for i, art in enumerate(articles[:20]):
        pub = art.published.strftime("%m/%d %H:%M") if art.published else "날짜 미상"
        kws = ", ".join(art.matched_keywords[:3])
        html = f"""
        <div class="article-card">
          <div class="article-source">{art.source} · {pub}</div>
          <div class="article-title">
            <a href="{art.url}" target="_blank"
               style="color:#E8F4FD;text-decoration:none;">{art.title[:80]}</a>
          </div>
          <div class="article-kw">🏷 {kws}</div>
        </div>"""
        with cols[i % 2]:
            st.markdown(html, unsafe_allow_html=True)

    if len(articles) > 20:
        st.caption(f"… 외 {len(articles) - 20}건 (분석에는 전체 포함)")


# ══════════════════════════════════════════════════════════════════════════════
# 분석 결과 렌더링
# ══════════════════════════════════════════════════════════════════════════════

def render_analysis_sections(analysis: dict) -> None:
    sections: dict = analysis.get("sections", {})
    if not sections:
        st.warning("분석 섹션을 파싱하지 못했습니다. Raw 결과를 표시합니다.")
        st.markdown(analysis.get("raw", ""))
        return

    for title, content in sections.items():
        color = _section_color(title)
        with st.expander(f"**{title}**", expanded=True):
            # 링크 포함 마크다운 렌더링
            st.markdown(
                f"<div style='border-left:3px solid {color};"
                f"padding-left:12px;color:#CAE9FF;line-height:1.8'>"
                f"{_md_to_streamlit(content)}</div>",
                unsafe_allow_html=True,
            )


def _md_to_streamlit(text: str) -> str:
    """마크다운 링크와 볼드를 HTML로 변환 (st.markdown unsafe_allow_html용)."""
    import re
    # URL → 클릭 가능 링크
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\)]+)\)",
        r'<a href="\2" target="_blank" style="color:#00B4D8">\1</a>',
        text,
    )
    # 마크다운 bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # 줄바꿈 유지
    text = text.replace("\n", "<br>")
    return text


def render_meta_banner(analysis: dict) -> None:
    date_str  = analysis.get("date", "")
    count     = analysis.get("article_count", 0)
    provider  = analysis.get("provider", "-")
    keywords  = ", ".join(analysis.get("keywords_found", [])[:6])
    notion_url = analysis.get("notion_url", "")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("분석 날짜", date_str)
    col2.metric("수집 기사", f"{count}건")
    col3.metric("분석 엔진", provider)
    col4.metric("매칭 키워드", f"{len(analysis.get('keywords_found', []))}개")

    if notion_url:
        st.link_button("📓 Notion에서 전체 보기", notion_url)

    if keywords:
        st.caption(f"🏷 키워드: {keywords}")


# ══════════════════════════════════════════════════════════════════════════════
# 분석 파이프라인 실행
# ══════════════════════════════════════════════════════════════════════════════

def run_analysis_pipeline(selected_kw: list[str]) -> dict | None:
    """분석 파이프라인 실행 — Streamlit status UI와 연동."""
    from src.collector import run_collection
    from src.analyzer import analyze_articles
    from src.ppt_generator import generate_ppt

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    result   = {}

    with st.status("🚀 분석 파이프라인 실행 중...", expanded=True) as status_box:

        # ── 1단계: 뉴스 수집 ──────────────────────────────────────────────────
        status_box.write("📡 **Step 1/4** — RSS 피드 및 Google News 수집 중...")
        prog = st.progress(0, text="피드 수집 중...")
        try:
            articles = run_collection(hours=26)
            prog.progress(25, text=f"✅ {len(articles)}건 수집 완료")
        except Exception as e:
            st.error(f"수집 실패: {e}")
            status_box.update(label="❌ 수집 단계 실패", state="error")
            return None

        if not articles:
            st.warning("수집된 기사가 없습니다. 키워드 또는 피드 설정을 확인하세요.")
            status_box.update(label="⚠️ 수집 기사 없음", state="error")
            return None

        result["articles"] = articles

        # ── 2단계: LLM 분석 ───────────────────────────────────────────────────
        status_box.write("🤖 **Step 2/4** — Multi-LLM 분석 시작 (Claude → Gemini → GPT 순)...")
        llm_placeholder = st.empty()

        def _ui_status(msg: str) -> None:
            llm_placeholder.info(msg)
            status_box.write(msg)

        prog.progress(30, text="LLM 분석 중...")
        try:
            analysis = analyze_articles(articles, date_str=date_str, status_fn=_ui_status)
            prog.progress(65, text=f"✅ {analysis['provider']} 분석 완료")
            llm_placeholder.success(f"✅ {analysis['provider']} 분석 완료")
        except Exception as e:
            st.error(f"LLM 분석 실패: {e}")
            status_box.update(label="❌ LLM 분석 실패", state="error")
            return None

        # ── 3단계: PPT 생성 ───────────────────────────────────────────────────
        status_box.write("📊 **Step 3/4** — PowerPoint 보고서 생성 중...")
        prog.progress(70, text="PPT 생성 중...")
        ppt_path = None
        try:
            import tempfile
            ppt_path = generate_ppt(analysis, output_dir=tempfile.gettempdir())
            analysis["ppt_path"] = ppt_path
            prog.progress(80, text="✅ PPT 생성 완료")
            status_box.write(f"✅ PPT 생성: `{Path(ppt_path).name}`")
        except Exception as e:
            status_box.write(f"⚠️ PPT 생성 실패 (계속 진행): {e}")

        # ── 4단계: Notion + Gmail ─────────────────────────────────────────────
        status_box.write("💾 **Step 4/4** — Notion 저장 및 Gmail 발송 중...")
        prog.progress(85, text="저장 및 발송 중...")

        if os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID"):
            try:
                from src.notion_client import save_daily_to_notion
                notion_url = save_daily_to_notion(analysis)
                analysis["notion_url"] = notion_url
                status_box.write(f"✅ Notion 저장 완료")
            except Exception as e:
                status_box.write(f"⚠️ Notion 저장 실패: {e}")

        if os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"):
            try:
                from src.email_sender import send_daily_email
                send_daily_email(analysis, ppt_path=ppt_path)
                status_box.write("✅ Gmail 발송 완료")
            except Exception as e:
                status_box.write(f"⚠️ Gmail 발송 실패: {e}")

        prog.progress(100, text="✅ 모든 단계 완료")
        status_box.update(
            label=f"✅ 분석 완료 — {len(articles)}건 기사, 분석 엔진: {analysis['provider']}",
            state="complete",
            expanded=False,
        )

    return analysis


# ══════════════════════════════════════════════════════════════════════════════
# Weekly 탭
# ══════════════════════════════════════════════════════════════════════════════

def render_weekly_tab() -> None:
    st.markdown("### 📅 Weekly Insights")

    notion_ok = os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DAILY_DB_ID")
    if not notion_ok:
        st.info("Notion 연동이 설정되지 않아 Weekly 데이터를 불러올 수 없습니다.")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("최근 7일간 누적 Daily 분석을 종합한 Weekly 보고서를 생성합니다.")
    with col2:
        run_weekly = st.button("📅 Weekly 보고서 생성", type="secondary",
                               use_container_width=True)

    if run_weekly:
        with st.status("Weekly 보고서 생성 중...", expanded=True) as ws:
            try:
                ws.write("📖 Notion에서 Daily 분석 데이터 조회 중...")
                from src.notion_client import fetch_weekly_analyses
                daily_list = fetch_weekly_analyses(days=7)
                ws.write(f"✅ {len(daily_list)}개 Daily 분석 로드 완료")

                if not daily_list:
                    st.warning("최근 7일간 Daily 분석 데이터가 없습니다.")
                    ws.update(label="⚠️ 데이터 없음", state="error")
                    return

                ws.write("🤖 Weekly LLM 분석 중...")
                from src.analyzer import analyze_weekly
                weekly = analyze_weekly(daily_list)
                ws.write(f"✅ {weekly['provider']} Weekly 분석 완료")

                from src.weekly_report import get_week_label
                week_label = get_week_label()

                ws.write("💾 Notion 저장 및 이메일 발송 중...")
                from src.notion_client import save_weekly_to_notion
                notion_url = save_weekly_to_notion(weekly, week_label)
                weekly["notion_url"] = notion_url

                if os.environ.get("GMAIL_ADDRESS"):
                    from src.email_sender import send_weekly_email
                    send_weekly_email(weekly, week_label)

                ws.update(label=f"✅ Weekly 보고서 완료: {week_label}", state="complete")
                st.session_state["weekly_analysis"] = weekly

            except Exception as e:
                st.error(f"Weekly 생성 실패: {e}")
                ws.update(label="❌ 실패", state="error")
                return

    if "weekly_analysis" in st.session_state:
        weekly = st.session_state["weekly_analysis"]
        st.markdown(f"**분석 엔진:** {weekly.get('provider', '-')} | "
                    f"**Daily 취합:** {weekly.get('daily_count', 0)}개")
        render_analysis_sections(weekly)


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # 사이드바
    selected_kw = render_sidebar()

    # 헤더
    st.markdown(
        "<h1 style='color:#00B4D8;font-size:26px;margin-bottom:4px'>"
        "⚡ Automotive / AI Semiconductor Strategy Brief"
        "</h1>"
        "<p style='color:#546E7A;font-size:13px;margin-top:0'>"
        "Multi-LLM 기반 자동 뉴스 분석 · SDV / Humanoid / Memory / Edge AI</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # 실행 버튼
    col_btn, col_info = st.columns([2, 5])
    with col_btn:
        run_clicked = st.button("▶  오늘의 전략 분석 실행", type="primary",
                                use_container_width=True)
    with col_info:
        kw_preview = ", ".join(selected_kw[:5])
        more = f" 외 {len(selected_kw)-5}개" if len(selected_kw) > 5 else ""
        st.markdown(
            f"<div style='padding:10px;color:#90A4AE;font-size:13px'>"
            f"🔍 분석 키워드: <strong style='color:#CAE9FF'>{kw_preview}{more}</strong></div>",
            unsafe_allow_html=True,
        )

    # 실행
    if run_clicked:
        analysis = run_analysis_pipeline(selected_kw)
        if analysis:
            st.session_state["daily_analysis"] = analysis
            st.session_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 탭 구성
    tab_daily, tab_weekly = st.tabs(["📊 Daily Analysis", "📅 Weekly Insights"])

    # ── Daily 탭 ──────────────────────────────────────────────────────────────
    with tab_daily:
        if "daily_analysis" not in st.session_state:
            st.markdown(
                "<div style='text-align:center;padding:60px;color:#546E7A'>"
                "<h3>분석 결과가 없습니다</h3>"
                "<p>상단의 <strong style='color:#00B4D8'>▶ 오늘의 전략 분석 실행</strong> "
                "버튼을 클릭하세요.</p></div>",
                unsafe_allow_html=True,
            )
        else:
            analysis = st.session_state["daily_analysis"]
            render_meta_banner(analysis)

            # PPT 다운로드 버튼
            ppt_path = analysis.get("ppt_path")
            if ppt_path and Path(ppt_path).exists():
                with open(ppt_path, "rb") as f:
                    st.download_button(
                        label="⬇ PPT 보고서 다운로드",
                        data=f,
                        file_name=Path(ppt_path).name,
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    )

            st.markdown("---")

            # 기사 목록 / 분석 결과 서브탭
            sub1, sub2 = st.tabs(["🗞 수집 기사", "📋 10가지 분석"])
            with sub1:
                render_article_cards(analysis.get("articles", []))
            with sub2:
                render_analysis_sections(analysis)

    # ── Weekly 탭 ─────────────────────────────────────────────────────────────
    with tab_weekly:
        render_weekly_tab()


if __name__ == "__main__":
    main()
