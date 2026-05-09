"""
Notion 연동 상태 진단 스크립트
실행: python tools/check_notion.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from notion_client import Client

def check(label: str, ok: bool, detail: str = "") -> None:
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {label}", f"→ {detail}" if detail else "")

def query_db(client: Client, db_id: str, page_size: int = 5) -> dict:
    """notion-client 버전에 무관하게 DB 쿼리."""
    # v2.x 방식
    if hasattr(client.databases, "query"):
        try:
            return client.databases.query(**{"database_id": db_id, "page_size": page_size})
        except Exception:
            pass
    # fallback: raw HTTP
    try:
        return client.request(
            path=f"databases/{db_id}/query",
            method="POST",
            body={"page_size": page_size},
        )
    except Exception as e:
        return {"results": [], "_error": str(e)}

def main():
    print("\n══════════════════════════════════════")
    print("  Notion 연동 진단 도구")
    print("══════════════════════════════════════\n")

    token    = os.environ.get("NOTION_TOKEN", "")
    daily_id = os.environ.get("NOTION_DAILY_DB_ID", "")
    week_id  = os.environ.get("NOTION_WEEKLY_DB_ID", "")

    # ── 1. 환경변수 확인 ──────────────────────────────────────
    print("[1] 환경변수 확인")
    check("NOTION_TOKEN",        bool(token),    token[:20] + "..." if token else "없음")
    check("NOTION_DAILY_DB_ID",  bool(daily_id), daily_id or "없음")
    check("NOTION_WEEKLY_DB_ID", bool(week_id),  week_id  or "없음")

    if not token:
        print("\n⛔  NOTION_TOKEN이 없습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    client = Client(auth=token)

    # ── 2. Integration 권한 확인 ──────────────────────────────
    print("\n[2] Notion API 연결 확인")
    try:
        me = client.users.me()
        check("API 연결", True, f"봇 이름: {me.get('name','?')}")
    except Exception as e:
        check("API 연결", False, str(e))
        print("\n⛔  토큰이 잘못됐거나 만료됐습니다.")
        sys.exit(1)

    # ── 3. Daily DB 접근 + 속성 확인 ─────────────────────────
    print("\n[3] Daily DB 확인")
    if not daily_id:
        print("  ⚠️  NOTION_DAILY_DB_ID 미설정 — 건너뜀")
    else:
        try:
            db = client.databases.retrieve(database_id=daily_id)
            title_list = db.get("title", [])
            db_title = title_list[0].get("plain_text", "?") if title_list else "?"
            check("DB 접근", True, db_title)

            # ── 디버그: 실제 API 응답 확인 ──
            import json
            print(f"\n  [DEBUG] DB object keys: {list(db.keys())}")
            raw_ds = db.get("data_sources", "KEY_MISSING")
            print(f"  [DEBUG] data_sources: {json.dumps(raw_ds, ensure_ascii=False)[:600]}")

            props = db.get("properties", {})
            print(f"\n  DB 속성 목록 (총 {len(props)}개):")

            # 실제 속성 이름 출력 (디버그)
            if props:
                for k, v in props.items():
                    print(f"    - '{k}' ({v.get('type','?')})")
            else:
                print("    (속성 없음 — setup_notion_db.py를 먼저 실행하세요)")

            needed = {"Name": "title", "Date": "date", "Type": "select",
                      "Keywords": "multi_select", "Articles": "number"}
            all_ok = True
            for pname, ptype in needed.items():
                if pname in props:
                    actual = props[pname]["type"]
                    ok = actual == ptype
                    if not ok:
                        all_ok = False
                    check(f"  속성 '{pname}'", ok,
                          f"타입: {actual}" + ("" if ok else f" (기대값: {ptype})"))
                else:
                    all_ok = False
                    check(f"  속성 '{pname}'", False, "없음 ← 추가 필요")

            if not all_ok:
                print("\n  💡 python tools/setup_notion_db.py 를 실행하면 속성이 자동 추가됩니다.")

            # 페이지 쿼리
            pages = query_db(client, daily_id)
            err = pages.get("_error")
            if err:
                check("페이지 조회", False, err)
            else:
                total = len(pages.get("results", []))
                check("페이지 조회", True, f"최근 {total}개 페이지 확인됨")

                if total > 0:
                    print("\n  최근 페이지 목록:")
                    for p in pages["results"]:
                        title_prop = p["properties"].get("Name", {}).get("title", [])
                        t = title_prop[0]["plain_text"] if title_prop else "(제목 없음)"
                        date_prop  = p["properties"].get("Date", {}).get("date") or {}
                        d = date_prop.get("start", "날짜없음")
                        print(f"    • [{d}] {t[:60]}")

                    last_id = pages["results"][0]["id"]
                    blocks  = client.blocks.children.list(block_id=last_id)
                    bcount  = len(blocks.get("results", []))
                    check("최근 페이지 블록 수", bcount > 0,
                          f"{bcount}개" + (" ← 내용 있음" if bcount > 0 else " ← 내용 없음!"))

        except Exception as e:
            check("Daily DB 접근", False, str(e))
            if "Could not find database" in str(e):
                print("\n  ⛔  DB ID가 잘못됐거나 Integration이 DB에 공유되지 않았습니다.")
                print("     Notion DB 페이지 → 우측 상단 ··· → Connections → Integration 추가")
            elif "is a page, not a database" in str(e):
                print("\n  ⛔  페이지 ID를 입력했습니다. DB 내부 테이블의 URL을 확인하세요.")

    # ── 4. Weekly DB 확인 ─────────────────────────────────────
    print("\n[4] Weekly DB 확인")
    if not week_id:
        print("  ⚠️  NOTION_WEEKLY_DB_ID 미설정 — 건너뜀")
    else:
        try:
            db = client.databases.retrieve(database_id=week_id)
            title_list = db.get("title", [])
            db_title = title_list[0].get("plain_text", "?") if title_list else "?"
            check("DB 접근", True, db_title)

            props = db.get("properties", {})
            print(f"  속성 목록 ({len(props)}개): {list(props.keys())}")
        except Exception as e:
            check("Weekly DB 접근", False, str(e))

    print("\n══════════════════════════════════════")
    print("  진단 완료")
    print("══════════════════════════════════════\n")


if __name__ == "__main__":
    main()
