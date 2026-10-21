// Втулка / проставка (B21). Параметры ниже переопределяет сервер: openscad -D outer_d=20 ...
// Все размеры в мм. Модель стоит на столе (z от 0 до height).

outer_d = 20;      // внешний диаметр (для шестигранника — размер под ключ)
inner_d = 8.5;     // диаметр отверстия
height = 10;       // высота
shape = "round";   // "round" | "hex"
chamfer = true;    // фаска 0.8 мм по верхней и нижней кромке

$fn = 96;          // гладкость окружностей

// Фаска не больше трети стенки и не выше трети высоты — иначе деталь «съедена» целиком.
wall = (outer_d - inner_d) / 2;
ch = chamfer ? min(0.8, wall / 3, height / 3) : 0;

// Внешнее тело: цилиндр или шестигранная призма с фасками (через hull двух сечений).
module body() {
    if (shape == "hex") {
        // Шестигранник задаём размером под ключ: диаметр описанной окружности = s / cos(30°).
        d_corner = outer_d / cos(30);
        hull() {
            translate([0, 0, ch]) cylinder(d = d_corner, h = height - 2 * ch, $fn = 6);
            cylinder(d = (outer_d - 2 * ch) / cos(30), h = height, $fn = 6);
        }
    } else {
        hull() {
            translate([0, 0, ch]) cylinder(d = outer_d, h = height - 2 * ch);
            cylinder(d = outer_d - 2 * ch, h = height);
        }
    }
}

difference() {
    body();
    // Отверстие чуть длиннее детали, чтобы не осталось плёнки на торцах.
    translate([0, 0, -1]) cylinder(d = inner_d, h = height + 2);
}
