"""
대회 종료 후 '최종순위표' 탭의 순위를 web/results.json으로 내보냄 (상장 페이지용).

탭 구조: 구역 행(종합 / 거리 / 획고)과 그 아래 헤더 행(순위, 고닉, 거리(KM), 획고(m), 총점)으로
세 순위표가 옆으로 나란히 있음. 각 구역의 순위·값을 그대로 쓰고, 고닉으로 한 사람의 기록을 합침.

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
SECTIONS   = {"종합": "total", "거리": "distance", "획고": "elevation"}

# 구역 안의 열 헤더 → 필드
COLUMN_ALIASES = {
    "rank":      ["순위"],
    "nickname":  ["고닉", "닉네임"],
    "distance":  ["거리"],
    "elevation": ["획고", "고도"],
    "score":     ["총점", "점수"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s", "", str(s)).lower()


def _num(raw: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(raw).replace(",", ""))
    return float(m.group()) if m else None


def _fail(rows: list[list[str]], reason: str):
    print(f"[오류] {reason}. 앞쪽 행 내용:", file=sys.stderr)
    for i, row in enumerate(rows[:5], start=1):
        print(f"  {i}행: {row}", file=sys.stderr)
    sys.exit(1)


def _find_layout(rows: list[list[str]]) -> tuple[int, dict[str, dict[str, int]]]:
    """구역 행을 찾아 구역별 {필드: 열 인덱스}와 데이터 시작 행을 반환."""
    for idx, row in enumerate(rows[:10]):
        starts = {SECTIONS[_norm(c)]: i for i, c in enumerate(row) if _norm(c) in SECTIONS}
        if "total" in starts and idx + 1 < len(rows):
            break
    else:
        _fail(rows, "종합/거리/획고 구역 행을 찾지 못했습니다")

    header = rows[idx + 1]
    bounds = sorted(i for i, c in enumerate(row) if _norm(c))   # 상품 등 다른 구역도 경계로 사용
    layout: dict[str, dict[str, int]] = {}
    for section, start in starts.items():
        end = next((b for b in bounds if b > start), len(header))
        cols = {}
        for i in range(start, end):
            cell = _norm(header[i]) if i < len(header) else ""
            for field, aliases in COLUMN_ALIASES.items():
                if field not in cols and any(a in cell for a in aliases):
                    cols[field] = i
                    break
        if "nickname" not in cols:
            _fail(rows, f"'{section}' 구역에서 고닉 열을 찾지 못했습니다")
        layout[section] = cols

    print(f"[헤더] 구역 {idx + 1}행, 열 {idx + 2}행 사용: " + " | ".join(
        f"{s}(" + ", ".join(f"{f}={header[i]}" for f, i in c.items()) + ")"
        for s, c in layout.items()))
    return idx + 2, layout


def build_results(rows: list[list[str]]) -> tuple[list[dict], dict[str, int]]:
    data_start, layout = _find_layout(rows)
    people: dict[str, dict] = {}
    totals = {s: 0 for s in layout}

    for section, cols in layout.items():
        get = lambda r, f: r[cols[f]].strip() if f in cols and cols[f] < len(r) else ""
        for pos, r in enumerate(rows[data_start:], start=1):
            nickname = get(r, "nickname")
            if not nickname:
                continue
            totals[section] += 1
            rank = _num(get(r, "rank"))
            p = people.setdefault(nickname, {"nickname": nickname})
            if f"rank_{section}" in p:      # 같은 고닉이 한 구역에 두 번 나오면 상위 기록만
                continue
            p[f"rank_{section}"] = int(rank) if rank else pos
            for field in ("distance", "elevation", "score"):
                value = _num(get(r, field))
                # 거리·획고 값은 해당 구역 순위표의 값을 우선 (종합 구역 값과 다를 수 있음)
                if value is not None and (field == section or field not in p):
                    p[field] = value

    results = []
    for p in people.values():
        results.append({
            "nickname":       p["nickname"],
            "rank_total":     p.get("rank_total"),
            "rank_distance":  p.get("rank_distance"),
            "rank_elevation": p.get("rank_elevation"),
            "score":          round(p["score"], 2) if "score" in p else None,
            "distance":       round(p["distance"], 2) if "distance" in p else None,
            "elevation":      int(p["elevation"]) if "elevation" in p else None,
        })
    results.sort(key=lambda e: (e["rank_total"] or 10**6, e["nickname"]))
    return results, totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(), help="상장 수여일 (YYYY-MM-DD)")
    parser.add_argument("--tab", default=RESULT_TAB, help="결과를 읽을 시트 탭 이름")
    parser.add_argument("--out", default=os.path.join("web", "results.json"))
    args = parser.parse_args()

    sheets = SheetsManager(SPREADSHEET_ID, args.tab)
    results, totals = build_results(sheets.ws.get_all_values())

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {"date": args.date, "totals": totals, "results": results},
            f, ensure_ascii=False, indent=1,
        )
    print(f"[내보내기] '{args.tab}' 탭 {len(results)}명 (종합 {totals.get('total', 0)} / "
          f"거리 {totals.get('distance', 0)} / 획고 {totals.get('elevation', 0)}) → {args.out}")


if __name__ == "__main__":
    main()
