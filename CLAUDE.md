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
> **2026-11-12 사용자 결정으로 바뀜 (아래 진행 상황 ③):** 날짜별 366구절 → 사용자가 직접 고르는 30~50개 목록을
> **차례대로, 하루 여러 번** 표시(기본 2시간마다) + 말씀 넣는 창(트레이 '말씀 목록 편집'). 이 절의 "날짜별 고정",
> "날짜가 바뀌면 교체", "verses.json 날짜 덮어쓰기" 항목은 이 결정으로 대체됨. ("설정 화면(GUI)" 보류 중 이 편집 창만 예외.)
> **2026-11-17 사용자 요청으로 추가:** 성경 구절 말고도 **사용자가 직접 타이핑한 문구**(한글 등 아무 글, 줄바꿈 유지, 출처는 선택)를
> 목록에 넣을 수 있음(편집 창 '직접 입력…'). "영어 본문만 표시"는 성경 구절에만 해당. 성경 구절(출처가 "(BSB)"로 끝남)은 고치지 않음.
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
- [완료, 사용자 확인 대기] ① 말씀 위젯 + 트레이 + 자동 실행 + 빌드 (브랜치 `claude/keen-hopper-d9tmyw`, main 미반영)
  - 사용자가 README "1단계 확인 체크리스트"로 윈도우에서 확인 → 문제 있으면 log.txt 받아서 수정
  - CI가 실제 윈도우 바탕화면 두 종류에서 매 push 점검(아래 "검증된 사실"). (구절 366일 날짜 방식은 ③에서 차례대로 도는 목록으로 바뀜.)
  - main 반영(PR/병합)은 사용자가 요청할 때만. 반영되면 Release `build-N`과 고정 링크 .../releases/latest/download/VerseDesk.exe 생김.
- ① 사용자 확인 결과(2026-11-12): Alt+Tab/작업표시줄 없음, Win+D, 배치 편집, 중복 실행 안내, 모니터 2대·다른 배율 모두 OK.
  재부팅 자동 실행은 나중에 확인 예정. **"말씀 위 바탕화면 아이콘 클릭 안 됨"** 보고 → CI(평소 상태+Win+D, 실제 마우스 클릭,
  그려진 글자 픽셀, 대조 실험)에서는 재현 안 됨. 앱이 말씀 창에 클릭이 닿으면 log.txt에 "reached the verse window although
  clicks should pass through" + 창 스타일·바탕화면 구조를 남기게 함 → 사용자 PC log.txt로 원인 확인 필요(재현 방법도 물어볼 것).
  2026-11-17에 받은 log.txt(11-12~11-17): 그 기록이 생긴 build 27(11-12 14:56) 이후 한 번도 없음 → 다시 보고되면 그때 확인.
- [완료, 사용자 확인 대기] ② 폴더 구역 (같은 브랜치) — CI 79개 점검(두 윈도우) 통과, 4관점 검토 16건+보완 4건 반영
  - 파일: `zones.py`(모델·경로 규칙·설정), `zone_manager.py`(설정↔창, 사용자 동작 저장), `zone_io.py`(작업 스레드:
    존재 확인·아이콘·열기), `shell.py`+`win32/shell.py`(SHGetFileInfo 아이콘→QImage, ShellExecuteEx 열기, 깨끗한 실행 환경),
    `ui/zone_widget.py`(상자), `ui/dialogs.py`(부모 없는 한국어 대화상자). settings.json의 `"zones"` 목록.
  - CI `check_zones`: 스타일, 상자 전체가 클릭을 받음, 다른 프로세스에서 실제 OLE 끌어다 놓기(Copy|Move|Link, Move 제안)를
    Link로 받는지+원본 그대로, 우클릭 메뉴 '구역에서 빼기', 더블클릭으로 탐색기 열림, 접기/펼치기 저장.
  - Qt 6.11 함정: `QWindowsDrag::startDoDragDrop`은 첫 WM_MOUSEMOVE에 버튼 플래그가 없으면 끌기를 취소함(E_FAIL →
    IgnoreAction). 테스트에서 드래그를 만들 땐 커서 이동·누르기를 Qt가 먼저 처리하게 한 뒤 QDrag.exec.
  - CI 러너 함정: explorer 재시작 뒤 이미지의 systempropertiesperformance.exe가 'System Properties'/'Performance Options'
    창을 띄움 → `clear_area`가 구역·끌기 경로를 가리는 남의 창을 닫음/최소화.
  - 4관점 검토(원본 안전·Qt/Windows UI·스레드·명세) 반영: 한글 PC 이름 공유 경로(ACE 'xn--' 복원), 500개 한도 안내,
    배율 125~175% 가장자리 알파, \\?\ 접두어, 유니코드 공백, 새/클릭한 구역 앞으로(`layer.bring_to_front`),
    제목줄 기준 모니터 유지, 48px 아이콘(SHIL_EXTRALARGE)+부드러운 확대, Explorer 표시 이름(SHGFI_DISPLAYNAME),
    ShellExecuteEx에 SEE_MASK_FLAG_NO_UI(깨진 바로가기 '삭제하시겠습니까?' 방지, 연결 없는 형식은 'openas'),
    작업 스레드 SetThreadErrorMode(디스크 없음 창 방지), 열기 직전 존재 재확인, 메뉴/대화상자 중 구역 삭제 지연.
  - 남은 알려진 한계: 매핑 드라이브(Z:\)와 UNC(\\server\share) 같은 대상의 중복 판단, 8.3 짧은 이름.
  - 주의(조사 결과): 구역 상자는 모든 픽셀 알파 ≥ 2/255(드롭이 바탕화면으로 새지 않게), WS_EX_TRANSPARENT 금지,
    대화상자는 부모 없이 생성(Qt.Tool 위젯을 부모로 주면 owner가 되어 같이 끌려 올라옴), 파일 열기 전 AllowSetForegroundWindow,
    경로 존재 확인·아이콘 추출은 작업 스레드에서(네트워크 경로가 GUI를 멈추지 않게)
  - 드래그 앤 드롭: dragEnter/dragMove/drop 모두 `event.setDropAction(Qt.LinkAction)`, possibleActions에 Link가 없으면 ignore.
    acceptProposedAction() 금지(Move가 되면 탐색기가 원본을 옮김). QApplication 전에 COM을 MTA로 초기화하지 말 것(Qt가 STA OleInitialize).
  - 항목 열기(os.startfile 등) 때 PyInstaller 환경을 자식 프로세스에 물려주지 않기: SetDllDirectoryW(None),
    PATH에서 sys._MEIPASS 제거, QT_PLUGIN_PATH/QML2_IMPORT_PATH 제거 후 실행하고 복원.
  - 확인/취소 같은 대화상자 단추는 한국어로 직접 지정(번역 파일 .qm은 exe에서 뺐음).

- [완료, 사용자 확인 대기] ③ 말씀 목록을 차례대로 돌리기 + 말씀 목록 편집 창 (같은 브랜치, 2026-11-12 사용자 요청)
  - 사용자 요청 원문: "매일 말씀이 바뀔 필요 없음 … 366개 고르기 좀 그래서. 그냥 순서대로 계속 돌아가면 될 듯, 하루에도 몇번씩
    돌아가면 좋고. 한 30~50개정도만 … 말씀 넣는 UI가 좀 개선되었으면 … 메모장에 바꿀려니까 좀 그래서 … 가장 간단하고 깔끔하고
    가볍고 군더더기 없는 방향으로". README 6-2 체크리스트로 확인 요청.
  - 목록: 내장 기본 40개(`tools/default_list.txt` → `versedesk/data/verses.json`). 사용자 목록 `%APPDATA%\VerseDesk\verses.json`
    (`{"verses":[{"reference","text"}]}`)이 있고 비어 있지 않으면 내장 목록을 통째로 대신함. 비면 내장 목록 표시.
  - 차례(`rotation.py`): 저장 상태 없음. index = (2000-01-01 00:00부터의 분 // interval) % 개수 (현지 벽시계 기준) → 재시작·절전 후에도
    순서가 이어짐. `settings.json` `verse.interval_minutes`(기본 120, 1~10080, 창에서 30분/1·2·3·6시간/하루). `RotationClock` = 다음 경계 단발 타이머 + 30초 확인.
  - 편집 창(`ui/verse_editor.py`): 부모 없는 일반 창(작업표시줄·Alt+Tab에 보임). 주소 입력(쉼표로 여러 개) → 내장 BSB에서 본문 자동 채움,
    2열 목록(구절|본문), ▲▼·삭제·끌어서 순서·Delete·Ctrl+↑↓, 선택 구절 전체 미리보기, 간격 선택. **바뀔 때마다 즉시 저장(저장 단추 없음)**.
    닫으면 WA_DeleteOnClose + `closed` 신호로 앱이 참조를 버림, 성경 본문(~15MB)도 해제.
  - 내장 성경(`bible.py`): `data/bsb.txt.xz` = 공식 bsb.txt 바이트 그대로 LZMA(974KB; 테스트가 SHA-256을 오프라인으로 확인),
    `data/psalm_titles.json` = USFM `\d` 표제 116개(1절 앞에서 떼어 냄, 빌드 도구와 같은 규칙). 편집 창이 처음 찾을 때만 읽음(~0.1초).
    주소 해석: 개역개정 이름·약자 + 새번역 이름 + 영어 이름·약자(가톨릭 이름은 일부러 뺌: 구약 절 번호가 달라 엉뚱한 절이 됨),
    한 장 안 10절까지, 단권(옵·몬·요이·요삼·유)은 "유 24"처럼 절만, 괄호·여러 물결표/대시 허용, 쉼표·가운뎃점·/로 여러 개.
    **한글 책 이름은 개역개정 번호**: `bible.KOREAN_NUMBERING`(고후 13:12=BSB 12–13, 13:13=BSB 14(축도), 요삼 1:15=BSB 14)로 바꿔 찾고
    편집 창에 "= 한글 성경 고후 13:13" 안내. 그 밖의 번호는 BSB와 개역개정이 같음(리뷰에서 말 4장·욜 2:28·계 12:17 등 확인).
    BSB에서 빠진 절(예: 마 17:21)은 건너뜀/오류 안내. 표시 출처 "Book C:V–W (BSB)"(엔 대시).
  - 예전 날짜형 verses.json(이전 내보내기 기능)은 시작 때 `verses.backup-<시각>.json`으로 이름만 바꿔 보관(삭제 안 함) + 트레이 알림.
  - **사용자 파일 보호(리뷰 최우선 지적):** `_verses_ok_sig` = 지금 목록을 읽어 온(또는 우리가 쓴) verses.json의 서명.
    저장 직전 디스크의 파일 서명이 다르면(망가짐·옛 형식·잠김·폴링 전 메모장 수정) 먼저 `verses.backup-<시각>.json`으로 복사(같은 이름이면 -2…).
    편집 창을 열 때마다 첫 저장 전 목록을 `verses.previous.json`에 한 벌 보관(실수 대량 삭제 복구용). 잠긴 파일(OSError)은 3번 시도 후
    `unreadable`로 표시해 다음 폴링에 다시 읽음("형식 오류"라고 하지 않음). MAX_TEXT_CHARS 3000(10절 최대 약 2,320자, 잘리면 경고).
    재검토 반영: 일부 항목을 건너뛰거나 자른 파일도 "우리 것 아님"(백업 후 저장), 시작할 때도 건너뜀/자름 개수 알림.
    폴링 재시도는 1번·잠깐 멈춤 없음(시작 때만 3번), 재시도 표시는 `RETRY_SIG`(None과 구분 → 그 사이 삭제도 알아챔).
    백업·previous 복사는 `copyfile`/`copy_contents`(윈도우 읽기 전용 속성을 옮기지 않음, previous 실패해도 저장은 진행).
    주소 나누기는 괄호 밖에서만('요 3:16 (개역개정/새번역)'), 전체가 괄호면 벗김, 괄호가 안 닫히면 그냥 나눔.
    한글 번호가 다른 장은 한글 절 수로 검사(고후 13장 13절, 요삼 15절). 목록 다시 채울 때 스크롤 위치 유지.
  - 편집 창 함정(리뷰): 단추를 클릭하면 포커스가 단추로 가고, 단추가 비활성화되면 Qt가 포커스를 다음 위젯(간격 콤보)으로 넘김 → ↑↓가
    간격을 바꿔 저장해 버림 → 단추는 TabFocus, 이동·삭제 뒤 목록에 포커스. QTreeWidget 여러 줄 끌기는 클릭 순서/역순으로 놓일 수 있음 →
    `keep_order`로 원래 순서 복원. 작은 화면(125~175%)에서는 창 크기를 작업 영역에 맞춤. 어두운 모드에서는 밝은 글자색.
  - 없앤 것: `daywatch.py`, `tools/seasonal.py`, `tools/verse_plan.tsv`, 메모장 내보내기(구절 목록 파일 만들기). 366일 계획은 커밋 22f06eb까지의 git 기록에 있음.
  - CI: 숨은 옵션 `--open-verse-editor`(트레이 대신 창 열기). `check_verse_editor`가 실제 키보드 입력(SendInput 유니코드)으로 "요 8:12"+Enter →
    verses.json에 BSB 본문 저장 확인, 창 닫아도 앱 유지, 일반 창 스타일 확인.

- [완료, 사용자 확인 대기] ④ 탐색기 창 자리 고정 (같은 브랜치, 2026-11-16 사용자 요청)
  - 사용자 요청: "창을 열면 내가 정해놓은 위치에 딱 그 배치에 열렸으면 … 탐색기만 사용할거야 … 다른 오류 안 나게, 신중하게
    딱 그 기능만 … 더 복잡해진 프로그램을 원하지 않아". README 6-3 체크리스트로 확인 요청.
  - 사용법: 트레이 체크 항목 **탐색기 창 자리 고정**(기본 꺼짐; 꺼져 있으면 아무것도 감시하지 않음). 처음 켜면 배치 편집이 켜지며
    파란 틀(`ui/slot_frame.py`, 항상 위·Tool·포커스 안 받음, 데스크톱 레이어와 무관)이 나타남 → 끌어서 자리, 오른쪽 아래 모서리로 크기.
    `settings.json` `"explorer_window": {enabled, x, y, width, height}`(논리 픽셀).
    이때 앱이 스스로 켠 배치 편집은, 사용자가 배치 편집을 직접 건드리기 전에 체크를 다시 끄면 같이 꺼짐(`app._edit_for_slot`;
    안 그러면 틀은 사라졌는데 말씀이 계속 클릭을 받음 — 사용자가 전에 보고한 것과 같은 증상; 그 보고 자체는 이 기능 이전이라 원인은 별개).
    사용자가 직접 켠 배치 편집은 건드리지 않음.
  - 규칙(`explorer_placer.py`): 기능을 켠 뒤 **화면에 새로 나타난 탐색기 창(클래스 CabinetWClass)만, 한 번** 자리로 옮김. 이미 열려 있던 창,
    나중에 사용자가 옮긴 창, 다른 프로그램 창은 건드리지 않음. 마우스 단추를 누르고 있는 동안은 옮기지 않고(더블클릭을 늦게 떼는 경우는
    떼면 옮김, 그 사이 창이 움직였으면 = 탭을 끌어낸 것 → 그대로 둠), 한 번이라도 옮긴 뒤 단추가 눌리면 손을 뗌.
    최대화된 창은 복원(SW_SHOWNOACTIVATE)을 한 번 요청하고 기다린 뒤 옮김. 보이지 않는 테두리는 GetWindowRect − DWM 확장 프레임으로 재서 보정.
    확인은 150ms 간격·최대 40번, 이동 최대 3번, 자리에 들어간 뒤 400ms 후 한 번 더 확인(다른 배율 모니터로 넘어갈 때 대비).
    검토(2026-11-16) 반영: 복원을 요청한 창에는 "끌어낸 탭" 판정을 하지 않음(우리 복원이 창 사각형을 바꿈 → 단추가 눌린 채 최대화로
    열린 창이 버려지던 문제). 옮긴 뒤 단추가 눌려 손을 뗄 때는 log에 "mouse button down after N move(s) …" 한 줄(자리에 든 것을 이미
    본 뒤라면 생략). 아직 옮기지 않은 창이 최소화돼 있으면 숨김/가림과 똑같이 취급(3초 기다렸다 잊고, 활성화 알림 때 다시 시도).
    알고 둔 한계: 최대화로 열린 창을 우리가 복원한 직후(첫 이동 전 약 0.15초 사이) 사용자가 잡아 끌면 그 창도 자리로 옮겨짐
    (복원 뒤의 사각형을 따로 기억하면 구분되지만, 사람이 그 틈에 잡기는 사실상 불가능해서 상태를 늘리지 않음).
  - 감지(`win32/explorer.py`): 숨은 Qt 위젯에 `RegisterShellHookWindow` → "SHELLHOOK" 메시지의 HSHELL_WINDOWCREATED(1, 창이 **보일 때** 옴)와
    WINDOWACTIVATED(4, 0x8004 포함)만 읽음(다른 코드의 lParam은 HWND가 아님). 클래스 이름으로 먼저 걸러서 다른 프로그램 창은 타이머도 안 만듦.
    Explorer 재시작(TaskbarCreated) 때 다시 등록. WinIdChange에서는 예약만 하고 winId()를 부르지 않음(Qt가 창을 만드는/부수는 중).
  - **절대 지킬 것:** 남의 창에는 비동기 호출만(SWP_ASYNCWINDOWPOS, ShowWindowAsync) — 동기 SetWindowPos/ShowWindow/SendMessage는 탐색기가
    멈추면 우리 앱도 멈춤. SWP_NOSENDCHANGING 금지(최소 크기 검사를 건너뜀). 최대화 상태에서는 SetWindowPos 금지.
  - "이미 열려 있음" = 보이고, 가려지지(cloak) 않았거나 셸이 가린 것(다른 가상 데스크톱). 숨겨진 채 준비된 창(윈도우 11 탐색기 미리 띄우기,
    아직 동작 미확인)은 처음 화면에 나올 때 옮김. 숨김/가림 상태로 보고된 창은 3초 기다렸다 잊고, 활성화 알림 때 다시 시도.
  - 좌표: 설정·Qt는 논리 픽셀, 윈도우는 실제 픽셀. `explorer_slot.to_native` = Qt와 같은 규칙(창 중심이 있는 화면 기준, 화면 왼쪽 위는 두 좌표계에서
    같은 점, 거리×배율, qRound(반올림은 0에서 멀어지는 쪽), 폭·높이는 따로 반올림). CI가 QT_SCALE_FACTOR=1.5로 실제 창과 1px 안에서 일치 확인.
    배율이 다른 모니터 사이에는 논리 좌표에 틈이 있어, 틀은 끄는 동안 항상 마우스가 있는 모니터 안에 통째로 두고 잡을 때의 크기를 유지함
    (`tests/test_slot_frame.py`가 150%+100% 가짜 모니터로 확인). 그 모니터 화면보다 큰 틀은 그 화면 크기로 줄여서 보여 주고(두 모니터에
    걸치지 않게), 거기에 놓으면 줄어든 크기로 저장(안 그러면 `place_on_screens`의 50% 규칙 때문에 주 모니터로 튕겨 돌아감).
    줄일 때도 틀의 최소 크기(480x320) 아래로는 내려가지 않음(저장값 = 보이는 값; 최소보다 작은 값은 다음 시작 때 설정 오류로 버려지므로). `_work_area` = availableGeometry ∩ geometry(Qt 6.10~6.11.3은 작업 표시줄이
    위/왼쪽이고 배율 100% 초과일 때 작업 영역을 어긋나게 보고함).
  - 실제 윈도우 확인(CI, 두 러너): 정확한 자리(테두리 7px 보정 포함), 셸 프로세스 소유 창, 최대화→복원→이동, explorer 재시작 후에도 동작,
    단추를 누르고 있는 동안 대기, 가짜 탐색기 창(`tools/ci_fake_explorer.py`: 숨김→표시, 가림→해제+클릭, 4초 무응답 동안 앱은 응답, 크기 거부),
    틀 끌기·크기·저장, 틀과 창 일치, Win+D.
    실행 34(커밋 d5b03e9, 147개 점검)에서 추가로 확인: 나타나자마자 멈춘 창은 이동 요청이 **대기**하고(창은 제자리), 그동안 앱은 응답하며,
    4초 뒤 깨어나면 그 요청대로 옮겨짐("after 1 move(s)"). 최소화된 채 처음 표시된 창에도 HSHELL_WINDOWCREATED가 옴 → 앱이 3초 기다렸다 잊고,
    띄워서 클릭(활성화)하면 자리로 옮김. 실제 탐색기 창(Slot G)은 그때 자기 기억대로 자리 안에 스스로 열렸음("opened in the slot by itself")
    → "멈춘 창이 있는 동안 다른 창도 옮겨지는가"는 기억이 없는 대역 창(plain)으로 확인하도록 바꿈(실행 35·36: 멈춘 창이 깨어나기 전에
    plain 창이 자리로 옮겨짐). 최종 상태: 커밋 4b4c8a9, 실행 36 — 두 러너 모두 148개 점검, 실패 0·경고 0. **탐색기는 "마지막으로 닫은 창 자리"를 스스로 기억하고 그게 항상 마지막 창도 아님 →
    점검에서 그 기억을 기준으로 삼지 말 것**(자리를 번갈아 쓰고, 앱 로그의 "placed in the slot ... 0x<hwnd>"로 확인).
  - 사용자 PC에서만 알 수 있는 것: 배율이 다른 두 모니터 사이 이동(로그에 "after 2 move(s)"가 나오면 정상), 윈도우 11 탭 끌어내기,
    탐색기 미리 띄우기 동작. log.txt에 "explorer window ..." 줄이 남음(켤 때 열려 있던 창 목록, 옮긴 결과, 틀을 놓았을 때 계산값과 실제 창 위치).
  - 알려진 한계(README에 안내): 창이 원래 자리에 잠깐 보였다 옮겨짐, 여러 창은 같은 자리에 겹침, 이미 열린 창에 새 탭으로 열리면 옮길 것이 없음,
    제어판·휴지통도 같은 클래스라 같이 옮겨짐, 끈 뒤에도 탐색기 자체 기억 때문에 같은 자리에 열릴 수 있음, 배치 편집 중 틀이 아래 것을 가림.
  - CI 숨은 옵션 `--exit-file PATH`(파일이 생기면 정상 종료; 점검 구간을 기다리지 않고 끝냄).
  - 점검 도구 함정(검토에서 발견): 대역 창 `slow`가 0.3초 동안 메시지를 처리한 뒤 멈추면 이동 요청이 그 사이에 끝나 버려 "멈춘 창에
    요청이 걸려 있는 동안 앱이 응답하는가"를 증명하지 못함 → 나타나자마자 멈추게 하고 "요청이 아직 대기 중"을 따로 확인.
    "이미 열려 있던 창" 점검은 앱 로그의 "1 Explorer window(s) already open"도 확인(창을 다시 건드리지 않으면 장부가 없어도 통과하므로).
    `tests/test_explorer_placer.py`만 따로 돌리면 죽던 문제: 테스트가 hide()를 바꿔 둔 틀이 화면에 남아 다음 테스트의 그리기 도중 파괴됨
    → 그 테스트 끝에서 틀을 숨김(앱 문제가 아님).

- [완료, 사용자 확인 대기] ⑤ "바탕화면 클릭하면 모든 창이 최소화" 보고 조사 + 진단 기록 (같은 브랜치, 2026-11-17)
  - 사용자 log.txt: 11-17 13:40:23 절전 복귀(30분 차례 변경이 늦게 기록됨) → 13:40:25·26 화면 구성 변경 → 13:40:58~13:41:44
    46초에 Show desktop 켜짐/꺼짐 10번(평소엔 하루 몇 번, 1~10초, 대개 Win+D 뒤 구역에서 열기) → 재부팅으로 해소.
    그 세션에 경고·오류 없음, 그 사이 구역·탐색기 자리 동작 없음. 같은 날 07:43 탐색기 두 번 재시작(그 뒤 Win+D 정상).
  - 4관점 조사(윈도우 쪽 원인 / VerseDesk 동작 / 로그 감식 / 반대 심문): VerseDesk는 최소화·바탕 화면 보기 API를 부르지 않고
    입력을 보내지 않으며 Progman을 움직이지 않음 → 관찰만 했다고 판단(확정 아님). 가장 그럴듯한 원인: 탐색기의 '바탕 화면 보기'
    상태가 절전·모니터 재연결 뒤 꼬임. 공개 보고는 대부분 StartAllBack 3.9.20 '향상된 클래식 작업 표시줄' + 25H2(바탕화면 클릭마다
    Win+D처럼 최소화, Win+D로 잠시 풀림, 옵션을 끄면 해결; 안전 모드에선 안 생김) — 그 밖에 Microsoft Q&A 몇 건(탐색기 다시 시작으로
    풀림). 사용자 PC는 재부팅으로 풀려 다를 수 있음 → **다음 보고 때 StartAllBack·ExplorerPatcher·Windhawk 같은 작업 표시줄 프로그램을
    쓰는지 물어볼 것**(탐색기에 주입되어 창 목록에는 안 보임). 덜 그럴듯: 터치패드 세 손가락 제스처, 눌린 채 남은 Win 키,
    위 모니터 작업 표시줄의 '바탕 화면 보기' 모서리(노트북 화면 위 가장자리 바로 위).
    "desktop raised" 줄 = Progman이 센티널 위로 올라오고 그 위에 보통 앱 창이 없음(= Show desktop의 모양).
  - 추가한 기록(사용자에게 안 보임, `win32/desktop.py`): 켜짐/꺼짐 줄 끝에 ` | ` 뒤로 이유(lowered by Explorer / covered by 창),
    전경 창, 커서 위치와 그 아래 창, 지금 눌린 키·버튼(`api.keys_down`), 마지막 입력 후 ms, 앱 창 집계(`app_window_census`:
    minimised / covered by the desktop / above it — 진짜 Show desktop은 minimised), 최근 5초 전경 변경과 그때 눌린 키
    (WinEvent 훅에서 기록: 쌓인 알림을 처리하는 순간의 물리적 상태라 대개 클릭은 LButton, Win+D는 LWin (D)이지만 짧게 누르면
    none일 수 있음 — CI의 합성 Win+D는 none. none ≠ 클릭·Win+D 아님, last input ms와 함께 볼 것. 관리자 권한 창이 앞에 있으면
    키를 못 읽어 none. LButton = 주 단추(단추를 바꾼 설정 반영)). 30초 안에 4번 켜지면 WARNING + 전체 창 목록
    + `show_desktop_storm` 신호 → 트레이 알림 "창이 자꾸 모두 내려가나요?"(Win+D, 탐색기 다시 시작 안내; 1시간에 한 번).
    키퍼 패스 간격 20초 초과 → "no desktop check for N s (tick counter: M s)"(절전; M이 훨씬 작으면 시계를 바꾼 것).
    화면 구성 변경 때 화면 목록. 로그 시간 ms(`logging_setup`). 기준 창 기록은 클래스·pid만(`_short`: 우리 프로세스 창의 제목을
    읽으면 WM_GETTEXT를 보내므로).
    시작 때 "Windows 25H2, build 26200.UBR"(`main._windows_build`, 레지스트리). SetWindowPos 실패는 오류 코드와 WARNING(실행당 20줄;
    INFO 40줄 한도에 묻히지 않게).
  - 함께 고친 실제 버그: insert-after 기준 창을 윈도우가 거부하면(사용자 PC: 다른 프로세스의 숨은 'Default IME'·
    'CicLoaderWndClass', ok=False) Show desktop이 끝난 직후 위젯이 HWND_NOTOPMOST 자리(모든 앱 창 위)에 남음(11-13 14:16 싸움 경고)
    → `_insert_after`: 다음 창 위로 최대 4번(건너뛰는 건 숨은 창), topmost 기준 창은 넘지 않음(그 위 topmost 아래에 넣으면 위젯이
    topmost가 됨), 기준 창이 사라지면 HWND_TOP으로 빠지지 않고 다음 패스에. `bring_to_front`도 같은 경로.
  - 사용자 안내: README 7-1(Win+D 한 번→한 번 더 → VerseDesk 종료 후 확인(계속 내려가면 지금 내리는 건 VerseDesk가 아님; 처음 계기까지
    가리지는 못함) → 작업 관리자에서 Windows 탐색기 다시 시작 → VerseDesk 다시 켜기 → 시각·log.txt, 작업 표시줄 프로그램 여부).
    동작(고정 방식)은 바꾸지 않음: Rainmeter와 같은 방식이고 로그상 원인이 아님. 다시 생기면 새 log.txt 줄로 판단.
  - CI `check_show_desktop_log`: 실제 Win+D 줄에 최소화 집계·전경·커서·키, 돌아올 때 최소화 수가 줄고 위 창 ≥1(러너 콘솔은 미리
    최소화돼 있어서 "N minimised ≥ 1"만으로는 증명이 안 됨), ms 시간, 빠른 Win+D 10번 → 경고 1번 + 알림. Win+D가 안 먹는
    러너에서는 WARN(앱 잘못이 아님). 실행 37(c62ce86): 두 러너 157개 점검 통과 — 24H2는 'lowered by Explorer', windows-2022는
    WorkerW가 떠 있는 채 'covered by TkTopLevel'로 돌아옴. 검토 반영 뒤 실행 38(992dbb9): 두 러너 159개, 실패 0·경고 0
    (사용자에게 준 exe). 실제 줄 예: "desktop raised ... | foreground 'Progman'; cursor (864, 594) over 'SysListView32' in
    'Progman'; held none, last input 16 ms ago; app windows: 2 minimised, 0 covered by the desktop, 0 above it; ..."
  - 사용자에게 물어본 것(답 기다림): 작업 표시줄·시작 메뉴를 바꾸는 프로그램을 쓰는지, 그때 마우스였는지 터치패드였는지.

- [완료, 사용자 확인 대기] ⑥ 내 문구 직접 입력 (같은 브랜치, 2026-11-17)
  - 사용자 요청: "직접 타이핑 할 수 있는 거 추가로 넣어줘 … 다른 문구 같은 것도 내가 타이핑해서 넣고 싶을 수 있으니까"
    (그 전에 "용량이 성경 때문이냐"는 검토 질문 → 답: exe 27.5MB 중 내장 성경 약 1MB(빌드 27 26.48MB → 빌드 28 27.47MB),
    나머지는 파이썬+Qt 엔진(빌드 15에서도 26.4MB), 성경은 편집 창이 열려 있을 때만 메모리에 올림 → 성경은 그대로 두기로).
  - 편집 창(`ui/verse_editor.py`): 윗줄 **직접 입력…** → `OwnTextDialog`(부모 = 편집 창, WindowModal: 구역은 계속 쓸 수 있음;
    문구 QPlainTextEdit(Enter=줄바꿈, Tab=출처 칸으로), 출처 QLineEdit(120자), 추가/취소, Ctrl+Enter, 글이 없거나 3000자 넘으면 추가 불가).
    목록 맨 아래에 `Verse(출처, 문구, "user")`. 같은 문구+출처는 두 번 안 들어감. 옆 단추 **고치기**(+두 번 클릭)는 직접 입력한
    줄만(`verses.is_bible_verse` = 출처가 "(BSB)"로 끝남 → 고치지 않음, 안내 문구). 대화상자가 열린 사이 verses.json이 밖에서 바뀌어
    목록이 다시 채워졌으면 원래 줄을 다시 찾고, 없으면 고치지 않고 "다시 해 주세요". 테스트는 `editor.ask_own`을 바꿔 끼움.
  - `verses.clean_text`: **본문 줄바꿈 유지**(모든 줄 끝 종류, 줄 안 공백 정리, 앞뒤 빈 줄 삭제, 빈 줄 여러 개는 하나로) — 예전에는 줄바꿈을
    공백으로 바꿨음. 출처는 한 줄(`clean_reference`). 대화상자도 같은 함수로 정리하므로 저장값 = 다시 읽은 값.
    목록 칸에는 줄바꿈을 " / "로, 미리보기·바탕화면에는 실제 줄바꿈(verse_widget의 drawText가 그대로 줄을 바꿈).
  - CI `check_verse_editor`: 윗줄 오른쪽 끝(클라이언트 폭-50, y 22) 클릭 → "직접 입력" 창 → 실제 키 입력으로 "Line one" Enter "둘째 줄"
    Tab "CI 출처" Enter → verses.json 마지막 항목 확인, 한 항목짜리 목록을 써서 한 줄/두 줄일 때 말씀 창 높이 비교.
    앱은 `start_app`/`end_app`(--exit-file)로 띄워 기다림이 줄었고, 끝나면 verses.json을 지워 뒤 점검은 기본 목록으로 시작.
    실행 40(c6489f8): 두 러너 163개 점검, 실패 0·경고 0, 말씀 창 높이 한 줄 71px → 두 줄 102px. (건너뜀 2~3개는 전부터 있던
    '러너에서 말씀이 다른 창에 가려짐' 클릭 점검.)
  - 독립 검토(3관점+반박 검증) 반영: `set_list`(밖에서 바뀐 파일을 다시 채울 때)가 선택을 `key()`로 복원 → 출처가 같은 직접 입력
    문구(key()가 같음)가 모두 골라져 삭제 한 번에 같이 지워짐 → (출처, 문구)로 각 항목 한 번씩만 다시 고름(Counter).
    `add_from_input`의 1000개 한도는 key 수가 아니라 줄 수로. 미리보기·안내 줄은 PlainText(타이핑한 "<b>"가 HTML로 보이지 않게).
    README 3-2/6-2: 새 줄은 맨 아래라 차례가 오기까지 며칠 걸릴 수 있음 → 바로 보려면 지금 바탕화면 말씀 줄 바로 위로 끌어 올리기.
    반박된 것: 고치기로 똑같은 항목을 하나 더 만들 수 있음(일부러 자주 보이게 하는 방법이기도 함, 그대로 둠),
    CI가 verses.json을 제자리에서 다시 씀(빈 파일을 읽을 확률 약 1/10000).
    검토 반영 뒤 실행 41(9436cfc): 두 러너 163개 점검, 실패 0·경고 0 → 사용자에게 준 exe = 빌드 41(README 6-2로 확인 요청).
  - 사용자 요청(빌드 41 화면 보고): 대화상자 이름표는 "문구"/"출처"만, 칸 안 안내는 "말씀을 입력해주세요"/"출처를 입력해주세요.(생략가능)"(예시 문구 없음).

## 개발 메모 (다음 세션용)

### 구조와 원칙
- 파일 지도는 README "개발자용 메모" 참고. 말씀 목록(`verses.py`)·성경 조회(`bible.py`)·차례 계산(`rotation.py`의 순수 함수)·설정(`settings.py`)·화면배치(`geometry.py`)는 Qt 없는 순수 로직 → `tests/`에서 리눅스로 테스트.
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
- `_sync_entry`가 매 tick마다 `_apply_styles`로 창 스타일을 다시 맞춤 → 다른 프로그램이 WS_EX_TRANSPARENT를 지워도 1 tick 안에 복구(CI 점검).
- 실제 Windows 검증은 CI(`tools/ci_desktop_check.py`)가 GitHub windows 러너의 실제 데스크톱에서 함(Win+D, explorer 재시작, 클릭 통과,
  배치 편집 드래그·저장·재시작 복원, 중복 실행, 자동 실행, 유휴 CPU/메모리). 결과는 Actions의 Job Summary와 `ci-report` 아티팩트(스크린샷, log.txt).
  - 숨은 옵션: `--edit-mode`(배치 편집 켠 상태로 시작; 트레이는 자동화로 못 누르므로 CI 전용), `--exit-after N`, `--no-duplicate-dialog`.
  - 레이어드 창은 알파 0인 픽셀에서는 WS_EX_TRANSPARENT가 없어도 클릭이 통과함 → 클릭 통과 점검은 "그려진 글자 픽셀"에서 하고,
    WS_EX_TRANSPARENT를 잠깐 지운 대조 실험에서 그 픽셀이 실제로 잡히는지 확인함. (같은 이유로 ② 구역 상자는 모든 픽셀 알파 ≥ 2/255.)

### 말씀 데이터
- 원문: https://bereanbible.com/bsb.txt (+ 시편 표제 확인용 bsb_usfm.zip). SHA-256은 `tools/bsb.py`에 고정.
- `python3 -I tools/bsb.py download` → `tools/.cache/`(git 제외). `python3 -I tools/bsb.py lookup "John 3:16"`으로 원문 조회.
- `tools/default_list.txt`(기본 목록, 30~50개, 1~3절) 수정 후 `python3 -I tools/build_verses.py` → `versedesk/data/verses.json`, `bsb.txt.xz`,
  `psalm_titles.json` 재생성(`--check`로 확인, CI data 작업도 공식 파일로 다시 만들어 비교). 본문을 손으로 쓰지 말 것.
  테스트(`test_embedded_data.py`)가 bsb.txt.xz의 SHA-256 = 고정값, 기본 목록 본문 = 앱의 조회 결과, 표제가 1절 앞에 있음을 오프라인으로 확인.
- 판(edition): bsb.txt에는 판 표시가 없음. Last-Modified 2026-07-31, 공식 changelog 2026-07-31 항목까지 반영된 본문(README·verses.json source에 기록).
  출판사는 같은 주소의 파일을 고쳐 올리므로 다시 받으면 해시가 달라질 수 있음 → 그때는 기본 목록 비교·changelog 확인 후 SOURCES 갱신,
  bsb.txt.xz도 새 파일로 다시 만들어야 함(사용자 verses.json에 이미 들어간 본문은 그대로 남음).
- 원문 그대로를 지킴: 다른 절에서 열린 따옴표로 끝나는 구절(끝의 ”)도 고치지 않음(바꾸면 BSB 이름을 쓰지 말라는 출판사 요청).

### 검증된 사실 (CI의 실제 윈도우 바탕화면에서 확인, 2026-11)
- windows-latest(Server 2025, 빌드 26100 = Win11 24H2 구조): Progman이 DefView를 품음. Win+D → 앱 최소화 후 Progman이 올라옴
  → 위젯이 작업표시줄 바로 아래 topmost로 들려 보임 → 다시 Win+D/앱 복원 시 정상 위치로 내려감.
- windows-2022(Server 2022, 빌드 20348 = Win10 구조): Win+D 때 DefView가 새 WorkerW로 옮겨지고 그 WorkerW가 올라옴
  → host 재탐색으로 따라감. explorer 재시작 후에도 같은 창(HWND)으로 계속 바탕화면 위에 있음.
- 두 러너 모두: Win+D 상태에서 그려진 글자 픽셀 클릭이 바탕화면(SysListView32)으로 통과. 유휴 CPU 약 0.15%(코어 1개 기준),
  작업 집합 약 69MB(onefile 실행기 포함 2개 프로세스). exe 약 26MB(③부터 내장 성경 포함). 러너 화면은 1024x768 한 개라 DPI/다중 모니터는 사용자 확인 필요.

### 빌드·테스트
- 로컬(리눅스): `pip install -r requirements-dev.txt` 후 `QT_QPA_PLATFORM=offscreen python -m pytest -q`
  (Qt용 시스템 라이브러리 libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 필요; 시스템 python에는 pytest가 없으니 venv 사용)
- CI(`.github/workflows/build.yml`): push마다 windows-latest·windows-2022에서 테스트 → PyInstaller(`VerseDesk.spec`) → 아티팩트 `VerseDesk-exe`
  (windows-latest만) → 바탕화면 점검. ubuntu의 data 작업이 공식 bsb.txt를 받아 verses.json이 그대로인지 확인(사이트 변경 시 경고만).
  main push면 release 작업이 GitHub CLI(`gh`)로 Release `build-N` 생성(main 실행은 취소 안 됨), 다른 브랜치는 dry run(다운로드·gh 확인만).
- 저장소는 public. 브랜치 규칙: 작업 브랜치에서 개발, PR은 사용자가 요청할 때만.
