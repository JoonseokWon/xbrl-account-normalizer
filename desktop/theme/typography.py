"""Select a readable Korean UI font without redistributing Windows fonts."""
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from application.paths import resources
from .tokens import COLORS, TYPE


def configure_typography(app):
    available = set(QFontDatabase.families())
    native = ('Malgun Gothic', '맑은 고딕') if sys.platform == 'win32' else ()
    family = next((name for name in native if name in available), None)
    if family is None:
        font_id = QFontDatabase.addApplicationFont(str(resources() / 'assets/fonts/NotoSansKR.ttf'))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        family = families[0] if families else app.font().family()
    font = QFont(family)
    font.setPointSizeF(TYPE['body'])
    font.setWeight(QFont.Weight.Normal)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS['placeholder']))
    app.setPalette(palette)
    return family
