"""
RoCyg-Sanremo 데이터 파이프라인 메인 루프.
Supervisor에 의해 관리되며, 갤러리를 주기적으로 스캔하여 신규 참가 기록을 시트에 적재함.
"""

import argparse
import json
import os
import sys
import time

from config import (
    GALLERY_TYPE, GALLERY_ID, GALLERY_SUBJECT,
    SPREADSHEET_ID, WORKSHEET_NAME,
    GEMINI_API_KEY,
    SEEN_POSTS_FILE, MIN_DELAY, MAX_DELAY, MAX_PAGES, POLL_INTERVAL,
)
from crawler import DCICrawler
from sheets_manager import SheetsManager


def load_seen() -> set[str]:
    if os.path.exists(SEEN_POSTS_FILE):
        with open(SEEN_POSTS_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return set(json.loads(content))
    return set()


def save_seen(seen: set[str]):
    with open(SEEN_POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def run_once(crawler: DCICrawler, sheets: SheetsManager, seen: set[str], max_pages: int = MAX_PAGES) -> int:
    """한 사이클 실행. 새로 적재된 게시글 수를 반환."""
    existing_urls = sheets.get_existing_urls()
    all_seen      = seen | existing_urls
    new_count     = 0

    for page in range(1, max_pages + 1):
        print(f"\n[페이지 {page}/{MAX_PAGES}] 목록 수집 중...")
        posts = crawler.get_post_list(page=page)

        if not posts:
            print("  더 이상 게시글 없음, 중단.")
            break

        for post in posts:
            url = post["url"]

            if url in all_seen:
                continue

            print(f"\n  [검사] {post['title'][:50]}")
            crawler.random_delay()

            detail = crawler.get_post_detail(post["no"])

            # 유효하지 않은 글 (본문 패턴 불일치)
            if detail is None:
                all_seen.add(url)
                seen.add(url)
                continue

            try:
                sheets.append_post(post["title"], url, detail)
                all_seen.add(url)
                seen.add(url)
                new_count += 1
            except Exception as e:
                print(f"  [오류] 시트 적재 실패: {e}")

        # 다음 페이지 요청 전 딜레이
        if page < MAX_PAGES and posts:
            crawler.random_delay()

    return new_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=MAX_PAGES,
                        help="이번 실행에만 적용할 최대 페이지 수 (기본: MAX_PAGES)")
    parser.add_argument("--once", action="store_true",
                        help="한 사이클만 실행 후 종료 (딥스캔용)")
    args = parser.parse_args()

    print("=" * 50)
    print("  RoCyg-Sanremo 데이터 파이프라인 시작")
    if args.once:
        print(f"  [딥스캔 모드] 최대 {args.pages}페이지, 1회 후 종료")
    print("=" * 50)

    crawler = DCICrawler(
        gallery_type=GALLERY_TYPE,
        gallery_id=GALLERY_ID,
        gallery_subject=GALLERY_SUBJECT,
        min_delay=MIN_DELAY,
        max_delay=MAX_DELAY,
        gemini_api_key=GEMINI_API_KEY,
    )
    sheets = SheetsManager(
        spreadsheet_id=SPREADSHEET_ID,
        worksheet_name=WORKSHEET_NAME,
    )
    seen = load_seen()

    while True:
        print(f"\n{'─' * 40}")
        print(f"[스캔 시작] 누적 확인 URL: {len(seen)}개")

        try:
            count = run_once(crawler, sheets, seen, max_pages=args.pages)
            save_seen(seen)
            print(f"\n[스캔 완료] 신규 적재: {count}건")
        except Exception as e:
            print(f"[치명 오류] 사이클 실패: {e}")

        if args.once:
            print("[딥스캔 완료] 종료.")
            break

        print(f"[대기] 다음 스캔까지 {POLL_INTERVAL}초 ({POLL_INTERVAL // 60}분)...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
