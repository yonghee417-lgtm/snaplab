"""OCR via Tesseract. Optional dependency: surfaces a clear error message if
the binary isn't on PATH so users can install it."""
from __future__ import annotations

from PIL import Image


class OcrError(Exception):
    pass


def extract_text(img: Image.Image, langs: str = "eng") -> str:
    try:
        import pytesseract
    except ImportError as e:
        raise OcrError("pytesseract가 설치되어 있지 않습니다.") from e

    try:
        return pytesseract.image_to_string(img, lang=langs)
    except pytesseract.TesseractNotFoundError:
        raise OcrError(
            "Tesseract 엔진을 찾을 수 없습니다.\n"
            "설치 방법:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki 에서 설치\n"
            "  macOS: brew install tesseract tesseract-lang\n"
            "한국어를 사용하려면 한국어 언어팩(kor.traineddata)도 설치하세요."
        )
    except Exception as e:
        # Often a missing language pack.
        raise OcrError(f"OCR 실패: {e}\n언어 설정({langs})을 확인하거나 언어팩을 설치하세요.")
