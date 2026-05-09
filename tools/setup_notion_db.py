"""
Notion DB 속성(컬럼) 자동 설정 스크립트
실행: python tools/setup_notion_db.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from notion_client import Client
from notion_client.errors import APIResponseError


def setup_db(client: Client, db_id: str, db_name: str) -> None:
    print(f"\n[{db_name}] DB 속성 설정 중...")

    # 현재 속성 조회
    try:
        db = client.databases.retrieve(database_id=db_id)
    except APIResponseError as e:
        print(f"  ❌ DB 접근 실패: {e}")
        return

    existing = db.get("properties", {})
    print(f"  현재 속성: {list(existing.keys())}")

    # 추가할 속성 정의
    to_add = {}

    if "Date" not in existing:
        to_add["Date"] = {"date": {}}
        print("  + Date 속성 추가 예정")

    if "Type" not in existing:
        to_add["Type"] = {
            "select": {
                "options": [
                    {"name": "Daily", "color": "blue"},
                    {"name": "Weekly", "color": "green"},
                ]
            }
        }
        print("  + Type 속성 추가 예정")

    if "Keywords" not in existing:
        to_add["Keywords"] = {"multi_select": {"options": []}}
        print("  + Keywords 속성 추가 예정")

    if "Articles" not in existing:
        to_add["Articles"] = {"number": {"format": "number"}}
        print("  + Articles 속성 추가 예정")

    if not to_add:
        print("  ✅ 모든 속성이 이미 존재합니다.")
        return

    # 속성 업데이트
    try:
        client.databases.update(
            database_id=db_id,
            properties=to_add,
        )
        print(f"  ✅ {len(to_add)}개 속성 추가 완료!")
    except APIResponseError as e:
        print(f"  ❌ 속성 추가 실패: {e}")


def main():
    print("\n══════════════════════════════════════")
    print("  Notion DB 속성 자동 설정")
    print("══════════════════════════════════════")

    token    = os.environ.get("NOTION_TOKEN", "")
    daily_id = os.environ.get("NOTION_DAILY_DB_ID", "")
    week_id  = os.environ.get("NOTION_WEEKLY_DB_ID", "")

    if not token:
        print("⛔ NOTION_TOKEN이 없습니다.")
        sys.exit(1)

    client = Client(auth=token)

    if daily_id:
        setup_db(client, daily_id, "Daily DB")
    else:
        print("\n⚠️  NOTION_DAILY_DB_ID 미설정")

    if week_id:
        setup_db(client, week_id, "Weekly DB")
    else:
        print("\n⚠️  NOTION_WEEKLY_DB_ID 미설정")

    print("\n══════════════════════════════════════")
    print("  완료! 이제 check_notion.py를 실행하세요.")
    print("══════════════════════════════════════\n")


if __name__ == "__main__":
    main()
