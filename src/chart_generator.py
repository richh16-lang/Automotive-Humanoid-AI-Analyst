"""
차트 생성기.
- Notion 이미지 블록용: QuickChart.io URL (외부 호스팅 불필요, URL만으로 차트 생성)
- Word 문서 임베딩용: matplotlib PNG bytes
"""
import io
import json
import urllib.parse
from typing import Optional

QUICKCHART_BASE = "https://quickchart.io/chart"

# 팔레트 (다크 네이비 테마)
_BLUES = ["#00B4D8", "#0096C7", "#0077B6", "#48CAE4",
          "#ADE8F4", "#90E0EF", "#023E8A", "#CAE9FF"]


def _setup_korean_font() -> None:
    """
    matplotlib 한글 폰트 설정 (Windows: 맑은 고딕, macOS: AppleGothic, Linux: NanumGothic).
    깨짐 방지 및 마이너스 부호 정상 출력.
    """
    import platform
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    plt.rcParams["axes.unicode_minus"] = False   # 마이너스 부호 깨짐 방지

    system = platform.system()
    candidates = []

    if system == "Windows":
        candidates = ["Malgun Gothic", "맑은 고딕", "NanumGothic", "Gulim", "Dotum"]
    elif system == "Darwin":
        candidates = ["AppleGothic", "Apple SD Gothic Neo", "NanumGothic"]
    else:
        candidates = ["NanumGothic", "NanumBarunGothic", "UnDotum", "DejaVu Sans"]

    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            return

    # 후보가 없으면 시스템에 있는 한글 지원 폰트 직접 탐색
    for f in fm.fontManager.ttflist:
        if any(k in f.name for k in ["Gothic", "Gothic", "Nanum", "Malgun", "고딕"]):
            plt.rcParams["font.family"] = f.name
            return


# ══════════════════════════════════════════════════════════════════════════════
# 휴머노이드 Chipset 채택 현황 차트
# ══════════════════════════════════════════════════════════════════════════════

def _load_chipset_baseline() -> dict:
    from pathlib import Path
    import json as _json
    p = Path(__file__).parent.parent / "data" / "humanoid_chipset_baseline.json"
    if not p.exists():
        return {}
    return _json.loads(p.read_text(encoding="utf-8"))


def humanoid_chipset_pie_bytes(status_filter: list | None = None) -> bytes:
    """
    휴머노이드 chipset 채택 현황 파이 차트 (matplotlib PNG bytes).
    status_filter: None = 전체 / ["confirmed"] = 확정만
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    _setup_korean_font()

    data   = _load_chipset_baseline()
    companies = data.get("companies", {})

    # 벤더별 카운트
    counts: dict[str, int] = {}
    for info in companies.values():
        if status_filter and info.get("status") not in status_filter:
            continue
        vendor = info.get("chip_vendor", "기타")
        counts[vendor] = counts.get(vendor, 0) + 1

    if not counts:
        return b""

    COLORS = {
        "NVIDIA":   "#76b900",
        "Qualcomm": "#3253DC",
        "In-house": "#FF6B35",
        "기타":     "#888888",
    }

    labels = list(counts.keys())
    sizes  = list(counts.values())
    colors = [COLORS.get(l, "#888888") for l in labels]
    total  = sum(sizes)

    fig, ax = plt.subplots(figsize=(7, 5))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,
        autopct=lambda p: f"{p:.1f}%\n({int(round(p * total / 100))}개)",
        colors=colors,
        startangle=140,
        pctdistance=0.75,
        wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
    )
    for at in autotexts:
        at.set_fontsize(10)
        at.set_color("white")
        at.set_fontweight("bold")

    legend = [mpatches.Patch(color=COLORS.get(l, "#888888"), label=f"{l}  {c}개")
              for l, c in zip(labels, sizes)]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=len(labels), fontsize=10, frameon=False)

    title_suffix = "(확정)" if status_filter == ["confirmed"] else "(전체)"
    ax.set_title(f"휴머노이드 Chipset 채택 현황 {title_suffix}\n기준: {data.get('_meta', {}).get('updated', '')}",
                 fontsize=13, fontweight="bold", pad=15)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150,
                facecolor="#1a2744", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def humanoid_chipset_pie_url(status_filter: list | None = None,
                              w: int = 500, h: int = 400) -> str:
    """
    휴머노이드 chipset 채택 현황 파이 차트 QuickChart URL (Notion용).
    """
    data      = _load_chipset_baseline()
    companies = data.get("companies", {})

    counts: dict[str, int] = {}
    for info in companies.values():
        if status_filter and info.get("status") not in status_filter:
            continue
        vendor = info.get("chip_vendor", "기타")
        counts[vendor] = counts.get(vendor, 0) + 1

    if not counts:
        return ""

    COLORS = {"NVIDIA": "#76b900", "Qualcomm": "#3253DC",
              "In-house": "#FF6B35", "기타": "#888888"}

    labels  = list(counts.keys())
    sizes   = list(counts.values())
    updated = data.get("_meta", {}).get("updated", "")

    chart = {
        "type": "pie",
        "data": {
            "labels": [f"{l} ({v}개)" for l, v in zip(labels, sizes)],
            "datasets": [{"data": sizes,
                          "backgroundColor": [COLORS.get(l, "#888888") for l in labels]}],
        },
        "options": {
            "title": {"display": True,
                      "text": f"휴머노이드 Chipset 채택 현황 ({updated})",
                      "fontColor": "#ffffff", "fontSize": 14},
            "legend": {"labels": {"fontColor": "#ffffff", "fontSize": 12}},
        },
    }
    return _qc_url(chart, w=w, h=h)


# ══════════════════════════════════════════════════════════════════════════════
# QuickChart.io URL 생성 (Notion image 블록용)
# ══════════════════════════════════════════════════════════════════════════════

def _qc_url(chart: dict, w: int = 600, h: int = 280, bg: str = "#1a2744") -> str:
    """QuickChart.io URL 생성."""
    params = {
        "c":   json.dumps(chart, ensure_ascii=False),
        "w":   str(w),
        "h":   str(h),
        "bkg": bg,
    }
    return QUICKCHART_BASE + "?" + urllib.parse.urlencode(params)


def keyword_chart_url(keywords: list, w: int = 650, h: int = 300) -> str:
    """
    핵심 키워드 우선순위 가로 막대 차트 URL.
    keywords: 우선순위 높은 순 정렬된 리스트
    """
    if not keywords:
        return ""
    labels = [str(k) for k in keywords[:10]][::-1]      # 위→아래 낮은→높은
    values = list(range(1, len(labels) + 1))              # 1~N 점수

    chart = {
        "type": "horizontalBar",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "우선순위",
                "data":  values,
                "backgroundColor": "#00B4D8",
                "borderColor":     "#0096C7",
                "borderWidth": 1,
            }],
        },
        "options": {
            "plugins": {"legend": {"display": False}},
            "title":   {
                "display":   True,
                "text":      "핵심 키워드 우선순위",
                "fontColor": "#ffffff",
                "fontSize":  13,
            },
            "scales": {
                "xAxes": [{"display": False}],
                "yAxes": [{"ticks": {"fontColor": "#ffffff", "fontSize": 11}}],
            },
        },
    }
    return _qc_url(chart, w, h)


def source_chart_url(sources: list, w: int = 520, h: int = 280) -> str:
    """출처별 기사 분포 도넛 차트 URL."""
    if not sources:
        return ""
    from collections import Counter
    top = Counter(sources).most_common(8)
    if not top:
        return ""
    labels = [item[0] for item in top]
    values = [item[1] for item in top]

    chart = {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [{
                "data":            values,
                "backgroundColor": _BLUES[:len(labels)],
            }],
        },
        "options": {
            "plugins": {
                "legend": {
                    "position": "right",
                    "labels":   {"fontColor": "#cccccc", "fontSize": 10},
                },
            },
            "title": {
                "display":   True,
                "text":      "데이터 출처 분포",
                "fontColor": "#ffffff",
                "fontSize":  13,
            },
        },
    }
    return _qc_url(chart, w, h)


def workload_chart_url(w: int = 480, h: int = 260) -> str:
    """차량용 스토리지 Read/Write 비율 도넛 차트 URL."""
    chart = {
        "type": "doughnut",
        "data": {
            "labels": ["Write 80%\n(ADAS 로그·KV Cache)", "Read 20%\n(맵·펌웨어)"],
            "datasets": [{
                "data":            [80, 20],
                "backgroundColor": ["#00B4D8", "#023E8A"],
            }],
        },
        "options": {
            "plugins": {
                "legend": {
                    "position": "right",
                    "labels":   {"fontColor": "#cccccc", "fontSize": 11},
                },
            },
            "title": {
                "display":   True,
                "text":      "차량용 스토리지 Read/Write 비율",
                "fontColor": "#ffffff",
                "fontSize":  13,
            },
        },
    }
    return _qc_url(chart, w, h)


# ══════════════════════════════════════════════════════════════════════════════
# matplotlib PNG bytes (Word 문서 임베딩용)
# ══════════════════════════════════════════════════════════════════════════════

def _mpl_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def make_keyword_chart_bytes(keywords: list) -> Optional[bytes]:
    """키워드 막대 차트 PNG bytes (Word 임베딩용)."""
    if not keywords or not _mpl_available():
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _setup_korean_font()   # ← 한글 폰트 설정

        labels = [str(k) for k in keywords[:10]][::-1]
        values = list(range(1, len(labels) + 1))

        fig, ax = plt.subplots(figsize=(7.5, max(2.8, len(labels) * 0.38)))
        fig.patch.set_facecolor("#162133")
        ax.set_facecolor("#1e2d45")

        ax.barh(labels, values, color="#00B4D8", edgecolor="#0096C7", height=0.65)
        ax.set_title("핵심 키워드 우선순위", color="#00B4D8",
                     fontsize=12, fontweight="bold", pad=8)
        ax.tick_params(colors="#CAE9FF", labelsize=9.5)
        ax.xaxis.set_visible(False)
        for spine in ["top", "right", "bottom"]:
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#334466")

        plt.tight_layout(pad=0.8)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        print(f"[Chart] 키워드 차트 생성 실패: {exc}")
        return None


def make_source_chart_bytes(sources: list) -> Optional[bytes]:
    """출처 분포 파이 차트 PNG bytes (Word 임베딩용)."""
    if not sources or not _mpl_available():
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from collections import Counter

        _setup_korean_font()   # ← 한글 폰트 설정

        top = Counter(sources).most_common(7)
        if not top:
            return None
        labels = [item[0] for item in top]
        values = [item[1] for item in top]
        colors = _BLUES[:len(labels)]

        fig, ax = plt.subplots(figsize=(6, 3.4))
        fig.patch.set_facecolor("#162133")

        wedges, _, autotexts = ax.pie(
            values, labels=labels, colors=colors,
            autopct="%1.0f%%", pctdistance=0.78,
            textprops={"color": "#CAE9FF", "fontsize": 8.5},
            wedgeprops={"linewidth": 1.2, "edgecolor": "#162133"},
        )
        for at in autotexts:
            at.set_color("#0D1B2A")
            at.set_fontsize(7.5)
            at.set_fontweight("bold")
        ax.set_title("데이터 출처 분포", color="#00B4D8",
                     fontsize=11, fontweight="bold", pad=6)
        ax.set_facecolor("#162133")

        plt.tight_layout(pad=0.6)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        print(f"[Chart] 출처 차트 생성 실패: {exc}")
        return None


def make_workload_chart_bytes() -> Optional[bytes]:
    """스토리지 Read/Write 비율 도넛 차트 PNG bytes."""
    if not _mpl_available():
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _setup_korean_font()   # ← 한글 폰트 설정

        fig, ax = plt.subplots(figsize=(5, 3.2))
        fig.patch.set_facecolor("#162133")

        labels = ["Write 80%\n(ADAS·KV Cache)", "Read 20%\n(맵·펌웨어)"]
        values = [80, 20]
        colors = ["#00B4D8", "#023E8A"]

        wedges, _, autotexts = ax.pie(
            values, labels=labels, colors=colors,
            autopct="%1.0f%%", pctdistance=0.78,
            textprops={"color": "#CAE9FF", "fontsize": 9},
            wedgeprops={"linewidth": 1.2, "edgecolor": "#162133"},
            startangle=90,
        )
        for at in autotexts:
            at.set_fontweight("bold")
        ax.set_title("차량용 스토리지 Read/Write 비율",
                     color="#00B4D8", fontsize=11, fontweight="bold", pad=6)
        ax.set_facecolor("#162133")

        plt.tight_layout(pad=0.6)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        print(f"[Chart] 워크로드 차트 생성 실패: {exc}")
        return None
