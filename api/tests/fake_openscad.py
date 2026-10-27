#!/usr/bin/env python3
"""Подделка OpenSCAD для тестов: принимает те же аргументы и пишет STL-коробку.

    fake_openscad.py -o out.stl --export-format binstl -D w=20 -D h=5 ... model.scad

Размеры коробки — из параметров w, d, h (если переданы), иначе 10 мм. Какие параметры
пришли — записывает рядом в <out>.params.json, чтобы тест проверил строку -D.
Если в scad-файле есть слово BROKEN — падает, как настоящий OpenSCAD на ошибке синтаксиса.
Если передан параметр empty=true — «пустая модель» (так OpenSCAD ведёт себя при h = 0).
"""

import json
import sys
from pathlib import Path

import trimesh


def main(argv: list[str]) -> int:
    args = argv[1:]
    out = Path(args[args.index("-o") + 1])
    scad = Path(args[-1])
    params: dict[str, str] = {}
    for i, a in enumerate(args):
        if a == "-D":
            name, value = args[i + 1].split("=", 1)
            params[name] = value

    if not scad.is_file():
        print(f"ERROR: Can't open input file '{scad}'!", file=sys.stderr)
        return 1
    if "BROKEN" in scad.read_text("utf-8"):
        print(f"ERROR: Parser error: syntax error in file {scad}, line 3", file=sys.stderr)
        print(f"Can't parse file '{scad}'!", file=sys.stderr)
        return 1
    if params.get("empty") == "true":
        print("Current top level object is empty.", file=sys.stderr)
        return 1

    def num(name: str, fallback: float) -> float:
        try:
            return float(params[name])
        except (KeyError, ValueError):
            return fallback

    box = trimesh.creation.box(extents=(num("w", 10), num("d", 10), num("h", 10)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(box.export(file_type="stl"))
    Path(str(out) + ".params.json").write_text(json.dumps(params), "utf-8")
    print("Geometries in cache: 1")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
