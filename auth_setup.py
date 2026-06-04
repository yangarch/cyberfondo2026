"""
최초 1회만 실행하는 OAuth2 인증 셋업 스크립트.
브라우저 없는 Linux 서버에서 콘솔 방식으로 token.json 을 생성함.

사용법:
    python auth_setup.py

실행 시 URL 이 출력되면 → 아무 기기 브라우저에서 열기 → 구글 계정 승인
→ 표시되는 코드를 터미널에 붙여넣기 → token.json 생성 완료
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_FILE    = "credentials.json"
AUTHORIZED_USER_FILE = "token.json"


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)

    # run_console(): 브라우저 없이 URL + 코드 붙여넣기 방식으로 인증
    creds = flow.run_console()

    # token.json 저장
    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes) if creds.scopes else SCOPES,
    }
    with open(AUTHORIZED_USER_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n인증 완료. {AUTHORIZED_USER_FILE} 저장됨.")
    print("이제 main.py 를 실행하면 됩니다.")


if __name__ == "__main__":
    main()
