# snaplab

가볍지만 강력한 화면 캡처 도구. Windows 및 macOS 지원.

## 주요 기능

- **영역 캡처** — 화면을 얼린 뒤 드래그로 정확한 영역 선택
- **전체 화면** — 다중 모니터 포함 전체 캡처
- **활성 창 캡처** — 창 경계에 정확히 맞춤 (Windows DWM 사용)
- **브라우저 스크롤 캡처** — Chrome / Edge 의 전체 페이지를 한 번에 (DevTools Protocol)
- **편집기** — 사각형 / 원 / 화살표 / 펜 / 형광펜 / 텍스트 / 모자이크
- **OCR** — Tesseract로 이미지에서 한국어/영어 텍스트 추출
- **컬러 피커** — 화면 어디서든 픽셀 색상 추출 (HEX 자동 복사)
- **핀** — 캡처를 화면 위에 띄워두기 (휠로 확대, 드래그로 이동)
- **딜레이 캡처** — 카운트다운 후 캡처 (메뉴 펼친 상태 캡처용)
- **히스토리** — 모든 캡처 자동 보관 (개수 설정 가능)
- **글로벌 단축키 + 시스템 트레이 + 자동 시작** (모두 옵션에서 변경 가능)

## 기본 단축키

| 동작 | Windows / Linux | macOS |
|---|---|---|
| 영역 캡처 | `Ctrl + Shift + A` | `Cmd + Shift + A` |
| 전체 화면 | `Ctrl + Shift + S` | `Cmd + Shift + S` |
| 활성 창 | `Ctrl + Shift + W` | `Cmd + Shift + W` |
| 브라우저 스크롤 | `Ctrl + Shift + L` | `Cmd + Shift + L` |
| 컬러 피커 | `Ctrl + Shift + C` | `Cmd + Shift + C` |
| 딜레이 캡처 | `Ctrl + Shift + D` | `Cmd + Shift + D` |

전부 설정 창에서 변경 가능합니다.

## 설치 (개발자 모드)

```bash
# 1) 가상환경
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2) 의존성
pip install -r requirements.txt

# 3) 실행
python -m snaplab
```

## 실행 파일 빌드

```bash
pip install pyinstaller
python build.py
# 결과물: dist/snaplab.exe (Windows) / dist/snaplab (macOS, Linux)
```

빌드 시 `assets/logo.ico` (Windows) 또는 `assets/logo.icns` (macOS) 가 있으면 실행파일 아이콘으로 자동 사용됩니다.

## 브라우저 스크롤 캡처 사용법

평소 사용하는 Chrome/Edge와 별개로, 디버그 포트가 켜진 인스턴스를 띄워야 합니다.
설정 > **브라우저 캡처** 탭에 명령어가 있습니다. 기본 포트는 9222입니다.

**Windows 예시 — 바로가기를 만들고 "대상" 필드에:**
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\snaplab\chrome"
```

**macOS:**
```
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/snaplab/chrome"
```

별도 `user-data-dir`을 사용하면 평소 프로필이 잠기지 않고 분리되어 안전합니다.

## OCR 사용을 위한 Tesseract 설치 (선택)

- **Windows**: https://github.com/UB-Mannheim/tesseract/wiki — 설치 시 Korean 언어팩 체크
- **macOS**: `brew install tesseract tesseract-lang`

설치 후 설정의 `ocr_languages`를 원하는 언어 코드로 변경 (`eng+kor`, `eng`, 등).

## 데이터 위치

| 항목 | Windows | macOS |
|---|---|---|
| 설정 파일 | `%APPDATA%\snaplab\settings.json` | `~/Library/Application Support/snaplab/settings.json` |
| 히스토리 | `%APPDATA%\snaplab\history\` | `~/Library/Application Support/snaplab/history/` |
| 기본 저장 폴더 | `%USERPROFILE%\Pictures\snaplab\` | `~/Pictures/snaplab/` |

## 폴더 구조

```
snaplab/
├── assets/                  # 로고/아이콘 (logo.png, logo.ico, logo.icns)
├── src/snaplab/
│   ├── app.py               # 애플리케이션 오케스트레이션
│   ├── tray.py              # 시스템 트레이
│   ├── hotkeys.py           # 글로벌 단축키
│   ├── settings.py          # 설정 저장/로드
│   ├── autostart.py         # 자동 시작 (cross-platform)
│   ├── paths.py             # 경로 헬퍼
│   ├── capture/
│   │   ├── screen.py        # mss 기반 grab
│   │   ├── area.py          # 영역 선택 오버레이
│   │   ├── fullscreen.py    # 전체 화면
│   │   ├── window.py        # 활성 창
│   │   └── scroll.py        # CDP 기반 전체 페이지
│   ├── editor/
│   │   ├── canvas.py        # 어노테이션 캔버스
│   │   └── window.py        # 편집기 메인 창
│   ├── features/
│   │   ├── color_picker.py
│   │   ├── ocr.py
│   │   ├── pin.py
│   │   ├── history.py
│   │   └── delay.py
│   ├── ui/
│   │   ├── settings_window.py
│   │   └── hotkey_edit.py
│   └── utils/
│       ├── image.py
│       └── clipboard.py
├── requirements.txt
├── pyproject.toml
└── build.py
```

## 라이선스

내부 개인 사용 — 자유롭게 수정 / 배포.
