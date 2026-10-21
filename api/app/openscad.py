"""Запуск OpenSCAD из командной строки (B21).

OpenSCAD — «программа вместо чертежа»: файл `model.scad` описывает деталь кодом, а числа
в начале файла (диаметр, высота, …) можно переопределить снаружи ключом `-D имя=значение`.
Так один scad-файл становится редактором: клиент меняет параметры в форме, мы строим STL.

Команда, которую собираем:
    openscad -o out.stl --export-format binstl -D outer_d=20 -D text="abc" model.scad

Сам OpenSCAD стоит только в контейнере worker (worker/Dockerfile).
В тестах вместо него — tests/fake_openscad.py, который пишет коробку такими же аргументами.
"""

import math
import re
import shlex
import subprocess
from pathlib import Path

from app.config import settings


class OpenScadError(RuntimeError):
    """OpenSCAD не отработал: нет бинарника, ошибка в параметрах или в самом scad-файле."""


def scad_literal(value: object) -> str:
    """Значение параметра → как его записать в OpenSCAD после `-D имя=`.

    bool → true/false, числа — как есть, строка — в кавычках с экранированием.
    Важно для безопасности: клиент не может «дописать код», потому что строка всегда
    попадает внутрь кавычек, а кавычки и обратные слэши внутри неё экранируются.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OpenScadError("Число должно быть конечным.")
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "")
        )
        return f'"{escaped}"'
    raise OpenScadError(f"Не умею передать в OpenSCAD значение типа {type(value).__name__}.")


def build_command(scad_path: Path, stl_path: Path, params: dict) -> list[str]:
    """Аргументы для OpenSCAD. Отдельная функция — чтобы её проверял тест."""
    cmd = shlex.split(settings.openscad_bin)
    cmd += ["-o", str(stl_path), "--export-format", "binstl"]
    for name, value in params.items():
        cmd += ["-D", f"{name}={scad_literal(value)}"]
    cmd.append(str(scad_path))
    return cmd


EMPTY_MESSAGE = "Модель получилась пустой — проверьте параметры."
_FILE_TAIL = re.compile(r"\s+in file .*?, line \d+")  # «… in file /srv/editors/x.scad, line 7»


def error_text(output: str) -> str:
    """Из вывода OpenSCAD — понятная строка: ERROR-строки без путей к файлам, пустая модель
    своим текстом, иначе последние строки вывода."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    errors = [_FILE_TAIL.sub("", ln) for ln in lines if ln.startswith("ERROR")]
    if errors:
        return " | ".join(errors)[:500]
    if any("top level object is empty" in ln for ln in lines):
        return EMPTY_MESSAGE
    return " | ".join(lines[-3:])[:500]


def run_openscad(scad_path: Path, stl_path: Path, params: dict) -> str:
    """Строит STL. Возвращает вывод OpenSCAD (предупреждения — пригодятся при отладке)."""
    if not scad_path.is_file():
        raise OpenScadError(f"Нет файла модели: {scad_path}")
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(scad_path, stl_path, params)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.openscad_timeout_s,
            check=False,
        )
    except FileNotFoundError as e:
        raise OpenScadError(
            f"Не найден OpenSCAD: {cmd[0]}. Проверь OPENSCAD_BIN или запусти worker."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise OpenScadError(f"OpenSCAD не уложился в {settings.openscad_timeout_s} с.") from e

    output = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0 or not stl_path.is_file():
        text = error_text(output)
        prefix = "" if text == EMPTY_MESSAGE else "OpenSCAD завершился с ошибкой: "
        raise OpenScadError(prefix + text)
    if stl_path.stat().st_size < 84 + 50:  # заголовок binary STL + хотя бы один треугольник
        raise OpenScadError(EMPTY_MESSAGE)
    return output
