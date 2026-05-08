"""
python-pptx를 이용해 분석 결과를 PowerPoint 파일로 생성합니다.
NotebookLM은 공개 API가 없으므로 python-pptx로 직접 생성합니다.
"""
import re
import textwrap
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

# ── 색상 팔레트 ───────────────────────────────────────────────────────────────
C_BG        = RGBColor(0x0D, 0x1B, 0x2A)   # 짙은 네이비 (배경)
C_ACCENT    = RGBColor(0x00, 0xB4, 0xD8)   # 밝은 하늘색 (강조)
C_WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
C_LIGHT     = RGBColor(0xCA, 0xE9, 0xFF)   # 연한 파랑 (부제)
C_DARK_TEXT = RGBColor(0x1A, 0x1A, 0x2E)   # 슬라이드 내용 배경
C_BODY_BG   = RGBColor(0x16, 0x21, 0x33)   # 본문 배경

SECTION_ICONS = {
    "핵심 요약":       "01",
    "기술적 의미":     "02",
    "AI Agent":        "03",
    "비즈니스 영향":   "04",
    "Ecosystem":       "05",
    "향후 전망":       "06",
    "메모리":          "07",
    "스토리지 Workload": "08",
    "지역별":          "09",
    "Why Now":         "10",
}


def _get_icon(title: str) -> str:
    for key, icon in SECTION_ICONS.items():
        if key in title:
            return icon
    return "•"


def _set_slide_bg(slide, color: RGBColor) -> None:
    from pptx.oxml.ns import qn
    from lxml import etree

    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, text: str, left, top, width, height,
                 font_size=18, bold=False, color=None, align=PP_ALIGN.LEFT,
                 word_wrap=True) -> None:
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = word_wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color or C_WHITE


def _bullet_lines(text: str, max_chars: int = 90) -> list[str]:
    """마크다운 bullet을 정제하여 슬라이드용 줄 목록 반환 (최대 8줄)."""
    lines = []
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^\*{1,2}|#{1,3}\s*", "", stripped)
        stripped = re.sub(r"\*{1,2}", "", stripped)
        stripped = re.sub(r"\[.*?\]\(.*?\)", "", stripped)  # 마크다운 링크 제거
        if stripped.startswith("- ") or stripped.startswith("• "):
            stripped = "• " + stripped[2:]
        elif not stripped.startswith("•"):
            stripped = "• " + stripped
        # 긴 줄 줄바꿈
        for wrapped in textwrap.wrap(stripped, width=max_chars):
            lines.append(wrapped)
    return lines[:8]


def _add_content_slide(prs: Presentation, title: str, content: str, slide_num: int) -> None:
    blank_layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(blank_layout)
    _set_slide_bg(slide, C_BG)

    W = prs.slide_width
    H = prs.slide_height

    # 상단 컬러 바
    bar = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(0), Inches(0), W, Inches(0.08),
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = C_ACCENT
    bar.line.fill.background()

    # 섹션 번호 배지
    icon = _get_icon(title)
    badge = slide.shapes.add_shape(1, Inches(0.3), Inches(0.15), Inches(0.55), Inches(0.55))
    badge.fill.solid()
    badge.fill.fore_color.rgb = C_ACCENT
    badge.line.fill.background()
    tf = badge.text_frame
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    run = tf.paragraphs[0].add_run()
    run.text = icon
    run.font.size = Pt(14)
    run.font.bold = True
    run.font.color.rgb = C_BG

    # 슬라이드 제목
    _add_textbox(slide, title, Inches(1.0), Inches(0.12), Inches(8.5), Inches(0.6),
                 font_size=22, bold=True, color=C_WHITE)

    # 구분선
    line = slide.shapes.add_shape(1, Inches(0.3), Inches(0.82), Inches(9.1), Inches(0.02))
    line.fill.solid()
    line.fill.fore_color.rgb = C_ACCENT
    line.line.fill.background()

    # 본문 배경 박스
    content_box = slide.shapes.add_shape(
        1, Inches(0.3), Inches(0.95), Inches(9.1), Inches(5.8)
    )
    content_box.fill.solid()
    content_box.fill.fore_color.rgb = C_BODY_BG
    content_box.line.color.rgb = RGBColor(0x00, 0x70, 0x90)

    # 본문 텍스트박스
    body_tf_box = slide.shapes.add_textbox(
        Inches(0.55), Inches(1.05), Inches(8.7), Inches(5.5)
    )
    body_tf = body_tf_box.text_frame
    body_tf.word_wrap = True

    lines = _bullet_lines(content)
    if not lines:
        lines = ["• (내용 없음)"]

    first = True
    for line in lines:
        if first:
            p = body_tf.paragraphs[0]
            first = False
        else:
            p = body_tf.add_paragraph()
        p.space_before = Pt(4)
        run = p.add_run()
        run.text = line
        run.font.size = Pt(15)
        run.font.color.rgb = C_LIGHT

    # 슬라이드 번호
    _add_textbox(slide, f"{slide_num}", Inches(9.1), Inches(6.9), Inches(0.5), Inches(0.3),
                 font_size=11, color=RGBColor(0x55, 0x77, 0x99), align=PP_ALIGN.RIGHT)


def generate_ppt(analysis: dict, output_dir: str = "/tmp") -> str:
    """
    분석 결과 dict를 받아 .pptx 파일 생성.
    반환값: 저장된 파일 경로
    """
    prs = Presentation()
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(7.5)

    date_str     = analysis.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    art_count    = analysis.get("article_count", 0)
    provider     = analysis.get("provider", "-")
    keywords     = ", ".join(analysis.get("keywords_found", [])[:6])
    report_type  = analysis.get("type", "daily").upper()

    # ── 타이틀 슬라이드 ──────────────────────────────────────
    blank_layout = prs.slide_layouts[6]
    title_slide  = prs.slides.add_slide(blank_layout)
    _set_slide_bg(title_slide, C_BG)

    W = prs.slide_width

    # 상단 그라데이션 대신 두꺼운 컬러 바
    bar = title_slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.15))
    bar.fill.solid()
    bar.fill.fore_color.rgb = C_ACCENT
    bar.line.fill.background()

    _add_textbox(title_slide,
                 "Automotive / AI Semiconductor",
                 Inches(0.8), Inches(1.2), Inches(8.5), Inches(0.8),
                 font_size=28, bold=True, color=C_ACCENT, align=PP_ALIGN.CENTER)

    _add_textbox(title_slide,
                 f"Strategy Intelligence Brief  [{report_type}]",
                 Inches(0.8), Inches(2.0), Inches(8.5), Inches(0.7),
                 font_size=22, bold=False, color=C_WHITE, align=PP_ALIGN.CENTER)

    _add_textbox(title_slide,
                 date_str,
                 Inches(0.8), Inches(2.8), Inches(8.5), Inches(0.5),
                 font_size=18, color=C_LIGHT, align=PP_ALIGN.CENTER)

    # 메타 정보 박스
    meta_box = title_slide.shapes.add_shape(1, Inches(2.0), Inches(4.0), Inches(6.0), Inches(1.6))
    meta_box.fill.solid()
    meta_box.fill.fore_color.rgb = C_BODY_BG
    meta_box.line.color.rgb = C_ACCENT

    meta_text = f"수집 기사: {art_count}건  |  분석 엔진: {provider}\n키워드: {keywords}"
    _add_textbox(title_slide, meta_text,
                 Inches(2.1), Inches(4.1), Inches(5.8), Inches(1.4),
                 font_size=13, color=C_LIGHT, align=PP_ALIGN.CENTER)

    _add_textbox(title_slide,
                 "Generated by Multi-LLM Strategy Analyzer",
                 Inches(0.8), Inches(6.8), Inches(8.5), Inches(0.4),
                 font_size=10, color=RGBColor(0x44, 0x66, 0x88), align=PP_ALIGN.CENTER)

    # ── 섹션 슬라이드 10개 ────────────────────────────────────
    sections: dict = analysis.get("sections", {})
    if not sections:
        sections = {"분석 결과": analysis.get("raw", "(내용 없음)")}

    for idx, (sec_title, sec_content) in enumerate(sections.items(), start=2):
        _add_content_slide(prs, sec_title, sec_content, idx)

    # ── 마지막: 출처 슬라이드 ─────────────────────────────────
    last_slide = prs.slides.add_slide(blank_layout)
    _set_slide_bg(last_slide, C_BG)
    sources = "\n".join(f"• {s}" for s in analysis.get("sources", [])[:15])
    _add_textbox(last_slide, "데이터 출처 (Sources)",
                 Inches(0.5), Inches(0.3), Inches(9.0), Inches(0.6),
                 font_size=20, bold=True, color=C_ACCENT)
    _add_textbox(last_slide, sources or "출처 정보 없음",
                 Inches(0.5), Inches(1.1), Inches(9.0), Inches(5.5),
                 font_size=13, color=C_LIGHT)

    # ── 저장 ─────────────────────────────────────────────────
    filename = f"semiconductor_brief_{date_str}.pptx"
    filepath = str(Path(output_dir) / filename)
    prs.save(filepath)
    return filepath
