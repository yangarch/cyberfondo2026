"""
대회 종료 후 '최종순위표' 탭의 기록을 web/results.json으로 내보냄 (상장 페이지용).

- 열 위치가 아니라 헤더 이름으로 열을 찾음 (HEADER_ALIASES)
- 검증 열이 있으면 "완료"인 행만 대상
- 식별자 열이 있으면 동일 식별자 중 점수가 가장 높은 단일 행만 반영
- 종합순위 열이 있으면 그 값을 그대로 쓰고, 없으면 점수로 계산
- 거리 / 획득고도 순위는 각각 계산 (동점은 같은 순위)

사용: python export_results.py [--date 2026-09-28] [--tab 최종순위표] [--out web/results.json]
"""

import argparse
import json
import os
import re
import sys
from datetime import date

from config import SPREADSHEET_ID
from sheets_manager import SheetsManager

RESULT_TAB = "최종순위표"

# 필드 → 헤더 후보 (공백 제거 후 완전 일치 우선, 없으면 포함 여부로 매칭)
HEADER_ALIASES = {
    "nickname":   ["닉네임", "글쓴이", "이름", "성명", "참가자"],
    "uid":        ["식별자", "아이디", "id", "uid"],
    "time":       ["시간", "주행시간"],
    "distance":   ["거리", "거리km", "주행거리"],
    "elevation":  ["획고", "획고m", "획득고도", "고도"],
    "score":      ["점수", "총점"],
    "rank_total": ["순위", "종합순위", "등수"],
    "verified":   ["검증", "검수"],
}
REQUIRED = ["nickname", "distance", "elevation"]


def _norm(s: str) -> str:
    return re.sub(r"[\s()\[\]]", "", str(s)).lower()


def _num(raw: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", str(raw).replace(",", ""))
    return float(m.group()) if m else 0.0


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """앞쪽 10행 중 필수 헤더가 모두 있는 첫 행을 헤더로 보고 필드별 열 인덱스를 반환."""
    for idx, row in enumerate(rows[:10]):
        cells = [_norm(c) for c in row]
        cols: dict[str, int] = {}
        for field, aliases in HEADER_ALIASES.items():
            alias_set = [_norm(a) for a in aliases]
            exact = [i for i, c in enumerate(cells) if c in alias_set]
            partial = [
                i for i, c in enumerate(cells)
                if c and any(a in c for a in alias_set)
                # "거리순위"가 거리 열로, "거리순위"/"획고순위"가 종합순위 열로 잡히지 않게
                and (("순위" in c) == (field == "rank_total"))
                and not (field == "rank_total" and re.search(r"거리|고도|획고", c))
            ]
            hit = (exact or partial or [None])[0]
            if hit is not None and hit not in cols.values():
                cols[field] = hit
        if all(f in cols for f in REQUIRED):
            return idx, cols

    print("[오류] 헤더 행을 찾지 못했습니다. 앞쪽 행 내용:", file=sys.stderr)
    for i, row in enumerate(rows[:5], start=1):
        print(f"  {i}행: {row}", file=sys.stderr)
    print("export_results.py의 HEADER_ALIASES에 실제 헤더 이름을 추가하세요.", file=sys.stderr)
    sys.exit(1)


def _rank(entries: list[dict], key: str, rank_key: str):
    """내림차순 경쟁 순위(1, 2, 2, 4 ...)."""
    ordered = sorted(entries, key=lambda e: e[key], reverse=True)
    prev, prev_rank = None, 0
    for i, e in enumerate(ordered, start=1):
        if e[key] != prev:
            prev, prev_rank = e[key], i
        e[rank_key] = prev_rank


def build_results(rows: list[list[str]]) -> list[dict]:
    header_idx, cols = _find_header(rows)
    print(f"[헤더] {header_idx + 1}행 사용: " + ", ".join(
        f"{f}={rows[header_idx][i]}" for f, i in cols.items()))

    get = lambda r, f: r[cols[f]].strip() if f in cols and cols[f] < len(r) else ""

    best: dict[str, dict] = {}
    for n, r in enumerate(rows[header_idx + 1:]):
        nickname = get(r, "nickname")
        if not nickname:
            continue
        if "verified" in cols and get(r, "verified") != "완료":
            continue
        distance, elevation = _num(get(r, "distance")), _num(get(r, "elevation"))
        if distance <= 0 and elevation <= 0:
            continue
        entry = {
            "nickname":  nickname,
            "uid":       get(r, "uid"),
            "time":      get(r, "time"),
            "distance":  round(distance, 2),
            "elevation": int(elevation),
            # 점수 열이 없으면 시트 수식과 동일하게 계산: 거리 1km당 5점 + 획고 1m당 0.2점
            "score":     round(_num(get(r, "score")) if "score" in cols
                               else distance * 5 + elevation * 0.2, 1),
        }
        if "rank_total" in cols:
            entry["rank_total"] = int(_num(get(r, "rank_total"))) or None

        key = entry["uid"] or f"row{n}"
        if key not in best or entry["score"] > best[key]["score"]:
            best[key] = entry

    entries = list(best.values())
    if "rank_total" not in cols or any(e.get("rank_total") is None for e in entries):
        _rank(entries, "score", "rank_total")
    _rank(entries, "distance", "rank_distance")
    _rank(entries, "elevation", "rank_elevation")
    return sorted(entries, key=lambda e: e["rank_total"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(), help="상장 수여일 (YYYY-MM-DD)")
    parser.add_argument("--tab", default=RESULT_TAB, help="결과를 읽을 시트 탭 이름")
    parser.add_argument("--out", default=os.path.join("web", "results.json"))
    args = parser.parse_args()

    sheets  = SheetsManager(SPREADSHEET_ID, args.tab)
    results = build_results(sheets.ws.get_all_values())

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {"date": args.date, "total": len(results), "results": results},
            f, ensure_ascii=False, indent=1,
        )
    print(f"[내보내기] '{args.tab}' 탭 {len(results)}명 → {args.out}")


if __name__ == "__main__":
    main()
