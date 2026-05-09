"""
Notion 페이지 실제 생성 테스트 (속성 확인 포함)
실행: python tools/test_notion_write.py
"""
import os, sys, json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from notion_client import Client
from notion_client.errors import APIResponseError

token    = os.environ.get("NOTION_TOKEN", "")
daily_id = os.environ.get("NOTION_DAILY_DB_ID", "")

if not token or not daily_id:
    print("⛔  .env 파일에 NOTION_TOKEN, NOTION_DAILY_DB_ID가 없습니다.")
    sys.exit(1)

client = Client(auth=token)
today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── Step 1: 빈 페이지 생성 ─────────────────────────────────────
print(f"\n[1] 빈 페이지 생성 중...")
try:
    page = client.pages.create(
        parent={"database_id": daily_id},
        properties={},
    )
    page_id  = page["id"]
    page_url = page.get("url", "")
    print(f"  ✅ 생성 성공: {page_url}")
except APIResponseError as e:
    print(f"  ❌ 생성 실패: {e}")
    sys.exit(1)

# ── Step 2: 생성된 페이지의 속성 목록 확인 ─────────────────────
print(f"\n[2] 실제 속성 목록 확인...")
try:
    p = client.pages.retrieve(page_id=page_id)
    props = p.get("properties", {})
    print(f"  속성 개수: {len(props)}개")
    for name, info in props.items():
        ptype = info.get("type", "?")
        print(f"  - '{name}' (타입: {ptype})")
    print(f"\n  [RAW] {json.dumps(props, ensure_ascii=False)[:500]}")
except APIResponseError as e:
    print(f"  ❌ 페이지 조회 실패: {e}")

# ── Step 3: data_sources ID로 DB 직접 접근 시도 ────────────────
print(f"\n[3] data_sources ID로 DB 직접 접근 시도...")
try:
    db_view = client.databases.retrieve(database_id=daily_id)
    ds_list = db_view.get("data_sources", [])
    if ds_list:
        ds_id = ds_list[0]["id"].replace("-", "")
        print(f"  data_sources ID: {ds_id}")
        try:
            src_db = client.databases.retrieve(database_id=ds_id)
            src_props = src_db.get("properties", {})
            print(f"  ✅ 소스 DB 접근 성공! 속성 {len(src_props)}개:")
            for name, info in src_props.items():
                print(f"    - '{name}' ({info.get('type','?')})")
        except APIResponseError as e2:
            print(f"  ❌ 소스 DB 접근 실패: {e2}")
    else:
        print("  data_sources 없음")
except APIResponseError as e:
    print(f"  ❌ 뷰 DB 조회 실패: {e}")

print("\n완료!")
