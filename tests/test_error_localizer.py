import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import get_language, set_language, tr


class TestErrorLocalizer(unittest.TestCase):
    def setUp(self):
        self._prev_lang = get_language()

    def tearDown(self):
        set_language(self._prev_lang)

    def test_localize_error_by_code_in_english(self):
        set_language("en")
        payload = {
            "error_code": "invalid_date",
            "message": "日期格式无效，请使用 YYYY-MM-DD",
        }
        text = localize_error_payload(payload)
        self.assertEqual("Invalid date format. Use YYYY-MM-DD.", text)

    def test_localize_error_by_code_in_chinese(self):
        set_language("zh-CN")
        payload = {
            "error_code": "invalid_date",
            "message": "Invalid date format. Use YYYY-MM-DD.",
        }
        text = localize_error_payload(payload)
        self.assertEqual("日期格式无效，请使用 YYYY-MM-DD。", text)

    def test_unknown_code_falls_back_to_original_message(self):
        set_language("en")
        payload = {
            "error_code": "custom_error_code",
            "message": "Raw backend message",
        }
        text = localize_error_payload(payload)
        self.assertEqual("Raw backend message", text)

    def test_empty_payload_honors_fallback(self):
        set_language("en")
        text = localize_error_payload({}, fallback="")
        self.assertEqual("", text)

    def test_qt_directwrite_font_warning_is_humanized_in_english(self):
        set_language("en")
        payload = {
            "message": (
                "qt.qpa.fonts: DirectWrite: CreateFontFaceFromHDC() failed "
                "(error in input file, e.g., font file) for "
                'QFontDef(Family="Fixedsys", stylename=Regular, pointsize=11.25, pixelsize=16, '
                "styleHint=5, weight=400, stretch=100, hintingPreference=0) "
                'LOGFONT("Fixedsys", lfWidth=0, lfHeight=-16) dpi=96'
            )
        }
        text = localize_error_payload(payload)
        expected = tr(
            "errors.qtFontFaceFromHdcFailed",
            default=(
                'Font rendering warning: failed to load "{family}" via DirectWrite (DPI {dpi}). '
                "The app will use a fallback font."
            ),
            family="Fixedsys",
            dpi="96",
        )
        self.assertEqual(expected, text)

    def test_qt_directwrite_font_warning_is_humanized_in_chinese(self):
        set_language("zh-CN")
        payload = {
            "message": (
                "qt.qpa.fonts: DirectWrite: CreateFontFaceFromHDC() failed "
                "(error in input file, e.g., font file) for "
                'QFontDef(Family="Fixedsys", stylename=Regular, pointsize=11.25, pixelsize=16, '
                "styleHint=5, weight=400, stretch=100, hintingPreference=0) "
                'LOGFONT("Fixedsys", lfWidth=0, lfHeight=-16) dpi=96'
            )
        }
        text = localize_error_payload(payload)
        expected = tr(
            "errors.qtFontFaceFromHdcFailed",
            default=(
                'Font rendering warning: failed to load "{family}" via DirectWrite (DPI {dpi}). '
                "The app will use a fallback font."
            ),
            family="Fixedsys",
            dpi="96",
        )
        self.assertEqual(expected, text)


if __name__ == "__main__":
    unittest.main()
