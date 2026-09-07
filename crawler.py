"""
디시인사이드 갤러리 크롤러.
본문 첫 줄이 '사이버폰도' 유연 패턴으로 시작하는 글만 유효 데이터로 취급.
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime

import google.generativeai as genai

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
# 시간 형식: H:MM / H:MM:SS / 9h07m58s / 7시간54분 / 7시간54분30초
# 구분자: 공백, 쉼표, 슬래시 허용
# 사이버/싸이버, 폰도/그란폰도 조합 모두 허용
# (사이버폰도, 싸이버폰도, 사이버 그란폰도, 싸이버그란폰도 등)
# 사이버-폰도(하이픈), [사이버폰도](대괄호) 표기 허용
# 첫 번째 시간 뒤 두 번째 시간(이동시간 등) 건너뜀: /45:30:38, (이동: 6:30), 이동6:30
# 거리·고도 값의 천단위 콤마 표기(1,011 등) 허용 (매칭 후 콤마 제거해서 사용)
# 시간/거리/고도 값마다 개별 대괄호로 감싸는 표기([ 7:00:13 ] [152.79] [2,077],
# [03:02:44][98.71][200]처럼 대괄호끼리 구분자 없이 바로 붙는 경우도) 허용
FIRST_LINE_REGEX = re.compile(
    r'^\[?\s*(?:사이버|싸이버)\s*[-]?\s*(?:그란\s*[-]?\s*)?폰도\s*\]?[\s,]+'
    r'\[?\s*(?P<time>'
    r'\d+:\d{2}(?::\d{2})?'                         # H:MM 또는 H:MM:SS (자릿수 제한 없음)
    r'|\d+h\s*\d{1,2}m(?:\s*\d{1,2}s)?'             # 9h07m58s (시간 자릿수 제한 없음)
    r'|\d{1,2}시간\s*\d{1,2}분(?:\s*\d{1,2}초?)?'  # 7시간54분(30초)
    r')\s*\]?'
    r'(?:[\s,/]*\(?\s*(?:이동[:\s]*)?\d+:\d{2}(?::\d{2})?\s*\)?)?'  # 두 번째 시간값 건너뜀
    r'(?:[\s,/]+|(?=\[))'                           # 구분자 또는 바로 이어지는 대괄호
    r'\[?\s*(?P<dist>\d+(?:,\d{3})*(?:\.\d+)?)\s*k?m?\s*\]?'
    r'(?:[\s,/]+|(?=\[))'
    r'\[?\s*(?P<ele>\d+(?:,\d{3})*)\s*m?\s*\]?',
    re.IGNORECASE
)

STRAVA_REGEX = re.compile(
    r'https?://\S*strava\S+'
)

SENSOR_KEYWORDS = ['심박', '파워', '케이던스', '속도', 'power', 'heart rate', 'cadence', 'bpm', 'rpm', 'w/kg', 'watt']

# 대회명/시간/거리/고도가 한 줄에 다 몰려 있는 경우부터, 값마다 줄바꿈된 경우까지
# 흡수하기 위해 앞쪽 몇 줄을 첫 줄 정규식 매칭 후보로 봄
HEADER_WINDOW_LINES = 6

_gemini_model = None

def _init_gemini(api_key: str):
    global _gemini_model
    if api_key and _gemini_model is None:
        genai.configure(api_key=api_key)
        _gemini_model = genai.GenerativeModel("gemini-3.5-flash-lite")

def _summarize(text: str) -> str:
    """Gemini로 사연 요약. API 키 없거나 내용 없으면 원문 200자 반환."""
    if not text.strip():
        return ""
    if _gemini_model is None:
        return text[:197] + "..." if len(text) > 200 else text
    try:
        prompt = (
            "다음은 디시인사이드 로드싸이클 갤러리 유저가 대회 후기로 쓴 글이야. "
            "디씨 특유의 거칠고 솔직한 말투와 감성을 살려서 핵심 사연만 50자 이내 1문장으로 요약해. "
            "요약문만 출력하고 다른 말은 하지 마.\n\n"
            f"{text}"
        )
        resp = _gemini_model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        print(f"  [Gemini] 요약 실패: {e}")
        return text[:197] + "..." if len(text) > 200 else text


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

    # 영문/한글 단위 치환 후 파싱
    t = re.sub(r'시간|h', ':', t, flags=re.IGNORECASE)
    t = re.sub(r'분|m', ':', t, flags=re.IGNORECASE)
    t = re.sub(r'초|s', '', t, flags=re.IGNORECASE)
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
                 min_delay: float, max_delay: float, gemini_api_key: str = ""):
        self.gallery_type    = gallery_type
        self.gallery_id      = gallery_id
        self.gallery_subject = gallery_subject
        self.min_delay       = min_delay
        self.max_delay       = max_delay
        self.session         = requests.Session()
        _init_gemini(gemini_api_key)

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

    def build_post_url(self, post_no: str) -> str:
        """게시글 번호로 상세 페이지 URL 구성 (단건 처리용)."""
        return f"{self._base()}/view/?id={self.gallery_id}&no={post_no}"

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
        # 디시 에디터가 값마다 줄바꿈을 삽입할 수 있으므로(대회명/시간/거리/고도가
        # 각각 다른 줄일 수 있음) 앞쪽 여러 줄을 공백으로 이어붙여 매칭
        non_empty = [l.strip() for l in body_text.splitlines() if l.strip()]
        header_window = non_empty[:HEADER_WINDOW_LINES]
        first_line = ' '.join(header_window)
        print(f"  [첫줄] {repr(first_line)}")
        m = FIRST_LINE_REGEX.match(first_line)
        if not m:
            print(f"  [스킵] 패턴 불일치")
            return None  # 대회 참가 글 아님

        ride_time = _normalize_time(m.group('time'))
        distance  = m.group('dist').replace(',', '')
        elevation = m.group('ele').replace(',', '')

        # 제목 (재검사 등 목록 페이지 없이 상세만으로 처리할 때 사용)
        title_el = soup.select_one('.title_subject')
        title    = title_el.get_text(strip=True) if title_el else ""
        title    = re.sub(r'\s*\[\d+\]$', '', title).strip()

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

        # 사연: 헤더·스트라바 URL 제외 후 Gemini 요약
        # 정규식이 실제로 소비한 만큼만 헤더로 취급 (값마다 줄이 나뉜 경우 대응)
        header_lines = self._count_header_lines(header_window, m.end())
        raw_story = self._extract_story(non_empty, header_lines)
        story = _summarize(raw_story)

        return {
            "title":      title,
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

    def _count_header_lines(self, header_window: list[str], matched_len: int) -> int:
        """
        FIRST_LINE_REGEX가 header_window를 ' '로 이어붙인 문자열에서 실제로
        소비한 글자 수(matched_len)를 바탕으로, 원본 몇 번째 줄까지가
        헤더(대회명/시간/거리/고도)인지 계산.
        정규식 끝의 선택적 공백(\\s*)이 다음 줄로 잘못 넘어가 계산되지 않도록,
        join 구분자로 생긴 트레일링 공백은 제외하고 비교한다.
        """
        content_len = len(' '.join(header_window)[:matched_len].rstrip())
        pos = 0
        for i, line in enumerate(header_window):
            line_end = pos + len(line)
            if content_len <= line_end:
                return i + 1
            pos = line_end + 1  # ' '.join 사이 공백 1글자
        return len(header_window)

    def _extract_story(self, non_empty: list[str], header_lines: int) -> str:
        # URL 자체뿐 아니라, 링크를 붙였을 때 에디터가 자동 생성하는
        # 미리보기 카드(제목·설명·도메인)도 실제 사연이 아니므로 함께 제외.
        # 값마다 대괄호로 감싼 글에서 헤더 뒤에 남는 짝 잃은 괄호 잔여 줄(예: ']')도 제외.
        story_lines = [
            line for line in non_empty[header_lines:]
            if not STRAVA_REGEX.search(line)
            and 'strava' not in line.lower()
            and line.strip('[]() ')
        ]
        story = ' '.join(story_lines)
        return story[:197] + "..." if len(story) > 200 else story
