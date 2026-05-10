"""
NotebookLM 최적화 Markdown 파일 생성기.
분석 결과를 구조화된 Markdown으로 변환합니다.

NotebookLM 업로드 최적화:
- 명확한 H1/H2/H3 계층 구조
- 메타데이터 YAML 프론트매터
- 출처 링크 보존
- AI 기여 모델 명시
"""
import re
from datetime import datetime, timezone
from pathlib import Path


def generate_markdown(analysis: dict, output_dir: str = "/tmp") -> str:
    """
    분석 결과를 NotebookLM 최적화 Markdown으로 저장.

    Returns:
        저장된 .md 파일 경로
    """
    date_str    = analysis.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    report_type = analysis.get("type", "daily").upper()
    provider    = analysis.get("provider", "-")
    attribution = analysis.get("model_attribution", provider)
    art_count   = analysis.get("article_count", 0)
    keywords    = analysis.get("keywords_found", [])
    sources     = analysis.get("sources", [])
    source_urls = analysis.get("source_urls", [])
    sections    = analysis.get("sections", {})

    week_label = analysis.get("week_label", "")
    title_date = week_label if week_label else date_str

    # 파일명
    safe_date  = date_str.replace("-", "")
    filename   = f"semiconductor_brief_{report_type.lower()}_{safe_date}.md"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)   # 폴더 자동 생성
    filepath   = str(output_path / filename)

    lines = []

    # ── YAML 프론트매터 (NotebookLM 메타데이터용) ──────────────
    lines += [
        "---",
        f"title: \"AI/Semiconductor Daily News [{report_type}] {title_date}\"",
        f"date: {date_str}",
        f"type: {report_type}",
        f"article_count: {art_count}",
        f"keywords: [{', '.join(keywords[:10])}]",
        f"ai_models: \"{attribution}\"",
        f"generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "---",
        "",
    ]

    # ── 문서 제목 ─────────────────────────────────────────────
    lines += [
        f"# AI/Semiconductor Daily News [{report_type}]",
        f"## Automotive/Humanoid and Storage Intelligence",
        f"### {title_date}",
        "",
        "> **AI 기여 모델:** " + attribution,
        f"> **수집 기사:** {art_count}건 | **핵심 키워드:** {', '.join(keywords[:8])}",
        "",
        "---",
        "",
    ]

    # ── 10개 섹션 ─────────────────────────────────────────────
    if sections:
        for sec_title, sec_content in sections.items():
            lines.append(f"## {sec_title}")
            lines.append("")
            lines.append(_clean_and_format(sec_content))
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        # 섹션 파싱 실패 시 raw 텍스트 삽입
        raw = analysis.get("raw", "")
        lines.append("## 분석 결과")
        lines.append("")
        lines.append(raw)
        lines.append("")

    # ── 데이터 출처 ───────────────────────────────────────────
    lines.append("## 📚 데이터 출처 (Sources)")
    lines.append("")

    if source_urls:
        lines.append("### 참조 URL")
        for url in source_urls[:30]:
            lines.append(f"- {url}")
        lines.append("")

    if sources:
        lines.append("### 수집 미디어")
        for src in sorted(set(sources)):
            lines.append(f"- {src}")
        lines.append("")

    # ── NotebookLM 활용 가이드 ────────────────────────────────
    lines += [
        "---",
        "",
        "## 🤖 NotebookLM 활용 가이드",
        "",
        "이 문서를 NotebookLM에 업로드 후 아래 질문을 활용하세요:",
        "",
        "- **「오늘 가장 중요한 스토리지 Workload 변화는 무엇인가요?」**",
        "- **「WAF와 TBW 관점에서 차량용 SSD 선택 기준을 설명해주세요.」**",
        "- **「KV Cache 증가가 차량 내 스토리지 용량 계획에 미치는 영향은?」**",
        "- **「Zonal Architecture 전환 시 스토리지 아키텍처는 어떻게 바뀌나요?」**",
        "- **「이번 주 가장 주목할 기업과 그 이유는?」**",
        "",
    ]

    content = "\n".join(lines)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[Markdown] 저장 완료: {filepath}")
    return filepath


def _clean_and_format(text: str) -> str:
    """
    분석 텍스트를 NotebookLM에 최적화된 Markdown으로 정리.
    - 기존 ## 헤딩을 ### 으로 조정 (문서 계층 유지)
    - 출처 URL 형식 정규화
    - 마크다운 테이블 열 정렬 (파이프 세로 정렬)
    - 빈 줄 정리
    """
    if not text:
        return ""

    # ── 마크다운 테이블 감지 & 정렬 ─────────────────────────────────────────
    # 테이블 블록을 찾아 열 너비를 맞춘 뒤 앞뒤 빈 줄 보장
    def _reformat_table_block(m: re.Match) -> str:
        raw_table = m.group(0).strip()
        formatted  = _format_md_table(raw_table)
        return f"\n\n{formatted}\n\n"

    # 테이블: 2줄 이상의 |...| 블록
    text = re.sub(
        r"(?:^|\n)((?:\|[^\n]+\|\n?){2,})",
        _reformat_table_block,
        text,
        flags=re.MULTILINE,
    )

    # ## → ### (이미 ## 섹션 안에 있으므로)
    text = re.sub(r"^##\s+", "### ", text, flags=re.MULTILINE)
    text = re.sub(r"^###\s+", "#### ", text, flags=re.MULTILINE)

    # [출처: URL] 형식 → Markdown 링크
    text = re.sub(
        r"\[출처:\s*(https?://[^\]]+)\]",
        lambda m: f"[🔗 출처]({m.group(1).strip()})",
        text
    )

    # URL만 있는 경우 → 링크로 변환
    text = re.sub(
        r"(?<!\()(https?://\S+)(?!\))",
        lambda m: f"[🔗 {_short_url(m.group(1))}]({m.group(1)})",
        text
    )

    # 연속 빈 줄 → 단일 빈 줄
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _format_md_table(table_text: str) -> str:
    """
    마크다운 테이블 열 너비 정렬 (파이프 세로 정렬).
    Genspark / PPT 가독성 최적화.

    입력:  | A | B |
           |---|---|
           | 값1 | 값2 |

    출력:  | A   | B   |
           | --- | --- |
           | 값1 | 값2 |
    """
    lines = [ln for ln in table_text.split("\n") if ln.strip()]
    if not lines:
        return table_text

    parsed:   list[list[str] | None] = []   # None = 구분선
    sep_idx:  int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells if c.strip()):
            parsed.append(None)
            sep_idx = len(parsed) - 1
        else:
            parsed.append(cells)

    if not parsed:
        return table_text

    # 열 수 & 최대 너비 계산
    num_cols = max((len(r) for r in parsed if r is not None), default=0)
    if num_cols == 0:
        return table_text

    col_widths = [3] * num_cols   # 최소 3 (구분선 --- 에 맞춤)
    for row in parsed:
        if row is None:
            continue
        for j, cell in enumerate(row[:num_cols]):
            col_widths[j] = max(col_widths[j], len(cell))

    # 포맷된 라인 생성
    result: list[str] = []
    for row in parsed:
        if row is None:
            cells_str = " | ".join("-" * w for w in col_widths)
        else:
            padded = []
            for j in range(num_cols):
                cell = row[j] if j < len(row) else ""
                padded.append(cell.ljust(col_widths[j]))
            cells_str = " | ".join(padded)
        result.append(f"| {cells_str} |")

    return "\n".join(result)


def _short_url(url: str) -> str:
    """URL의 도메인 추출."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or url[:40]
    except Exception:
        return url[:40]
