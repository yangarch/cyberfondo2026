"""
Google Sheets 적재 모듈.
B~N열 순서로 데이터를 Append하며, I열에 점수 수식을 자동 삽입함.
"""

import json
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

TOKEN_FILE = "token.json"   # auth_setup.py 실행으로 생성

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_credentials() -> Credentials:
    """token.json을 로드하고 만료 시 자동 갱신."""
    with open(TOKEN_FILE) as f:
        data = json.load(f)

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes", SCOPES),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # 갱신된 토큰 저장
        data["token"] = creds.token
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)

    return creds


class SheetsManager:
    def __init__(self, spreadsheet_id: str, worksheet_name: str):
        creds  = _load_credentials()
        client = gspread.authorize(creds)
        self.ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)

    # ---- 조회 ----------------------------------------------------------------

    def get_existing_urls(self) -> set[str]:
        """K열(원글 링크)에 이미 적재된 URL 집합을 반환."""
        try:
            values = self.ws.col_values(11)   # K = 11번째 열
            return set(v for v in values[1:] if v)   # 헤더 제외
        except gspread.exceptions.GSpreadException:
            return set()

    # ---- 적재 ----------------------------------------------------------------

    def append_post(self, title: str, post_url: str, data: dict):
        """
        다음 빈 행에 게시글 데이터를 적재.
        I열에 점수 수식 자동 삽입, B열에 HYPERLINK 수식 삽입.
        """
        # K열(원글 링크)은 크롤러만 채우므로 드롭다운 사전 설정에 영향받지 않음
        k_values = self.ws.col_values(11)  # K = 11번째 열
        next_row = max(len(k_values) + 1, 2)

        # 시트 행 한도 초과 시 자동 확장
        if next_row > self.ws.row_count:
            self.ws.add_rows(500)
            print(f"  [시트] 행 500개 자동 추가 (현재 {self.ws.row_count}행)")

        # 거리: 200m당 1점 (1km=5점), 획고: 10m당 2점 (1m=0.2점)
        # 8시간 초과 시 (8시간/실제시간) 비례 차감
        score_formula = (
            f'=IF(J{next_row}="완료",'
            f'IF(F{next_row}*1440<=480,'
            f'(G{next_row}*5)+(H{next_row}*0.2),'
            f'((G{next_row}*5)+(H{next_row}*0.2))*(480/(F{next_row}*1440))),0)'
        )

        safe_title    = title.replace('"', "'")
        title_formula = f'=HYPERLINK("{post_url}","{safe_title}")'

        # A열은 공란, B~N열에 데이터
        row = [
            "",                          # A
            title_formula,               # B 제목
            data["nickname"],            # C 글쓴이
            data["uid"],                 # D 식별자
            data["post_date"],           # E 작성일
            data["ride_time"],           # F 시간
            data["distance"],            # G 거리 km
            data["elevation"],           # H 획고 m
            score_formula,               # I 점수
            "미완료",                     # J 검증
            post_url,                    # K 원글 링크
            data["strava_url"],          # L 스트라바 링크
            data["sensor"],              # M 센서
            data["story"],               # N 눈물 나는 사연
        ]

        self.ws.update(
            f"A{next_row}:N{next_row}",
            [row],
            value_input_option="USER_ENTERED",
        )
        print(f"  [시트] 행 {next_row} 적재 완료: {title[:40]}")
