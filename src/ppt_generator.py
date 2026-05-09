"""
PPT 생성기 — 사용자 템플릿 우선, 없으면 기본 스타일 사용.

우선순위:
  1. TEMPLATE_PATH 환경변수로 지정된 .pptx 파일
  2. templates/report_template.pptx (자동 탐색)
  3. 기본 다크 테마 자동 생성

템플릿 레이아웃 설정 (.env):
  TEMPLATE_PATH=templates/report_template.pptx
  TEMPLATE_TITLE_LAYOUT=0     # 표지 슬라이드 레이아웃 번호
  TEMPLATE_CONTENT_LAYOUT=1   # 내용 슬라이드 레이아웃 번호
  TEMPLATE_TITLE_PH=0         # 제목 플레이스홀더 idx
  TEMPLATE_BODY_PH=1          # 본문 플레이스홀더 idx
"""
import os
import re
import textwrap
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

# ── 색상 (기본 테마용) ─────────────────────────────────────────────────────────
C_BG      = RGBColor(0x0D, 0x1B, 0x2A)
C_ACCENT  = RGBColor(0x00, 0xB4, 0xD8)
C_WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
C_LIGHT   = RGBColor(0xCA, 0xE9, 0xFF)
C_BODY_BG = RGBColor(0x16, 0x21, 0x33)


# ══════════════════════════════════════════════════════════════════════════════
# 템플릿 탐색
# ══════════════════════════════════════════════════════════════════════════════

def _find_template() -> Path | None:
    """템플릿 파일 탐색 (환경변수 → 기본 경로)."""
    env_path = os.environ.get("TEMPLATE_PATH", "")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    root = Path(__file__).parent.parent
    candidates += [
        root / "templates" / "report_template.pptx",
        root / "templates" / "template.pptx",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _get_layout_cfg() -> dict:
    """레이아웃 인덱스 설정값 반환."""
    return {
        "title_layout":   int(os.environ.get("TEMPLATE_TITLE_LAYOUT",   "0")),
        "content_layout": int(os.environ.get("TEMPLATE_CONTENT_LAYOUT", "1")),
        "title_ph":       int(os.environ.get("TEMPLATE_TITLE_PH",       "0")),
        "body_ph":        int(os.environ.get("TEMPLATE_BODY_PH",        "1")),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 텍스트 처리 유틸
# ══════════════════════════════════════════════════════════════════════════════

def _clean_md(text: str) -> str:
    """마크다운 기호 제거 → 순수 텍스트."""
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)   # 링크
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)    # 볼드/이탤릭
    text = re.sub(r"^#{1,3}\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def _bullet_lines(text: str, max_lines: int = 10, max_chars: int = 95) -> list[str]:
    """섹션 본문 → 슬라이드용 bullet 줄 목록."""
    lines = []
    for raw in _clean_md(text).split("\n"):
        s = raw.strip()
        if not s:
            continue
        s = s.lstrip("-•·").strip()
        for wrapped in textwrap.wrap(s, width=max_chars):
            lines.append("• " + wrapped)
    return lines[:max_lines]


def _set_ph_text(placeholder, text: str, font_size: int = 14) -> None:
    """플레이스홀더에 텍스트 설정 (기존 서식 최대한 유지)."""
    tf = placeholder.text_frame
    tf.clear()
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    if font_size:
        run.font.size = Pt(font_size)


def _set_ph_bullets(placeholder, lines: list[str], font_size: int = 13) -> None:
    """플레이스홀더에 bullet 목록 설정."""
    tf = placeholder.text_frame
    tf.clear()
    tf.word_wrap = True
    first = True
    for line in lines:
        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()
        p.space_before = Pt(3)
        run = p.add_run()
        run.text = line
        if font_size:
            run.font.size = Pt(font_size)


def _find_placeholder(slide, idx: int):
    """idx로 플레이스홀더 찾기."""
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == idx:
            return ph
    return None


def _add_textbox_fallback(slide, text: str, top_offset: float = 1.5) -> None:
    """플레이스홀더가 없을 때 텍스트박스로 대체."""
    W = slide.shapes._spTree.getparent().getparent().presentation.slide_width
    H = slide.shapes._spTree.getparent().getparent().presentation.slide_height
    txb = slide.shapes.add_textbox(
        Inches(0.5), Inches(top_offset), W - Inches(1.0), H - Inches(top_offset + 0.3)
    )
    tf = txb.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].text = text
    tf.paragraphs[0].runs[0].font.size = Pt(13)


# ══════════════════════════════════════════════════════════════════════════════
# 템플릿 기반 PPT 생성
# ══════════════════════════════════════════════════════════════════════════════

def _build_with_template(
    template_path: Path,
    analysis: dict,
    cfg: dict,
) -> Presentation:
    """사용자 템플릿을 열어 분석 결과를 채워넣기."""
    prs = Presentation(str(template_path))

    date_str   = analysis.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    provider   = analysis.get("provider", "-")
    art_count  = analysis.get("article_count", 0)
    report_type = analysis.get("type", "daily").upper()
    week_label  = analysis.get("week_label", "")
    subtitle    = week_label if week_label else date_str
    sections: dict = analysis.get("sections", {})

    title_layout_idx   = cfg["title_layout"]
    content_layout_idx = cfg["content_layout"]
    title_ph_idx       = cfg["title_ph"]
    body_ph_idx        = cfg["body_ph"]

    # 레이아웃 안전 참조
    n_layouts = len(prs.slide_layouts)
    title_layout   = prs.slide_layouts[min(title_layout_idx,   n_layouts - 1)]
    content_layout = prs.slide_layouts[min(content_layout_idx, n_layouts - 1)]

    # ── 표지 슬라이드 ──────────────────────────────────────────
    slide = prs.slides.add_slide(title_layout)

    ph_title = _find_placeholder(slide, title_ph_idx)
    if ph_title:
        _set_ph_text(ph_title,
                     f"Automotive / AI Semiconductor\nStrategy Brief  [{report_type}]",
                     font_size=0)  # 0 = 기존 서식 유지
    else:
        _add_textbox_fallback(slide, f"Automotive / AI Semiconductor Brief [{report_type}]", 1.0)

    ph_body = _find_placeholder(slide, body_ph_idx)
    cover_body = (
        f"{subtitle}\n"
        f"수집 기사: {art_count}건  |  분석 엔진: {provider}\n"
        f"키워드: {', '.join(analysis.get('keywords_found', [])[:5])}"
    )
    if ph_body:
        _set_ph_text(ph_body, cover_body, font_size=0)
    else:
        _add_textbox_fallback(slide, cover_body, 3.5)

    # ── 섹션 슬라이드 (10개) ───────────────────────────────────
    if not sections:
        sections = {"분석 결과": analysis.get("raw", "(내용 없음)")}

    for sec_title, sec_content in sections.items():
        slide = prs.slides.add_slide(content_layout)

        # 제목 플레이스홀더
        ph_t = _find_placeholder(slide, title_ph_idx)
        if ph_t:
            _set_ph_text(ph_t, sec_title, font_size=0)
        else:
            _add_textbox_fallback(slide, sec_title, 0.3)

        # 본문 플레이스홀더
        ph_b = _find_placeholder(slide, body_ph_idx)
        lines = _bullet_lines(sec_content, max_lines=10)
        if ph_b:
            _set_ph_bullets(ph_b, lines, font_size=0)
        else:
            _add_textbox_fallback(slide, "\n".join(lines), 1.4)

    # ── 출처 슬라이드 ─────────────────────────────────────────
    slide = prs.slides.add_slide(content_layout)
    ph_t = _find_placeholder(slide, title_ph_idx)
    if ph_t:
        _set_ph_text(ph_t, "데이터 출처 (Sources)", font_size=0)

    ph_b = _find_placeholder(slide, body_ph_idx)
    sources = "\n".join(f"• {s}" for s in analysis.get("sources", [])[:15])
    if ph_b:
        _set_ph_bullets(ph_b, sources.split("\n"), font_size=0)
    else:
        _add_textbox_fallback(slide, sources, 1.4)

    return prs


# ══════════════════════════════════════════════════════════════════════════════
# 기본 다크 테마 PPT 생성 (템플릿 없을 때 폴백)
# ══════════════════════════════════════════════════════════════════════════════

def _set_bg(slide, color: RGBColor) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _add_tb(slide, text, l, t, w, h, size=14, bold=False,
            color=None, align=PP_ALIGN.LEFT) -> None:
    txb = slide.shapes.add_textbox(l, t, w, h)
    tf  = txb.text_frame
    tf.word_wrap = True
    p   = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color or C_WHITE


def _build_default(analysis: dict) -> Presentation:
    """템플릿 없을 때 사용하는 기본 다크 테마."""
    prs = Presentation()
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    date_str   = analysis.get("date", "")
    art_count  = analysis.get("article_count", 0)
    provider   = analysis.get("provider", "-")
    report_type = analysis.get("type", "daily").upper()
    week_label  = analysis.get("week_label", "")
    subtitle    = week_label if week_label else date_str
    sections    = analysis.get("sections", {}) or {"분석결과": analysis.get("raw","")}
    W = prs.slide_width

    # 표지
    s = prs.slides.add_slide(blank)
    _set_bg(s, C_BG)
    bar = s.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.12))
    bar.fill.solid(); bar.fill.fore_color.rgb = C_ACCENT; bar.line.fill.background()
    _add_tb(s, f"Automotive / AI Semiconductor  [{report_type}]",
            Inches(0.8), Inches(1.5), Inches(8.5), Inches(0.8),
            size=24, bold=True, color=C_ACCENT, align=PP_ALIGN.CENTER)
    _add_tb(s, subtitle,
            Inches(0.8), Inches(2.4), Inches(8.5), Inches(0.5),
            size=16, color=C_WHITE, align=PP_ALIGN.CENTER)
    _add_tb(s, f"수집 기사: {art_count}건  |  분석 엔진: {provider}",
            Inches(0.8), Inches(3.0), Inches(8.5), Inches(0.4),
            size=13, color=C_LIGHT, align=PP_ALIGN.CENTER)

    # 섹션 슬라이드
    for i, (title, content) in enumerate(sections.items(), 2):
        s = prs.slides.add_slide(blank)
        _set_bg(s, C_BG)
        bar = s.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.07))
        bar.fill.solid(); bar.fill.fore_color.rgb = C_ACCENT; bar.line.fill.background()
        _add_tb(s, title, Inches(0.3), Inches(0.1), Inches(9.2), Inches(0.6),
                size=20, bold=True, color=C_ACCENT)
        box = s.shapes.add_shape(1, Inches(0.3), Inches(0.85), Inches(9.2), Inches(6.2))
        box.fill.solid(); box.fill.fore_color.rgb = C_BODY_BG; box.line.fill.background()
        body_tb = s.shapes.add_textbox(Inches(0.5), Inches(0.95), Inches(8.9), Inches(6.0))
        body_tf = body_tb.text_frame
        body_tf.word_wrap = True
        lines = _bullet_lines(content, max_lines=10)
        first = True
        for line in lines:
            p = body_tf.paragraphs[0] if first else body_tf.add_paragraph()
            first = False
            p.space_before = Pt(4)
            run = p.add_run()
            run.text = line
            run.font.size = Pt(14)
            run.font.color.rgb = C_LIGHT
        _add_tb(s, str(i), Inches(9.2), Inches(7.1), Inches(0.5), Inches(0.3),
                size=10, color=RGBColor(0x44,0x66,0x88), align=PP_ALIGN.RIGHT)

    return prs


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def generate_ppt(analysis: dict, output_dir: str = "/tmp") -> str:
    """
    분석 결과를 PPT로 저장.
    사용자 템플릿이 있으면 템플릿 사용, 없으면 기본 다크 테마.
    반환값: 저장된 .pptx 경로
    """
    date_str = analysis.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    filename = f"semiconductor_brief_{date_str}.pptx"
    filepath = str(Path(output_dir) / filename)

    template = _find_template()
    if template:
        print(f"[PPT] 템플릿 사용: {template.name}")
        cfg = _get_layout_cfg()
        prs = _build_with_template(template, analysis, cfg)
    else:
        print("[PPT] 템플릿 없음 → 기본 다크 테마 사용")
        prs = _build_default(analysis)

    prs.save(filepath)
    print(f"[PPT] 저장 완료: {filepath}")
    return filepath
