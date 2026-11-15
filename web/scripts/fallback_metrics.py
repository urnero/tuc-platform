"""Считает поправки для «запасного» шрифта (B53, CLS).

Пока Manrope/Unbounded грузятся, браузер рисует текст системным шрифтом (Arial/Roboto).
Если он шире или уже — строки переносятся иначе, и после загрузки шрифта страница «прыгает»
(Lighthouse: Cumulative Layout Shift). Поправки size-adjust / ascent-override подгоняют Arial
под размеры нашего шрифта — так же делает next/font. Результат вставляется в app/globals.css.

Запуск (нужны fonttools и brotli):  python web/scripts/fallback_metrics.py
"""

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

WEB = Path(__file__).resolve().parent.parent
# Liberation Sans по размерам совпадает с Arial (так задумано авторами шрифта).
ARIAL = {400: "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         700: "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"}
FONTS = {
    "Manrope Fallback": (WEB / "node_modules/@fontsource-variable/manrope/files/manrope-cyrillic-wght-normal.woff2",
                         WEB / "node_modules/@fontsource-variable/manrope/files/manrope-latin-wght-normal.woff2",
                         400),
    "Unbounded Fallback": (WEB / "node_modules/@fontsource/unbounded/files/unbounded-cyrillic-700-normal.woff2",
                           WEB / "node_modules/@fontsource/unbounded/files/unbounded-latin-700-normal.woff2",
                           700),
}
# Какие системные шрифты брать как запасные: Arial (Windows/macOS), Roboto (Android),
# Liberation Sans (Linux, по размерам = Arial). На iPhone ничего из этого нет — там системный шрифт без поправок.
LOCAL = {400: 'local("Arial"), local("ArialMT"), local("Roboto"), local("Liberation Sans")',
         700: 'local("Arial Bold"), local("Arial-BoldMT"), local("Roboto Bold"), local("Liberation Sans Bold")'}
# Типичный текст сайта: средняя ширина букв считается по нему.
SAMPLE = ("Загрузите модель, выберите материал и получите цену печати за минуту. "
          "Семейная мастерская 3D-печати в Москве. PLA PETG 0.2 mm")


def load(path: Path, weight: int) -> TTFont:
    font = TTFont(path)
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, {"wght": weight})
    return font


def avg_width(fonts: list[TTFont], text: str) -> float:
    """Средняя ширина символа в долях em (берём глиф из первого файла, где он есть)."""
    total = 0.0
    for ch in text:
        for f in fonts:
            name = f.getBestCmap().get(ord(ch))
            if name:
                total += f["hmtx"][name][0] / f["head"].unitsPerEm
                break
    return total / len(text)


def main() -> None:
    for family, (cyr, lat, weight) in FONTS.items():
        ours = [load(cyr, weight), load(lat, weight)]
        arial = [TTFont(ARIAL[weight])]
        size_adjust = avg_width(ours, SAMPLE) / avg_width(arial, SAMPLE)
        hhea, upm = ours[0]["hhea"], ours[0]["head"].unitsPerEm
        asc = hhea.ascent / upm / size_adjust
        desc = abs(hhea.descent) / upm / size_adjust
        gap = hhea.lineGap / upm / size_adjust
        print(f'@font-face {{ font-family: "{family}"; src: {LOCAL[weight]}; '
              f"font-weight: {weight}; size-adjust: {size_adjust:.2%}; ascent-override: {asc:.2%}; "
              f"descent-override: {desc:.2%}; line-gap-override: {gap:.2%}; }}")


if __name__ == "__main__":
    main()
