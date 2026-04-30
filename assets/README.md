# Assets

이 폴더에 로고/아이콘 파일을 넣어주세요. 앱이 자동으로 로드합니다.

## 권장 파일

| 파일명 | 용도 | 권장 크기 / 포맷 |
|---|---|---|
| `logo.png` | 트레이 아이콘, 윈도우 아이콘 (런타임) | 256x256 PNG (투명 배경 권장) |
| `logo.ico` | Windows 설치 파일 / 실행파일 아이콘 | multi-size .ico (16, 32, 48, 64, 128, 256) |
| `logo.icns` | macOS 앱 번들 아이콘 | .icns (1024x1024 base) |
| `logo@2x.png` | (선택) HiDPI 트레이 아이콘 | 512x512 PNG |

## 변환 팁

- PNG → ICO (Windows): `pillow`로 변환 가능. 또는 https://icoconvert.com
- PNG → ICNS (macOS): `iconutil` (macOS 내장) 또는 https://cloudconvert.com/png-to-icns

## 동작 방식

- 런타임에 시스템 트레이 아이콘은 `logo.png` (없으면 `logo.ico`) 를 사용합니다.
- 빌드 시 `build.py`가 `logo.ico` (Windows), `logo.icns` (macOS) 를 패키징해서 설치 아이콘으로 사용합니다.
- 파일이 없으면 기본 Qt 시스템 아이콘으로 폴백되니 미리 넣지 않아도 앱은 동작합니다.
