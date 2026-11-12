# VerseDesk (가칭) — 윈도우 바탕화면 '오늘의 말씀' + 폴더 구역

나는 프로그래밍 경험이 없어. 설명은 한국어로 쉽게, 내가 직접 할 일은 단계별로 알려줘.
이 문서 내용을 리포 루트 CLAUDE.md에 저장해서 다음 세션에서도 기준으로 삼아줘.

## 이번 목표
1. 오늘의 성경말씀(영어)이 바탕화면에 배경처럼 떠 있고 날마다 바뀜
2. 바탕화면에 '구역' 상자를 만들어 폴더·파일을 모아두고, 구역별로 접기/펼치기

## 공통 조건
- Windows 10/11 64비트. 설치 없이 exe 하나로 실행, 관리자 권한 불필요, 실행 시 콘솔창 안 뜸
- 기술 스택: Python + PySide6 → PyInstaller 단일 exe
- 인터넷 없이 동작해야 함(사내망 PC에서도 사용). 말씀 데이터는 exe에 내장
- 설정·상태(위치, 구역, 접힘 상태, 글자 크기 등)는 %APPDATA%\VerseDesk\settings.json에 저장, 재실행 시 그대로 복원
- 중복 실행 방지. 메인 창 없이 트레이 아이콘 메뉴로 조작:
  [배치 편집 켜기/끄기] [새 구역 추가] [Windows 시작 시 자동 실행 켜기/끄기(HKCU Run, 기본 켬)] [종료]
- 모든 위젯 창은 바탕화면 레이어에 고정 (Rainmeter의 'On Desktop'처럼)
  · 다른 창 위로 올라오지 않음, 작업표시줄·Alt+Tab에 안 보임
  · Win+D(바탕 화면 보기)를 눌러도 사라지지 않음
  · explorer.exe가 재시작돼도 자동으로 다시 붙음
- 다중 모니터·화면 배율(100/125/150%) 대응. 저장된 위치가 화면 밖이면 주 모니터 안으로 옮김
- 오류는 %APPDATA%\VerseDesk\log.txt에 기록하고 프로그램은 꺼지지 않게. 상주 프로그램이니 가볍게

## 기능 1: 오늘의 말씀
- 영어 본문만 표시 + 출처(예: John 3:16 (BSB)). 기본 글꼴 Georgia, 어떤 배경화면에서도 읽히게(흰 글씨+그림자 등), 긴 구절은 줄바꿈
- 날짜별 고정: 1/1~12/31(2/29 포함) 366구절, 매년 같은 날짜엔 같은 구절
- 프로그램 시작 시, 그리고 날짜가 바뀌면(자정, 절전 복귀 포함) 자동 교체
- 평소엔 클릭이 통과돼서 뒤쪽 바탕화면 아이콘 사용을 방해하지 않음. '배치 편집'을 켰을 때만 드래그로 이동, 위치 저장
- 기본 위치는 주 모니터 오른쪽 위, 글자 크기는 settings.json 값으로 조절
- 데이터 verses.json (날짜, 출처, 본문)
  · 번역본은 퍼블릭 도메인인 Berean Standard Bible(BSB). 본문은 공식 배포 원문 파일에서 그대로 가져오고 출처를 README에 기록
  · 본문을 기억에 의존해 작성하지 말 것(오탈자 방지). 원문 데이터를 못 구하면 진행을 멈추고 알려줄 것
  · 구절은 묵상하기 좋은 잘 알려진 구절 위주, 1~3절 분량
  · %APPDATA%\VerseDesk\verses.json이 있으면 그 파일에 있는 날짜는 그 본문을 우선 사용하고, 없는 날짜는 내장본 사용 (내가 일부 구절만 바꿔 넣을 수 있게)

## 기능 2: 폴더 구역
- [새 구역 추가] → 이름 입력 → 반투명 상자 생성. 여러 개 가능
- 상자 구성: 제목줄(이름, 항목 수, 접기/펼치기 버튼) + 항목 아이콘 목록(윈도우 기본 아이콘 + 이름)
- 탐색기나 바탕화면에서 폴더/파일을 끌어다 놓으면 등록
  · 원본은 절대 이동·복사·삭제하지 않고 경로만 등록(바로가기처럼). 드롭은 '링크' 동작으로 받아서 탐색기가 원본을 옮기거나 지우지 않게 할 것
  · 같은 경로는 중복 등록 안 함
- 더블클릭: 폴더는 탐색기로, 파일은 연결된 프로그램으로 열기
- 우클릭: 항목 → [구역에서 빼기] / 제목줄 → [이름 변경] [구역 삭제(확인창, 원본 파일은 그대로)]
- 접기 버튼 → 제목줄만 남음, 다시 누르면 펼침. 상태 저장
- 구역 이동·크기 조절은 '배치 편집' 중에만. 평소에도 접기/펼치기·열기·끌어다 놓기·우클릭은 동작
- 원본이 없어진 경로는 흐리게 표시(오류로 꺼지지 않게)

## 개발·빌드
- 클라우드 세션(리눅스)에선 윈도우 화면 테스트가 안 되니, 날짜별 구절 선택·설정 저장/불러오기 같은 로직은 분리해서 자동 테스트
- GitHub Actions(windows-latest)로 push마다 exe 빌드(Artifacts), main에 반영되면 GitHub Releases에 최신 exe 첨부
- 진행 순서: ① 말씀 위젯 + 트레이 + 자동 실행 + 빌드 → 내가 윈도우에서 확인 → ② 폴더 구역
- 단계마다 끝에 안내: exe 내려받는 법, SmartScreen 경고가 뜰 때 실행하는 법, 내가 확인할 체크리스트, 문제 생기면 log.txt 전달하는 법

## 이번엔 하지 않음 (나중에)
아멘·묵상 메모, 자동 분류, 통독·주제별 구절, 설정 화면(GUI), 구역 간 항목 이동·정렬
→ 나중에 붙이기 쉽게 말씀·구역·설정 코드는 파일을 나눠 둘 것

---

## 진행 상황 (Claude가 세션마다 갱신)
- [진행 중] ① 말씀 위젯 + 트레이 + 자동 실행 + 빌드
- [대기] ② 폴더 구역 — 사용자가 ①을 윈도우에서 확인한 뒤 시작

## 개발 메모 (다음 세션용)

### 구조와 원칙
- 파일 지도는 README "개발자용 메모" 참고. 말씀(`verses.py`)·설정(`settings.py`)·화면배치(`geometry.py`)는 Qt 없는 순수 로직 → `tests/`에서 리눅스로 테스트.
- 윈도우 전용 코드는 `versedesk/win32/`에만. 다른 OS에서는 `desktop_layer.NullDesktopLayer`가 대신함.
- Qt 슬롯은 예외를 밖으로 던지지 않음(`app.safe` 데코레이터, excepthook → log.txt).
- PySide6 함정: `QGraphicsEffect`를 부모 없이 만들면 파이썬 GC가 지워서 효과가 사라짐 → 부모 지정 + 참조 보관.
- `Qt.Tool` 창은 show() 때 Qt가 raise()를 호출함 → 위젯의 nativeEvent 거부(veto)로 막음.

### 바탕화면 고정 방식 (`versedesk/win32/desktop.py`)
- Rainmeter의 On Desktop 방식을 따름(조사 결과: Rainmeter·OpenFences·still-today 소스, Qt 6.10 소스 확인).
- 위젯 = 소유자 없는 최상위 Qt.Tool+Frameless+WindowDoesNotAcceptFocus+반투명(WS_EX_LAYERED) 창
  + WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE(+클릭 통과 시 WS_EX_TRANSPARENT), Aero Peek 제외.
- 거부(veto): `ui/desktop_widget.py`의 nativeEvent가 WM_WINDOWPOSCHANGING에 SWP_NOZORDER를 넣어 남(Qt의 show-raise,
  다른 프로그램)이 z-order를 못 바꾸게 함. 우리 이동은 SWP_NOSENDCHANGING이라 거부를 우회.
- "desktop host" = SHELLDLL_DefView를 품은 최상위 창(Progman, 또는 구버전에서 분리된 상태의 explorer WorkerW).
- 규칙: 위젯은 항상 host 바로 위. 평소 host는 맨 아래 → 위젯은 모든 앱 아래. Win+D로 host가 올라오면 위젯도 그 바로 위로
  다시 놓음(host가 topmost면 위젯도 topmost가 되고, 내려오면 HWND_NOTOPMOST로 해제).
- 감시: 500ms 타이머(올라온 동안 150ms) + 전경창 변경 WinEvent 훅 후 1초간 5번 재확인. explorer 재시작은 소유 관계가 없으니
  다음 확인 때 새 host를 찾기만 하면 됨. 다른 프로그램과 자리싸움하면 30초 쉼.
- `desktop_mode: "owner"`는 실험용 대체 수단(host를 owner/Qt transient parent로). owner 방식은 클릭 시 바탕화면 전체가 딸려
  올라오거나 Explorer와 입력 큐가 묶이는 문제가 보고되어 기본값이 아님. `Qt.WindowStaysOnBottomHint`는 Win+D 들어올림과
  싸우므로 쓰지 않음.
- 실제 Windows 검증은 CI(`tools/ci_desktop_check.py`)가 GitHub windows 러너의 실제 데스크톱에서 함(Win+D, explorer 재시작, 클릭 통과, 중복 실행, 자동 실행). 결과는 Actions의 Job Summary와 `ci-report` 아티팩트(스크린샷, log.txt).

### 말씀 데이터
- 원문: https://bereanbible.com/bsb.txt (+ 시편 표제 확인용 bsb_usfm.zip). SHA-256은 `tools/bsb.py`에 고정.
- `python3 -I tools/bsb.py download` → `tools/.cache/`(git 제외). `python3 -I tools/bsb.py lookup "John 3:16"`으로 원문 조회.
- `tools/verse_plan.tsv`(날짜→구절) 수정 후 `python3 -I tools/build_verses.py`로 `versedesk/data/verses.json` 재생성. 본문을 손으로 쓰지 말 것.

### 빌드·테스트
- 로컬(리눅스): `QT_QPA_PLATFORM=offscreen python -m pytest -q` (Qt용 시스템 라이브러리 libegl1 등 필요)
- CI: push마다 windows-latest에서 테스트 → PyInstaller(`VerseDesk.spec`) → 아티팩트 `VerseDesk-exe` → 바탕화면 점검. main push면 Release `build-N` 생성.
- 저장소는 public. 브랜치 규칙: 작업 브랜치에서 개발, PR은 사용자가 요청할 때만.
