# VerseDesk

윈도우 바탕화면에 **오늘의 성경 말씀(영어, BSB)** 을 배경처럼 띄워 주는 작은 프로그램입니다.
날마다 자동으로 바뀌고, 인터넷이 없어도 동작합니다. 설치 없이 `VerseDesk.exe` 파일 하나로 실행합니다.

> 지금은 **1단계(말씀 위젯 + 트레이 메뉴 + 자동 실행)** 입니다. 폴더를 모아 두는 "구역" 기능은 2단계에서 추가됩니다.

---

## 1. 내려받기

### 방법 A — GitHub Actions에서 받기 (지금 단계 확인용)

1. GitHub에 로그인한 뒤 이 저장소 페이지에서 위쪽의 **Actions** 탭을 누릅니다.
2. 목록 맨 위(가장 최근)의 **build** 실행을 누릅니다. 왼쪽에 초록색 체크(✓)가 있는지 확인하세요.
3. 페이지 아래쪽 **Artifacts** 칸에서 **VerseDesk-exe** 를 누르면 zip 파일이 내려받아집니다.
4. zip 파일을 오른쪽 클릭 → **압축 풀기** → 안에 있는 `VerseDesk.exe` 가 프로그램입니다.

### 방법 B — Releases에서 받기 (main 브랜치에 반영된 뒤)

- <https://github.com/kimlin70-spec/VerseDesk/releases/latest> → **Assets** → `VerseDesk.exe` (로그인 없이 받을 수 있습니다)

## 2. 놓아 둘 곳과 실행

1. `VerseDesk.exe` 를 오래 둘 폴더로 옮기세요. 예: `문서\VerseDesk\VerseDesk.exe`
   (자동 실행은 exe가 있는 위치를 기억합니다. 나중에 옮겨도, 옮긴 곳에서 한 번 실행하면 알아서 고쳐집니다.)
2. 더블클릭해서 실행합니다. 첫 실행은 몇 초 걸릴 수 있습니다. 검은 콘솔 창은 뜨지 않습니다.
3. 화면 **오른쪽 위**에 오늘의 말씀이 나타나고, 작업 표시줄 오른쪽 아래에 VerseDesk 아이콘(남색 바탕의 펼친 책)이 생깁니다.
   아이콘이 안 보이면 작업 표시줄의 **^** (숨겨진 아이콘 표시) 단추를 눌러 보세요.

### "Windows의 PC 보호" (SmartScreen) 경고가 뜰 때

서명되지 않은 새 프로그램이라 처음 한 번 경고가 나올 수 있습니다.

1. 파란 경고 창에서 **추가 정보** 를 누릅니다.
2. 아래에 생기는 **실행** 단추를 누릅니다.

한 번 실행하면 다음부터는 경고가 나오지 않습니다. (새 버전 exe로 바꾸면 다시 한 번 나올 수 있습니다.)

그 밖에 이런 경우가 있을 수 있습니다.

- **내려받을 때 브라우저가 경고**("일반적으로 다운로드되지 않는 파일" 등): 목록에서 `…` → **유지** → **자세히** → **그래도 계속** 을 누르세요.
- **파란 창에 "실행" 단추가 없을 때**: exe 파일을 오른쪽 클릭 → **속성** → 아래쪽 **차단 해제** 에 체크 → 확인 → 다시 실행.
- **Windows 11에서 "스마트 앱 컨트롤이 차단했습니다"**: 서명이 없는 프로그램은 이 기능이 켜져 있으면 실행할 수 없습니다. 끄는 방법은 설정 → 개인 정보 및 보안 → Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 설정이지만, 한 번 끄면 다시 켜기 어려울 수 있으니 **바로 끄지 말고 먼저 알려 주세요.**
- **회사 PC에서 보안 프로그램이 실행을 막을 때**: 막혔다는 메시지 화면을 캡처해서 알려 주세요.

### 새 버전으로 바꿀 때

트레이 메뉴 → **종료** 로 먼저 끈 다음, 같은 폴더의 `VerseDesk.exe` 를 새 파일로 덮어쓰고 다시 실행하세요. 설정과 구절 파일은 `%APPDATA%\VerseDesk` 에 있어서 그대로 남습니다.

## 3. 사용법

트레이 아이콘을 **클릭**(왼쪽이든 오른쪽이든)하면 메뉴가 열립니다. 별도의 프로그램 창은 없습니다.

| 메뉴 | 하는 일 |
|---|---|
| 배치 편집 켜기 / 끄기 | 켜면 말씀 상자에 점선 테두리가 생기고 마우스로 끌어 옮길 수 있습니다. 끄면 위치가 저장되고, 다시 클릭이 뒤로 통과됩니다. |
| 새 구역 추가 | 2단계에서 제공 예정입니다(지금은 회색). |
| Windows 시작 시 자동 실행 | 체크되어 있으면 로그인할 때 자동으로 실행됩니다(기본: 켜짐). |
| 설정·로그 폴더 열기 | `%APPDATA%\VerseDesk` 폴더를 엽니다. `settings.json`, `log.txt` 가 여기 있습니다. |
| 종료 | 프로그램을 끕니다. |

- 말씀은 **바탕화면 층**에 붙어 있어서 다른 창 위로 올라오지 않고, 작업 표시줄과 Alt+Tab 목록에도 나오지 않습니다.
- **Win+D**(바탕 화면 보기)를 눌러도 말씀은 그대로 보입니다.
- 평소에는 말씀 위를 클릭해도 뒤쪽 바탕화면 아이콘이 그대로 눌립니다.
- 날짜가 바뀌면(자정, 절전에서 깨어날 때 포함) 말씀도 자동으로 바뀝니다. 같은 날짜에는 해마다 같은 구절이 나옵니다.

## 4. 글자 크기 등 바꾸기 — `settings.json`

1. 트레이 메뉴 → **설정·로그 폴더 열기**
2. `settings.json` 을 오른쪽 클릭 → **연결 프로그램** → **메모장**
3. 숫자나 글자를 바꾸고 **저장**(Ctrl+S) 하면 2초 안에 화면에 반영됩니다. 프로그램을 다시 켤 필요가 없습니다.

```json
{
  "version": 1,
  "autostart": true,
  "desktop_mode": "bottom",
  "debug_log": false,
  "verse": {
    "x": null,
    "y": null,
    "width": 520,
    "font_family": "Georgia",
    "font_size": 20,
    "reference_font_size": null,
    "color": "#FFFFFF",
    "shadow": true,
    "align": "right"
  }
}
```

| 항목 | 뜻 | 예 |
|---|---|---|
| `font_size` | 본문 글자 크기(포인트) | `24` |
| `reference_font_size` | 출처 글자 크기. `null` 이면 본문의 65% | `14` |
| `width` | 말씀 상자 너비(픽셀, 100% 배율 기준) | `600` |
| `font_family` | 글꼴 이름 | `"Georgia"`, `"Segoe UI"` |
| `color` | 글자 색 | `"#FFFFFF"`(흰색), `"#FFF4D6"`(따뜻한 흰색) |
| `shadow` | 글자 테두리·그림자(어느 배경에서도 읽히게) | `true` / `false` |
| `align` | 줄 맞춤 | `"right"`, `"left"`, `"center"` |
| `x`, `y` | 위치. `null` 이면 주 모니터 오른쪽 위. 배치 편집으로 옮기면 자동 저장 | `null` |
| `autostart` | Windows 시작 시 자동 실행 | `true` / `false` |
| `desktop_mode` | 바탕화면 고정 방식(아래 9번 참고). 바꾸면 **다시 시작**해야 적용 | `"bottom"` |
| `debug_log` | `true` 면 문제 해결용 자세한 기록을 log.txt에 남김. 바꾸면 **다시 시작**해야 적용 | `false` |

- 쉼표나 따옴표를 빠뜨리면 트레이에 "형식 오류" 알림이 뜨고, 고칠 때까지 이전 설정을 그대로 씁니다.
- 처음 상태로 되돌리려면: 트레이 메뉴 → 종료 → `settings.json` 삭제 → 다시 실행.
- 저장된 위치가 화면 밖(예: 떼어 낸 모니터)이면 주 모니터 안으로 옮겨서 보여 줍니다.

## 5. 원하는 날짜의 구절 바꾸기 — `verses.json`

같은 폴더(`%APPDATA%\VerseDesk`)에 `verses.json` 을 만들면, **그 파일에 적은 날짜만** 내 구절로 바뀌고 나머지 날짜는 내장 구절이 그대로 나옵니다.
메모장으로 아래처럼 쓰고, 파일 형식을 **UTF-8** 로 저장하세요(최근 메모장은 기본이 UTF-8).

```json
{
  "verses": [
    { "date": "12-25", "reference": "Luke 2:11 (BSB)", "text": "Today in the city of David a Savior has been born to you. He is Christ the Lord!" },
    { "date": "03-14", "reference": "", "text": "출처 없이 본문만 보여 줄 수도 있습니다." }
  ]
}
```

- `date`: `"월-일"` (예: `"01-05"`, `"1-5"`, `"1/5"` 모두 가능). 2월 29일은 `"02-29"`.
- `reference`: 화면에 보일 출처(비워도 됨). `text`: 본문.
- 저장하면 2초 안에 반영됩니다. 파일을 지우면 다시 내장 구절로 돌아갑니다.

## 6. 1단계 확인 체크리스트

- [ ] 실행할 때 검은 콘솔 창이 뜨지 않는다
- [ ] 주 모니터 오른쪽 위에 영어 말씀과 출처(예: `John 3:16 (BSB)`)가 보인다
- [ ] 밝은 배경화면과 어두운 배경화면에서 모두 잘 읽힌다(배경화면을 바꿔 보기)
- [ ] 말씀 위에 있는 바탕화면 아이콘을 클릭/더블클릭할 수 있다(클릭 통과)
- [ ] 메모장 같은 창을 말씀 위로 옮기면 창이 말씀을 덮는다(말씀이 창 위로 올라오지 않음)
- [ ] 작업 표시줄과 Alt+Tab 목록에 VerseDesk가 없다(트레이 아이콘만 있음)
- [ ] Win+D 를 눌러도 말씀이 계속 보인다. 한 번 더 누르면 창들이 돌아오고, 창들이 말씀을 덮는다
- [ ] 배치 편집 켜기 → 끌어서 옮기기 → 배치 편집 끄기 → 종료 후 다시 실행해도 옮긴 자리에 있다
- [ ] `settings.json` 의 `font_size` 를 바꿔 저장하면 글자 크기가 바뀐다
- [ ] `VerseDesk.exe` 를 한 번 더 실행하면 "이미 실행 중" 안내가 나온다
- [ ] 다시 로그인(또는 재부팅)하면 자동으로 실행된다. 메뉴에서 자동 실행을 끄면 실행되지 않는다
- [ ] (해당되면) 모니터 2대 / 배율 125%·150% 에서도 글자가 흐리지 않고 위치가 맞다
- [ ] (선택) 작업 관리자에서 "Windows 탐색기"를 **다시 시작**해도 말씀이 바탕화면에 그대로 붙어 있다
- [ ] (선택) 자정이 지나면 다음 날 구절로 바뀐다

## 7. 문제가 생기면 — `log.txt` 보내는 법

1. 트레이 메뉴 → **설정·로그 폴더 열기** (트레이가 안 보이면 키보드 **Win+R** → `%APPDATA%\VerseDesk` 입력 → 확인)
2. `log.txt` 를 채팅 창에 끌어다 놓아 첨부하거나, 메모장으로 열어 **전체 선택(Ctrl+A) → 복사(Ctrl+C)** 해서 붙여 넣어 주세요.
   `log.txt.1`, `crash.txt` 가 있으면 함께 보내 주세요.
3. 어떤 상황이었는지 한두 줄과, 가능하면 화면 캡처(**Win+Shift+S**)도 함께 보내 주세요.

## 8. 말씀 데이터 출처

- 번역본: **Berean Standard Bible (BSB)** — 퍼블릭 도메인. 원문 파일 머리말: *"This text of God's Word has been dedicated to the public domain."*
- 원문 파일: <https://bereanbible.com/bsb.txt> — 공식 다운로드 페이지 <https://berean.bible/downloads.htm> 의 "Berean Standard Bible - Text"
  - 받은 날짜: 2026-11-12, SHA-256 `2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96`
- 시편 표제(예: "A Psalm of David.") 처리: bsb.txt 에는 표제가 1절 앞에 붙어 있어서, 공식 USFM 파일 <https://bereanbible.com/bsb_usfm.zip> (SHA-256 `f0c56438eb89c98e8f62c5c00461e25cc35b098ad5b179bc350cede759ee5f87`) 의 `\d` 표시로 표제 문장을 확인하고, 1절이 정확히 그 문장으로 시작할 때만 그 부분을 떼어 냈습니다.
- 본문은 손으로 입력하지 않았습니다. `tools/verse_plan.tsv` (날짜 → 구절 위치 목록)와 `tools/build_verses.py` 가 원문 파일에서 그대로 복사해 `versedesk/data/verses.json` 을 만듭니다. 여러 절은 공백 하나로 이어 붙였습니다.
- 구절 선정: 묵상과 암송에 널리 쓰이는 1~3절 분량의 구절, 366일(2월 29일 포함) 모두 서로 다른 구절.

## 9. 바탕화면 고정이 이상할 때 (고급)

말씀이 아예 안 보이거나, Win+D 때 사라지거나, 다른 창 위로 올라온다면:

1. `settings.json` 의 `"debug_log": false` 를 `true` 로 바꾸고, 트레이 → 종료 → 다시 실행한 뒤 문제가 생기는 동작(예: Win+D)을 한 번 해 보세요. 그다음 `log.txt` 를 보내 주세요(7번). 확인이 끝나면 다시 `false` 로 돌려 두세요.
2. 시험 삼아 `settings.json` 의 `"desktop_mode": "bottom"` 을 `"desktop_mode": "owner"` 로 바꾸고, 트레이 → 종료 → 다시 실행해 보세요(다른 고정 방식). 결과를 알려 주시면 원인을 좁히는 데 도움이 됩니다. 원래대로 하려면 `"bottom"` 으로 되돌리면 됩니다.

---

## 개발자용 메모

```
versedesk/
  main.py            시작점: 로그, 중복 실행 방지, QApplication
  app.py             전체 연결(설정·말씀·위젯·트레이·타이머)
  settings.py        settings.json 읽기/검증/원자적 저장/외부 편집 감지 (Qt 없음)
  verses.py          날짜별 구절 선택, 사용자 verses.json 덮어쓰기 (Qt 없음)
  geometry.py        화면 밖 위치 보정, 기본 위치 계산 (Qt 없음)
  daywatch.py        자정·절전 복귀 날짜 변경 감지
  autostart.py       HKCU Run + StartupApproved
  single_instance.py 중복 실행 방지(명명된 뮤텍스)
  desktop_layer.py   바탕화면 고정 인터페이스(윈도우 외에서는 빈 구현)
  win32/api.py       ctypes 선언
  win32/desktop.py   바탕화면 고정 구현(Rainmeter 방식: z-order 거부 + 바탕화면 바로 위 유지)
  ui/verse_widget.py 말씀 위젯, ui/tray.py 트레이 메뉴, ui/icon.py 아이콘
  data/verses.json   내장 366일 구절(tools/build_verses.py 로 생성)
tools/   bsb.py(원문 조회) build_verses.py verse_plan.tsv make_icon.py write_build_info.py ci_desktop_check.py
tests/   pytest (리눅스에서는 QT_QPA_PLATFORM=offscreen)
```

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m PyInstaller --noconfirm --clean VerseDesk.spec   # Windows에서 dist/VerseDesk.exe
```

GitHub Actions(`.github/workflows/build.yml`)가 push마다 Windows에서 테스트 → exe 빌드 → 실제 바탕화면 동작 점검(`tools/ci_desktop_check.py`, 스크린샷 포함)을 하고, main에 반영되면 Release를 만듭니다.
