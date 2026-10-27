// Кронштейн / уголок (B22). Параметры ниже переопределяет сервер: openscad -D length_a=50 ...
// Все размеры в мм. Полка A лежит на столе (вдоль X), полка B стоит вертикально (вдоль Z),
// наружный угол — в начале координат. Ширина — по Y.

length_a = 50;          // длина горизонтальной полки A
length_b = 50;          // длина вертикальной полки B
width = 25;             // ширина уголка
thickness = 4;          // толщина полок
hole_d = 4.5;           // диаметр отверстий
holes_a = 2;            // отверстий в полке A (0..4)
holes_b = 2;            // отверстий в полке B (0..4)
hole_type = "plain";    // "plain" | "countersunk" (потай с внутренней стороны)
rib = true;             // косынки по бокам
rounded = true;         // скруглить свободные концы полок

$fn = 64;               // гладкость окружностей
eps = 0.01;             // небольшой запас, чтобы вырезы выходили за край детали

// --- отверстия ---------------------------------------------------------------------------
// Ряд по середине ширины. От свободного конца и от внутреннего угла отступаем на диаметр,
// между центрами — не меньше двух диаметров. Если столько отверстий не помещается,
// лишние пропускаем (подсказка в форме об этом предупреждает).
function hole_span(len) = len - thickness - 2 * hole_d;
function holes_fit(len, n) =
    n <= 0 ? 0
    : len - thickness < 1.5 * hole_d ? 0              // даже одно не влезает
    : n == 1 || hole_span(len) < 2 * hole_d ? 1       // место только для одного
    : min(n, floor(hole_span(len) / (2 * hole_d)) + 1);
// Координата i-го центра вдоль полки (отсчёт от наружного угла).
function hole_pos(len, n, i) =
    n == 1 ? thickness + (len - thickness) / 2
    : thickness + hole_d + i * hole_span(len) / (n - 1);

// Глубина потая: конус 90° (ширина головки = 2 диаметра), но не глубже 60% толщины,
// чтобы под головкой осталась опора.
sink_h = hole_type == "countersunk" ? min(hole_d / 2, thickness * 0.6) : 0;

// Одно отверстие вдоль Z, ось в начале координат, от z = -eps до thickness + eps.
// Потай — у верхней (внутренней) кромки.
module hole() {
    translate([0, 0, -eps]) cylinder(d = hole_d, h = thickness + 2 * eps);
    if (sink_h > 0)
        translate([0, 0, thickness - sink_h])
            cylinder(d1 = hole_d, d2 = hole_d + 2 * sink_h, h = sink_h + eps);
}

// --- полки -------------------------------------------------------------------------------
// Полка в плоскости XY: прямоугольник length × width × thickness, свободный конец
// (x = length) при rounded — со скруглёнными углами.
module leg_flat(len) {
    r = rounded ? min(5, width / 3, (len - thickness) / 2) : 0;
    if (r > 0) {
        hull() {
            cube([len - r, width, thickness]);
            translate([len - r, r, 0]) cylinder(r = r, h = thickness);
            translate([len - r, width - r, 0]) cylinder(r = r, h = thickness);
        }
    } else {
        cube([len, width, thickness]);
    }
}

// Полка с рядом отверстий (та же система координат, что у leg_flat).
module leg(len, n) {
    k = holes_fit(len, n);
    difference() {
        leg_flat(len);
        for (i = [0 : 1 : k - 1])
            translate([hole_pos(len, k, i), width / 2, 0]) hole();
    }
}

// --- косынки -----------------------------------------------------------------------------
// Треугольники в плоскости XZ во внутреннем углу, по одному у каждого бока.
// Толщина ребра — как у полок, но ребра не должны залезать на ряд отверстий:
// между ними оставляем hole_d + 2 мм. Длина катетов — 60% короткой полки.
rib_t = min(thickness, (width - hole_d - 2) / 2);
rib_len = 0.6 * (min(length_a, length_b) - thickness);

module gusset() {
    // Вершина чуть утоплена в угол, чтобы ребро срослось с полками без щели.
    t = thickness;
    rotate([90, 0, 0])
        linear_extrude(rib_t)
            polygon([[t - 1, t - 1], [t + rib_len, t - 1], [t - 1, t + rib_len]]);
}

module gussets() {
    if (rib && rib_t >= 1 && rib_len >= 3) {
        translate([0, rib_t, 0]) gusset();         // у бока y = 0
        translate([0, width, 0]) gusset();         // у бока y = width
    }
}

// --- сборка ------------------------------------------------------------------------------
union() {
    leg(length_a, holes_a);                                  // полка A — на столе
    // Полка B: та же заготовка, но стоя. mirror([1,0,-1]) меняет местами X и Z:
    // длина уходит вверх, толщина ложится на x от 0 до thickness, потай остаётся
    // с внутренней стороны (x = thickness).
    mirror([1, 0, -1]) leg(length_b, holes_b);
    gussets();
}
