"""
디시인사이드 갤러리 크롤러.
본문 첫 줄이 '로싸산레모' 유연 패턴으로 시작하는 글만 유효 데이터로 취급.
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# 본문 첫 줄 유효성 검사 + 데이터 추출
# 시간 형식: H:MM / H:MM:SS / 7시간54분 / 7시간54분30초
FIRST_LINE_REGEX = re.compile(
    r'^로싸\s*산레모[\s,]+'
    r'(?P<time>'
    r'\d{1,2}:\d{2}(?::\d{2})?'                    # H:MM 또는 H:MM:SS
    r'|\d{1,2}시간\s*\d{1,2}분(?:\s*\d{1,2}초?)?'  # 한글: 7시간54분(30초)
    r')'
    r'[\s,]+'
    r'(?P<dist>\d+(?:\.\d+)?)[km\s,]*'
    r'(?P<ele>\d+)[m\s]*',
    re.IGNORECASE
)

STRAVA_REGEX = re.compile(
    r'https?://(?:www\.)?strava\.com/activities/\d+'
)

SENSOR_KEYWORDS = ['심박', '파워', '케이던스', '속도', 'power', 'heart rate', 'cadence', 'bpm', 'rpm', 'w/kg', 'watt']


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _normalize_time(raw: str) -> str:
    """
    다양한 형식의 시간 문자열을 HH:MM:SS 로 정규화.
    지원: '7:53', '07:54:30', '7시간54분', '7시간 54분 30초'
    """
    t = raw.strip()

    # 순수 H:MM 또는 H:MM:SS
    m = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', t)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return f"{h:02d}:{mi:02d}:{s:02d}"

    # 한글 단위 치환 후 파싱
    t = re.sub(r'시간', ':', t)
    t = re.sub(r'분', ':', t)
    t = re.sub(r'초', '', t)
    t = re.sub(r'\s+', '', t).strip(':')

    parts = [p for p in t.split(':') if p.isdigit()]
    if len(parts) == 2:
        h, mi = int(parts[0]), int(parts[1])
        return f"{h:02d}:{mi:02d}:00"
    if len(parts) == 3:
        h, mi, s = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{h:02d}:{mi:02d}:{s:02d}"

    return raw  # fallback: 그대로 반환


def _format_date(raw: str) -> str:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return raw.strip()


# ---------------------------------------------------------------------------
# 크롤러 클래스
# ---------------------------------------------------------------------------

class DCICrawler:
    def __init__(self, gallery_type: str, gallery_id: str, gallery_subject: str,
                 min_delay: float, max_delay: float):
        self.gallery_type    = gallery_type
        self.gallery_id      = gallery_id
        self.gallery_subject = gallery_subject
        self.min_delay       = min_delay
        self.max_delay       = max_delay
        self.session         = requests.Session()

    # ---- 내부 유틸 --------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "User-Agent":              random.choice(USER_AGENTS),
            "Referer":                 "https://www.dcinside.com/",
            "Accept":                  "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":         "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Accept-Encoding":         "gzip, deflate, br",
            "Connection":              "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _base(self) -> str:
        if self.gallery_type == "mgallery":
            return "https://gall.dcinside.com/mgallery/board"
        return "https://gall.dcinside.com/board"

    def random_delay(self):
        delay = random.uniform(self.min_delay, self.max_delay)
        print(f"  [딜레이] {delay:.1f}s")
        time.sleep(delay)

    # ---- 목록 페이지 ------------------------------------------------------

    def get_post_list(self, page: int = 1) -> list[dict]:
        """갤러리 목록 페이지에서 게시글 기본 정보 수집."""
        params = {"id": self.gallery_id, "page": page}
        if self.gallery_subject:
            params["subject_key"] = self.gallery_subject

        try:
            resp = self.session.get(
                f"{self._base()}/lists/",
                params=params,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_list(resp.text)
        except requests.RequestException as e:
            print(f"[오류] 목록 요청 실패 (page={page}): {e}")
            return []

    def _parse_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, 'lxml')
        posts = []

        for row in soup.select('tr.ub-content'):
            # 공지글 스킵 (notice 클래스, 비숫자 글번호, 말머리 "공지")
            if 'notice' in row.get('class', []):
                continue
            num_cell = row.select_one('td.gall_num')
            if num_cell and not num_cell.get_text(strip=True).isdigit():
                continue
            subject_cell = row.select_one('td.gall_subject')
            if subject_cell and '공지' in subject_cell.get_text(strip=True):
                continue

            title_cell = row.select_one('td.gall_tit a')
            if not title_cell:
                continue

            title = re.sub(r'\s*\[\d+\]$', '', title_cell.get_text(strip=True)).strip()
            href  = title_cell.get('href', '')

            no_match = re.search(r'no=(\d+)', href)
            if not no_match:
                continue

            post_no  = no_match.group(1)
            post_url = f"https://gall.dcinside.com{href}" if href.startswith('/') else href

            posts.append({"no": post_no, "title": title, "url": post_url})

        return posts

    # ---- 게시글 상세 -------------------------------------------------------

    def get_post_detail(self, post_no: str) -> dict | None:
        """게시글 상세 페이지를 파싱하여 대회 데이터를 반환. 유효하지 않으면 None."""
        try:
            resp = self.session.get(
                f"{self._base()}/view/",
                params={"id": self.gallery_id, "no": post_no},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_detail(resp.text)
        except requests.RequestException as e:
            print(f"[오류] 상세 요청 실패 (no={post_no}): {e}")
            return None

    def _parse_detail(self, html: str) -> dict | None:
        soup = BeautifulSoup(html, 'lxml')

        # 본문 텍스트
        body_el   = soup.select_one('.write_div, .s_write')
        body_text = body_el.get_text(separator='\n', strip=True) if body_el else ""

        # 첫 줄 유효성 검사 + 데이터 추출
        first_line = next((l.strip() for l in body_text.splitlines() if l.strip()), "")
        m = FIRST_LINE_REGEX.match(first_line)
        if not m:
            return None  # 대회 참가 글 아님

        ride_time = _normalize_time(m.group('time'))
        distance  = m.group('dist')
        elevation = m.group('ele')

        # 닉네임
        nickname_el = soup.select_one('.nickname em')
        nickname    = nickname_el.get_text(strip=True) if nickname_el else ""

        # 고닉 ID (data-uid 우선, 없으면 IP 표시)
        uid = ""
        uid_el = soup.select_one('[data-uid]')
        if uid_el:
            uid = uid_el.get('data-uid', '').strip()
        if not uid:
            ip_el = soup.select_one('.ip, .user-info')
            if ip_el:
                uid = ip_el.get_text(strip=True).strip('()')

        # 작성일
        date_el  = soup.select_one('.gall_date, .date_time')
        raw_date = (date_el.get('title', '') or date_el.get_text(strip=True)) if date_el else ""
        post_date = _format_date(raw_date)

        # 스트라바 URL
        strava_match = STRAVA_REGEX.search(body_text)
        strava_url   = strava_match.group(0) if strava_match else ""

        # 센서 데이터 포함 여부
        body_lower = body_text.lower()
        sensor = "O" if any(kw in body_lower for kw in SENSOR_KEYWORDS) else ""

        # 사연 (첫 줄 · 스트라바 URL 제외 나머지)
        story = self._extract_story(body_text, first_line)

        return {
            "nickname":   nickname,
            "uid":        uid,
            "post_date":  post_date,
            "ride_time":  ride_time,
            "distance":   distance,
            "elevation":  elevation,
            "strava_url": strava_url,
            "sensor":     sensor,
            "story":      story,
        }

    def _extract_story(self, body_text: str, first_line: str) -> str:
        lines = [l.strip() for l in body_text.splitlines() if l.strip()]
        story_lines = []
        skip = True

        for line in lines:
            if skip:
                if line == first_line:
                    skip = False
                continue
            if STRAVA_REGEX.search(line):
                continue
            story_lines.append(line)

        story = ' '.join(story_lines)
        return story[:197] + "..." if len(story) > 200 else story
