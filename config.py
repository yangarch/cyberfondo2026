import os
from dotenv import load_dotenv

load_dotenv()

GALLERY_TYPE    = os.getenv("GALLERY_TYPE", "board")
GALLERY_ID      = os.getenv("GALLERY_ID", "roadcycle")
GALLERY_SUBJECT = os.getenv("GALLERY_SUBJECT", "")      # 탭(말머리) 필터, 빈 문자열이면 전체

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1cfKsH8EtWv3fDka4lfdF5t9WHlZvS7oY19ZdYcifYDY")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "시트1")

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

SEEN_POSTS_FILE = "seen_posts.json"
MIN_DELAY       = float(os.getenv("MIN_DELAY", "2"))
MAX_DELAY       = float(os.getenv("MAX_DELAY", "5"))
MAX_PAGES       = int(os.getenv("MAX_PAGES", "10"))
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "600"))
