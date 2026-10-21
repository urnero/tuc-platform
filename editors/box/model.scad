// Коробка / органайзер (B23). Параметры ниже переопределяет сервер: openscad -D length=100 ...
// Все размеры в мм, внешние. Коробка стоит на столе: длина по X, ширина по Y, высота по Z,
// угол коробки — в начале координат. Крышка (если выбрана) лежит рядом, дном вниз.

length = 100;        // длина снаружи
width = 70;          // ширина снаружи
height = 40;         // высота снаружи (без крышки)
wall = 1.6;          // толщина стенок
floor_t = 1.6;       // толщина дна
corner_r = 3;        // скругление вертикальных углов
cells_x = 2;         // ячеек по длине (1 — без перегородок)
cells_y = 1;         // ячеек по ширине
divider = 1.2;       // толщина перегородок
lid = "none";        // "none" | "inset" (бортик внутрь) | "cap" (колпачок снаружи)
lid_gap = 0.3;       // зазор между крышкой и коробкой, на сторону

$fn = 48;            // гладкость скруглений
eps = 0.01;          // небольшой запас, чтобы вырезы выходили за край детали
lip_h = 4;           // высота бортика крышки
min_cell = 5;        // уже этого ячейки не делаем — лишние перегородки пропускаем
lid_space = 10;      // расстояние между коробкой и крышкой на столе

// --- размеры -----------------------------------------------------------------------------
// Скругление не больше, чем позволяет короткая сторона; изнутри радиус меньше на стенку.
r_out = min(corner_r, (min(length, width) - 1) / 2);
r_in = max(r_out - wall, 0);
in_len = length - 2 * wall;      // внутренние размеры
in_wid = width - 2 * wall;

// Сколько ячеек поместится: каждая не уже min_cell.
function cells_fit(inner, n) =
    n <= 1 ? 1 : max(1, min(n, floor((inner + divider) / (divider + min_cell))));
// Координата i-й перегородки (i = 1..n-1) от внутреннего края: ячейки одинаковой ширины.
function div_pos(inner, n, i) = i * (inner - (n - 1) * divider) / n + (i - 1) * divider;

nx = cells_fit(in_len, cells_x);
ny = cells_fit(in_wid, cells_y);

// Под вкладную крышку перегородки ниже верха на бортик и зазор, иначе — вровень с краем.
div_top = height - (lid == "inset" ? lip_h + lid_gap : 0);

// --- заготовки ---------------------------------------------------------------------------
// Прямоугольник l × w со скруглёнными углами радиуса r, угол в начале координат (2D).
module rrect(l, w, r) {
    if (r > 0)
        translate([r, r]) offset(r = r) square([l - 2 * r, w - 2 * r]);
    else
        square([l, w]);
}

// Стакан: прямоугольная «ванна» l × w × h со стенкой t и дном b, угол в начале координат.
module tub(l, w, h, t, b, r) {
    difference() {
        linear_extrude(h) rrect(l, w, r);
        translate([t, t, b])
            linear_extrude(h - b + eps) rrect(l - 2 * t, w - 2 * t, max(r - t, 0));
    }
}

// --- коробка -----------------------------------------------------------------------------
module box() {
    tub(length, width, height, wall, floor_t, r_out);
    // Перегородки: от дна до div_top, слегка утоплены в стенки и дно, чтобы срослись без щелей.
    for (i = [1 : 1 : nx - 1])
        translate([wall + div_pos(in_len, nx, i), wall - eps, floor_t - eps])
            cube([divider, in_wid + 2 * eps, div_top - floor_t + eps]);
    for (j = [1 : 1 : ny - 1])
        translate([wall - eps, wall + div_pos(in_wid, ny, j), floor_t - eps])
            cube([in_len + 2 * eps, divider, div_top - floor_t + eps]);
}

// --- крышка ------------------------------------------------------------------------------
// Вкладная: пластина по размеру коробки и бортик-рамка, который входит внутрь коробки
// с зазором. Печатается пластиной вниз, бортиком вверх; на коробку ставится бортиком вниз.
module lid_inset() {
    lip_l = in_len - 2 * lid_gap;
    lip_w = in_wid - 2 * lid_gap;
    linear_extrude(floor_t) rrect(length, width, r_out);
    translate([wall + lid_gap, wall + lid_gap, floor_t - eps])
        linear_extrude(lip_h + eps) difference() {
            rrect(lip_l, lip_w, max(r_in - lid_gap, 0));
            // Рамка толщиной wall; если места на окно нет — бортик сплошной.
            if (lip_l > 2 * wall + 2 && lip_w > 2 * wall + 2)
                translate([wall, wall]) rrect(lip_l - 2 * wall, lip_w - 2 * wall, max(r_in - lid_gap - wall, 0));
        }
}

// Колпачок: стакан чуть больше коробки (на зазор и стенку), глубиной в бортик.
// Печатается дном вниз, открытой стороной вверх.
cap_l = length + 2 * lid_gap + 2 * wall;
cap_w = width + 2 * lid_gap + 2 * wall;
module lid_cap() {
    tub(cap_l, cap_w, floor_t + lip_h, wall, floor_t, r_out + lid_gap + wall);
}

// Крышка ложится рядом с коробкой: по Y, если коробка не шире, чем длиннее, иначе по X —
// так две детали занимают на столе меньше места.
module lid_part() {
    shift = width <= length ? [0, width + lid_space, 0] : [length + lid_space, 0, 0];
    translate(shift) {
        if (lid == "inset") lid_inset();
        if (lid == "cap") lid_cap();
    }
}

// --- сборка ------------------------------------------------------------------------------
union() {
    box();
    lid_part();
}
