// Надпись или логотип для тиснения на загруженной модели (B30).
//
// Этот файл строит ТОЛЬКО само тиснение — плоскую фигуру (текст или SVG), вытянутую
// в толщину. Фигура лежит в плоскости XY, центр — в начале координат, «лицом» вверх (+Z).
// Сервер (app/emboss.py) поворачивает её на нужную грань модели и соединяет с моделью:
// выпуклую — прибавляет, углублённую — вырезает. Параметры переопределяет сервер:
//     openscad -D kind="text" -D text="ТУЦ" -D size_mm=10 ... emboss.scad

kind = "text";          // "text" — надпись, "logo" — картинка из файла logo_file (SVG)
text = "ТУЦ";           // надпись
font = "sans";          // "sans" | "serif" | "mono"
bold = true;            // жирное начертание
size_mm = 10;           // текст: размер шрифта (высота заглавной буквы); логотип: ширина
depth_mm = 1;           // высота выпуклого / глубина углублённого тиснения
style = "raised";       // "raised" — выпуклое, "engraved" — углублённое
logo_file = "";         // путь к SVG, когда kind = "logo"
angle = 0;              // поворот фигуры в её плоскости, градусы (против часовой стрелки)

// Запас, на который фигура заходит внутрь модели (выпуклая) или выступает над ней
// (углублённая): так тиснение точно сцепляется с поверхностью, даже если она не идеально
// ровная или сетка загружена с мелкой погрешностью.
overlap = 0.3;

$fn = 32;

// Шрифты Liberation стоят в worker (fonts-liberation) — в них есть кириллица.
family = font == "serif" ? "Liberation Serif" : font == "mono" ? "Liberation Mono" : "Liberation Sans";
font_spec = str(family, ":style=", bold ? "Bold" : "Regular");

module shape2d() {
    if (kind == "logo") {
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
