// Табличка / бирка с текстом (B24). Параметры ниже переопределяет сервер: openscad -D text="…" ...
// Все размеры в мм. Табличка лежит на столе: длина по X, высота по Y, толщина по Z.
// Левый нижний угол — в начале координат.

text = "ТУЦ";           // надпись (первая строка)
text2 = "";             // вторая строка, "" — её нет
font_size = 10;         // размер шрифта = высота заглавной буквы
font = "sans";          // "sans" | "serif" | "mono"
bold = true;            // жирное начертание
style = "raised";       // "raised" — выпуклый текст, "engraved" — углублённый
text_h = 1;             // высота выпуклого / глубина углублённого текста
thickness = 2;          // толщина основания
width = 0;              // ширина таблички, 0 — по тексту
height = 0;             // высота таблички, 0 — по тексту
margin = 4;             // поля между текстом и краем
corner_r = 3;           // скругление углов
frame = false;          // выпуклая рамка по периметру
hole = "none";          // "none" | "left" | "both"
hole_d = 4;             // диаметр отверстий

$fn = 48;               // гладкость окружностей
eps = 0.01;             // небольшой запас, чтобы вырезы выходили за край детали

// --- шрифт -------------------------------------------------------------------------------
// Шрифты Liberation стоят в worker (fonts-liberation); в них есть кириллица.
// Если шрифта нет, OpenSCAD подставит похожий и напишет предупреждение — модель построится.
family = font == "serif" ? "Liberation Serif" : font == "mono" ? "Liberation Mono" : "Liberation Sans";
font_spec = str(family, ":style=", bold ? "Bold" : "Regular");

// --- оценка размеров текста --------------------------------------------------------------
// OpenSCAD (версия из Debian) не умеет измерять текст, поэтому ширину строки прикидываем
// по буквам: у каждой — примерная ширина в долях размера шрифта (замерено по Liberation).
// Оценка с небольшим запасом: лучше табличка чуть шире, чем обрезанная буква. На всякий
// случай текст ещё и обрезается по площадке под него (text_clipped) — модель не сломается.
wide_upper = "ШЩЖЮЫФМДWM";          // самые широкие заглавные
wide_lower = "шщжюыфмдmw—";         // широкие строчные и длинное тире
narrow = " iljtfIі!.,:;'|-()[]";    // узкие знаки и пробел
descenders = "gjpqyдруфцщ,;";       // то, что свешивается под базовую линию
function is_in(ch, set) = len(search(ch, set)) > 0;
function is_upper(ch) = (ch >= "A" && ch <= "Z") || (ch >= "А" && ch <= "Я") || ch == "Ё";
function char_k(ch) =
    font == "mono" ? 0.82
    : is_in(ch, wide_upper) ? (font == "serif" ? 1.45 : 1.3)
    : is_in(ch, wide_lower) ? 1.1
    : is_in(ch, narrow) ? 0.4
    : is_upper(ch) ? 0.95
    : 0.75;
bold_k = bold ? 1 : 0.92;  // обычное начертание уже жирного
function line_w(s) = len(s) == 0 ? 0 : font_size * bold_k * 1.03 * (
    [for (i = [0 : 1 : len(s) - 1]) char_k(s[i])] * [for (i = [0 : 1 : len(s) - 1]) 1]
);
function has_descender(s) = len([for (i = [0 : 1 : len(s) - 1]) if (is_in(s[i], descenders)) 1]) > 0;

lines = text2 == "" ? [text] : [text, text2];
n_lines = len(lines);
block_w = max([for (s = lines) line_w(s)]);
// По вертикали: над базовой линией — размер шрифта (заглавные и б, й), под ней — хвосты
// у, р, д (0,3 размера), если такие буквы есть. Между строками — просвет 0,25 размера.
ascent = 1.0 * font_size;
function descent(s) = (has_descender(s) ? 0.3 : 0.05) * font_size;
gap = 0.25 * font_size;
line_hs = [for (s = lines) ascent + descent(s)];
block_h = (line_hs * [for (s = lines) 1]) + (n_lines - 1) * gap;
// Базовая линия i-й строки, если верх блока текста — y = 0.
function baseline_y(i) = -(ascent + (i > 0 ? line_hs[0] + gap : 0));

// --- площадка таблички -------------------------------------------------------------------
// Слева/справа от текста — поля; там, где отверстие, вместо поля — место под него
// (диаметр + по 2,5 мм стенки с каждой стороны).
hole_pad = hole_d + 5;
pad_left = hole == "none" ? margin : hole_pad;
pad_right = hole == "both" ? hole_pad : margin;
// Автоматический размер не больше стола принтера (250 × 150 — как максимумы в editor.yaml):
// слишком длинная надпись не растянет табличку, а уменьшится.
max_w = 250;
max_h = 150;
plate_w = width > 0 ? max(width, pad_left + pad_right + 2) : min(max_w, pad_left + block_w + pad_right);
// Площадка под текст: между полями. Текст центрируется в ней; если заданная ширина или
// высота таблички меньше, чем нужно тексту, буквы пропорционально уменьшаются.
area_w = plate_w - pad_left - pad_right;
scale_w = block_w > 0 ? min(1, area_w / block_w) : 1;   // насколько ужать по ширине
// Автоматическая высота — под текст уже ужатый по ширине, чтобы не оставалось пустого места.
plate_h = height > 0 ? max(height, 2 * margin + 2) : min(max_h, 2 * margin + block_h * scale_w);
area_h = plate_h - 2 * margin;
text_scale = min(scale_w, area_h / block_h);
r = min(corner_r, (min(plate_w, plate_h) - 1) / 2);  // скругление не больше половины стороны
area_cx = pad_left + area_w / 2;
area_cy = plate_h / 2;

module rounded_rect(w, h, rr) {
    if (rr > 0)
        offset(r = rr) offset(delta = -rr) square([w, h]);
    else
        square([w, h]);
}

// Контур текста в 2D: строки одна под другой, центр блока — в начале координат.
module text_2d() {
    scale(text_scale)
        translate([0, block_h / 2])
            for (i = [0 : 1 : n_lines - 1])
                translate([0, baseline_y(i)])
                    text(lines[i], size = font_size, font = font_spec, halign = "center", valign = "baseline");
}

// Текст, обрезанный по площадке плюс половина поля (на случай, если оценка промахнулась).
module text_clipped() {
    intersection() {
        translate([area_cx, area_cy]) text_2d();
        translate([pad_left - margin / 2, margin / 2]) square([area_w + margin, area_h + margin]);
    }
}

// --- детали --------------------------------------------------------------------------------
module base() {
    linear_extrude(thickness) rounded_rect(plate_w, plate_h, r);
}

module holes() {
    hd = min(hole_d, plate_h - 4);            // отверстие не шире таблички минус стенки
    if (hole != "none" && hd >= 1) {
        translate([2.5 + hd / 2, plate_h / 2, -eps]) cylinder(d = hd, h = thickness + 2 * eps);
        if (hole == "both")
            translate([plate_w - 2.5 - hd / 2, plate_h / 2, -eps]) cylinder(d = hd, h = thickness + 2 * eps);
    }
}

frame_w = 1.2;  // ширина рамки

module frame_3d() {
    translate([0, 0, thickness - eps])
        linear_extrude(text_h + eps)
            difference() {
                rounded_rect(plate_w, plate_h, r);
                translate([frame_w, frame_w]) rounded_rect(plate_w - 2 * frame_w, plate_h - 2 * frame_w, max(r - frame_w, 0));
            }
}

// --- сборка ------------------------------------------------------------------------------
difference() {
    union() {
        base();
        if (style == "raised")
            translate([0, 0, thickness - eps]) linear_extrude(text_h + eps) text_clipped();
        if (frame) frame_3d();
    }
    if (style == "engraved")
        translate([0, 0, thickness - text_h]) linear_extrude(text_h + eps) text_clipped();
    holes();
}
