"""Шрифты для живого 3D-текста в редакторе (B61, docs/EDITOR.md).

Берёт шрифты Liberation — те же, которыми OpenSCAD наносит надпись на сервере
(api/app/scad/emboss.scad), — и делает из них typeface-JSON для three.js
(FontLoader + TextGeometry). Оставляем только латиницу, кириллицу, цифры и знаки
препинания — так файл в 3–4 раза меньше полного шрифта.

Запуск (нужен fontTools: pip install fonttools; шрифты: apt install fonts-liberation):
    python web/scripts/make_typefaces.py
Результат: web/public/fonts/typeface/liberation-<sans|serif|mono>-<regular|bold>.json

Масштаб как у three.js TTFLoader: 1 em = 100000 / 72 единиц при resolution 1000,
то есть надпись size мм имеет em = size / 0,72 мм — тот же размер, что у text(size=…)
в OpenSCAD (FreeType при 100 dpi), поэтому ширина надписи в окне совпадает с сервером.
"""

import json
import sys
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

SRC = Path("/usr/share/fonts/truetype/liberation")
OUT = Path(__file__).resolve().parent.parent / "public" / "fonts" / "typeface"

# Какие символы оставить: ASCII, «»°±№, кириллица, тире/кавычки/многоточие, ₽.
RANGES = [(0x20, 0x7E), (0xA0, 0xFF), (0x400, 0x45F), (0x2010, 0x2026), (0x2116, 0x2116), (0x20BD, 0x20BD)]


class OutlinePen(BasePen):
    """Записывает контур глифа командами typeface-JSON: m x y, l x y, q x y cx cy, z."""

    def __init__(self, glyph_set, scale):
        super().__init__(glyph_set)
        self.scale = scale
        self.parts = []

    def _n(self, v):
        return str(round(v * self.scale))

    def _moveTo(self, p):
        self.parts += ["m", self._n(p[0]), self._n(p[1])]

    def _lineTo(self, p):
        self.parts += ["l", self._n(p[0]), self._n(p[1])]

    def _qCurveToOne(self, c, p):
        # В typeface-JSON сначала конечная точка, потом контрольная (так читает FontLoader).
        self.parts += ["q", self._n(p[0]), self._n(p[1]), self._n(c[0]), self._n(c[1])]

    def _curveToOne(self, c1, c2, p):
        self.parts += ["b", self._n(p[0]), self._n(p[1]), self._n(c1[0]), self._n(c1[1]), self._n(c2[0]), self._n(c2[1])]

    def _closePath(self):
        self.parts.append("z")


def convert(ttf: Path) -> dict:
    font = TTFont(ttf)
    em = font["head"].unitsPerEm
    scale = 100000 / (em * 72)
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    hmtx = font["hmtx"]
    glyphs = {}
    for lo, hi in RANGES:
        for code in range(lo, hi + 1):
            name = cmap.get(code)
            if name is None:
                continue
            pen = OutlinePen(glyph_set, scale)
            glyph_set[name].draw(pen)
            glyphs[chr(code)] = {"ha": round(hmtx[name][0] * scale), "o": " ".join(pen.parts)}
    head, post, hhea = font["head"], font["post"], font["hhea"]
    s = lambda v: round(v * scale)  # noqa: E731
    return {
        "glyphs": glyphs,
        "familyName": font["name"].getDebugName(1),
        "ascender": s(hhea.ascent),
        "descender": s(hhea.descent),
        "underlinePosition": s(post.underlinePosition),
        "underlineThickness": s(post.underlineThickness),
        "boundingBox": {"xMin": s(head.xMin), "yMin": s(head.yMin), "xMax": s(head.xMax), "yMax": s(head.yMax)},
        "resolution": 1000,
        "original_font_information": {"license": "SIL Open Font License 1.1 (Liberation Fonts)"},
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for family in ("Sans", "Serif", "Mono"):
        for style in ("Regular", "Bold"):
            src = SRC / f"Liberation{family}-{style}.ttf"
            if not src.exists():
                print(f"нет файла {src} — поставьте fonts-liberation", file=sys.stderr)
                return 1
            dst = OUT / f"liberation-{family.lower()}-{style.lower()}.json"
            dst.write_text(json.dumps(convert(src), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(dst.name, dst.stat().st_size // 1024, "КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
