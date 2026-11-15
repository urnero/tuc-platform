// Надпись, логотип или текстура для тиснения на загруженной модели (B30, B68).
//
// Этот файл строит ТОЛЬКО само тиснение — плоскую фигуру (текст, SVG или участок
// повторяющегося узора), вытянутую
// в толщину. Фигура лежит в плоскости XY, центр — в начале координат, «лицом» вверх (+Z).
// Сервер (app/emboss.py) поворачивает её на нужную грань модели и соединяет с моделью:
// выпуклую — прибавляет, углублённую — вырезает. Параметры переопределяет сервер:
//     openscad -D kind="text" -D text="ТУЦ" -D size_mm=10 ... emboss.scad

kind = "text";          // "text" — надпись, "logo" — картинка из файла logo_file (SVG),
                        // "pattern" — текстура: узор pattern на квадрате со стороной size_mm (B68)
text = "ТУЦ";           // надпись
font = "sans";          // "sans" | "serif" | "mono"
bold = true;            // жирное начертание
size_mm = 10;           // текст: размер шрифта (высота заглавной буквы); логотип: ширина;
                        // текстура: сторона квадратного участка
depth_mm = 1;           // высота выпуклого / глубина углублённого тиснения
style = "raised";       // "raised" — выпуклое, "engraved" — углублённое
logo_file = "";         // путь к SVG, когда kind = "logo"
angle = 0;              // поворот фигуры в её плоскости, градусы (против часовой стрелки)
pattern = "lines";      // текстура: "lines" — полосы, "grid" — сетка, "dots" — точки, "hex" — соты
pitch_mm = 3;           // текстура: шаг узора (расстояние между повторами), мм

// Запас, на который фигура заходит внутрь модели (выпуклая) или выступает над ней
// (углублённая): так тиснение точно сцепляется с поверхностью, даже если она не идеально
// ровная или сетка загружена с мелкой погрешностью. На изогнутой поверхности API передаёт
// -D overlap=<глубина надписи> (B64a), чтобы края букв не повисли в воздухе.
overlap = 0.3;

$fn = 32;

// Шрифты Liberation стоят в worker (fonts-liberation) — в них есть кириллица.
family = font == "serif" ? "Liberation Serif" : font == "mono" ? "Liberation Mono" : "Liberation Sans";
font_spec = str(family, ":style=", bold ? "Bold" : "Regular");

// --- текстура (B68) ------------------------------------------------------------------
// Узор — бесконечно повторяющаяся плоская фигура, заполняющая примерно половину площади:
// полосы и прутья сетки шириной в половину шага, точки и соты — тоже около половины.
// Так выпуклая и врезанная версии одного узора выглядят одинаково «плотно», а печатаются
// без тонких элементов: при шаге 2 мм прут 1 мм — это 2–3 линии сопла 0,4 мм.
// Участок — квадрат size_mm, узор обрезается по нему (intersection), края ровные.
half = size_mm / 2;
n = ceil(half / pitch_mm) + 1;            // сколько повторов нужно от центра до края

module stripes() {                        // полосы вдоль Y с шагом pitch_mm
    for (i = [-n : n])
        translate([i * pitch_mm - pitch_mm / 4, -half - pitch_mm, 0])
            square([pitch_mm / 2, size_mm + 2 * pitch_mm]);
}

module pattern2d() {
    if (pattern == "lines") {
        stripes();
    } else if (pattern == "grid") {
        stripes();
        rotate([0, 0, 90]) stripes();
    } else if (pattern == "dots") {
        // Точки диаметром 0,75 шага на квадратной решётке
        for (i = [-n : n], j = [-n : n])
            translate([i * pitch_mm, j * pitch_mm, 0]) circle(d = pitch_mm * 0.75, $fn = 24);
    } else if (pattern == "hex") {
        // Соты: шестиугольники на треугольной решётке (соседи в ряду — на расстоянии
        // шага, ряды через шаг·√3/2, нечётные сдвинуты на полшага), зазор между сотами —
        // четверть шага. Поворот на 30° ставит соты плоской стороной к соседу по ряду.
        row_h = pitch_mm * sqrt(3) / 2;
        rows = ceil(half / row_h) + 1;
        for (j = [-rows : rows], i = [-n - 1 : n + 1])
            translate([i * pitch_mm + (j % 2 == 0 ? 0 : pitch_mm / 2), j * row_h, 0])
                rotate([0, 0, 30]) circle(d = pitch_mm * 0.75 / cos(30), $fn = 6);
    }
}

module shape2d() {
    if (kind == "pattern") {
        intersection() {
            square(size_mm, center = true);
            pattern2d();
        }
    } else if (kind == "logo") {
        // SVG приводим к ширине size_mm, пропорции сохраняем (auto=true).
        resize([size_mm, 0], auto = true) import(logo_file, center = true);
    } else {
        text(text, size = size_mm, font = font_spec, halign = "center", valign = "center");
    }
}

// Выпуклое: от -overlap (внутри модели) до +depth_mm над поверхностью.
// Углублённое: от -depth_mm (в глубину) до +overlap (чуть выше поверхности, чтобы вырез
// наверняка прошёл сквозь грань).
z0 = style == "engraved" ? -depth_mm : -overlap;
translate([0, 0, z0])
    linear_extrude(height = depth_mm + overlap)
        rotate([0, 0, angle])
            shape2d();
