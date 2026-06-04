# Project: RoCyg-Sanremo Data Pipeline (HITL & Flexible Parsing)

## 1. Project Overview
- **목적:** 디시인사이드 로드싸이클갤러리 '로싸-산레모' 대회 데이터 자동 수집 및 구글 스프레드시트 적재 파이프라인 구축.
- **운영 방식:** Human-in-the-loop (유연한 텍스트 파싱을 통한 1차 자동 적재 -> 관리자 수동 검수 -> 시트 내 수식 계산)
- **기술 스택:** Python, BeautifulSoup4, Requests, gspread (Google Sheets API), 정규표현식(re)
- **배포 환경:** Linux 기반 개인 서버, Supervisor 프로세스 관리

## 2. Google Sheets Target Schema
크롤러는 탓워 탭을 모니터링하여 아래 순서대로 정확히 데이터를 추가(Append)함.
- **B열 (제목):** 게시글 제목 (`=HYPERLINK("원글링크", "제목")`)
- **C열 (글쓴이):** 작성자 닉네임
- **D열 (식별자):** 작성자 고닉 ID (중복 방지 및 유저 식별용)
- **E열 (작성일):** 게시글 등록 일시 (`YYYY-MM-DD HH:MM:SS`)
- **F열 (시간):** 주행 시간 (`HH:MM:SS` 형태로 파이썬에서 정제하여 입력)
- **G열 (거리 km):** 주행 거리 (숫자만 추출, Float)
- **H열 (획고 m):** 획득 고도 (숫자만 추출, Integer)
- **I열 (점수):** 수식 자동 삽입
  - `=IF(J[Row]="완료", IF(F[Row]*1440 <= 480, (F[Row]*24) * ((G[Row]*10) + (H[Row]*0.2)), 8 * ((G[Row]*10) + (H[Row]*0.2))), 0)`
- **J열 (검증):** 초기값 공란 (관리자가 스트라바 교차 검수 후 "완료" 입력 시 점수 계산 활성화)
- **K열 (원글 링크):** 게시글 원본 URL
- **L열 (스트라바 링크):** 본문에서 파싱한 스트라바 활동 주소 URL
- **M열 (센서):** 본문 내 센서 데이터 키워드('심박', '파워', '케이던스' 등) 포함 여부 추출
- **N열 (눈물 나는 사연):** 규정 행을 제외한 본문 스토리 요약 또는 공란

## 3. Flexible Post Template & Parsing Rules
참가자는 게시글 **본문 첫 줄**에 대회명과 기록을 작성하며, 띄어쓰기, 쉼표, 한글 단위 혼용을 허용함.
- **유효한 입력 예시:**
  - `로싸산레모 7:53 340 3400`
  - `로싸 산레모, 7시간54분, 340km, 3400m`
  - `로싸산레모 07:54:30, 340.5, 3400`

### 크롤러 데이터 추출 파이프라인 (Data Extraction)
1. **첫 줄 인식 정규식 (유연한 패턴):** `^로싸\s*산레모[\s,]+(?P<time>\d{1,2}[:시간\s]+\d{1,2}[분\s]*(?:\d{1,2}초?)?)[\s,]+(?P<dist>\d+(?:\.\d+)?)[km\s,]*(?P<ele>\d+)[m\s]*`
2. **데이터 정제(Preprocessing) 요구사항:**
   - 추출된 `time` 그룹 값에서 한글 텍스트('시간', '분', '초') 및 공백을 치환하여 `HH:MM:SS` 규격으로 정제.
3. **스트라바 URL 정규식:** `https?:\/\/(?:www\.)?strava\.com\/activities\/\d+`

## 4. Execution Constraints
- **필터링 규칙:** 글 제목 필터링 폐지. 갤러리 '탓워' 탭의 글 본문을 HTTP GET으로 읽었을 때, 본문 최상단이 위의 `로싸\s*산레모` 정규식으로 시작하는 경우에만 유효 데이터로 취급.
- **안티 봇 방지:** 글 목록 수집과 본문 상세 조회(GET) 사이에 반드시 무작위 딜레이(2~5초)를 부여하고, User-Agent를 설정할 것.
- **중복 처리:** 데이터를 시트에 누적 적재하되, 동일 식별자(D열) 중 J열이 "완료"이면서 I열(점수)이 가장 높은 단일 행만 랭킹에 반영.

## 5. Deployment (Supervisor)
- `/etc/supervisor/conf.d/rocyg_crawler.conf` 파일 생성 후 아래 내용 적용하여 백그라운드 무중단 운영:
```ini
[program:rocyg_crawler]
command=python /절대경로/crawler.py
directory=/절대경로/
autostart=true
autorestart=true
stderr_logfile=/var/log/rocyg_crawler.err.log
stdout_logfile=/var/log/rocyg_crawler.out.log