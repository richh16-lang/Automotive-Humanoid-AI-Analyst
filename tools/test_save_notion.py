"""
Notion 실제 저장 테스트
실행: python tools/test_save_notion.py
"""
import sys, os
from pathlib import Path

# 프로젝트 루트를 경로에 추가 (src/ 폴더가 아닌 루트)
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from dotenv import load_dotenv
load_dotenv(root / ".env")

# src 폴더를 직접 임포트
import importlib.util

spec = importlib.util.spec_from_file_location(
    "notion_saver",
    root / "src" / "notion_client.py"
)
notion_saver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notion_saver)

print("\n[Notion 저장 테스트]")
print("DB ID:", os.environ.get("NOTION_DAILY_DB_ID", "없음"))

test_data = {
    "date": "2026-05-09",
    "provider": "Claude",
    "article_count": 5,
    "keywords_found": ["SDV", "NVIDIA", "Tesla"],
    "sources": ["Reuters", "Bloomberg"],
    "sections": {
        "1. 핵심 요약": "오늘 반도체 시장에서 중요한 움직임이 있었습니다.",
        "2. 주요 뉴스": "NVIDIA가 새로운 자동차용 AI 칩을 발표했습니다.",
        "3. 시장 동향": "글로벌 반도체 수요가 회복세를 보이고 있습니다.",
    },
    "raw": ""
}

try:
    url = notion_saver.save_daily_to_notion(test_data)
    print(f"\n✅ 저장 성공!")
    print(f"   URL: {url}")
    print(f"\nNotion에서 'Daily News Analysis' 페이지를 열어 확인하세요!")
except Exception as e:
    print(f"\n❌ 저장 실패: {e}")
    import traceback
    traceback.print_exc()
