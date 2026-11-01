"""Параметрические редакторы (B21): схема editor.yaml, проверка параметров, команда OpenSCAD,
сборка STL, «Заказать» → загрузка, уборка сборок, настоящие редакторы spacer, bracket, box."""

import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from conftest import REPO_ROOT
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import editors as ed
from app.config import settings
from app.db import get_engine
from app.editors import EditorError, parse_editor, validate_params
from app.models import Event
from app.openscad import EMPTY_MESSAGE, OpenScadError, build_command, error_text, scad_literal

YAML_OK = """
title: Коробка
text: Тестовый редактор со всеми типами параметров.
material: petg
order: 5
params:
  - name: w
    label: Ширина
    type: number
    unit: мм
    min: 5
    max: 100
    step: 0.5
    default: 20
  - name: d
    label: Глубина
    type: number
    min: 5
    max: 100
    default: 10
  - name: h
    label: Высота
    type: number
    min: 1
    max: 50
    integer: true
    default: 10
  - name: lid
    label: Крышка
    type: bool
    default: false
  - name: style
    label: Стиль
    type: choice
    options:
      - { value: plain, label: Гладкая }
      - rounded
    default: plain
  - name: label_text
    label: Надпись
    type: text
    maxlen: 12
    default: ""
checks:
  - rule: d <= w
    message: Глубина не больше ширины.
  - rule: h >= 2
"""

SCAD_OK = (
    'w = 20; d = 10; h = 10; lid = false; style = "plain"; label_text = "";\ncube([w, d, h]);\n'
)


def _write_editor(root, slug, yaml_text=YAML_OK, scad_text=SCAD_OK):
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "editor.yaml").write_text(yaml_text, "utf-8")
    (folder / "model.scad").write_text(scad_text, "utf-8")
    return folder


@pytest.fixture
def editors_dir(tmp_path, monkeypatch, data_dir):
    """Временная папка редакторов: box (все типы), second (порядок), broken-scad."""
    root = tmp_path / "editors"
    _write_editor(root, "box")
    _write_editor(
        root, "second", YAML_OK.replace("order: 5", "order: 1").replace("Коробка", "Вторая")
    )
    _write_editor(root, "bad-scad", scad_text="BROKEN (\n")
    (root / "not-an-editor").mkdir()  # папка без editor.yaml — пропускается
    monkeypatch.setattr(settings, "editors_dir", root)
    ed.reload_editors()
    yield root
    ed.reload_editors()


# --- editor.yaml -----------------------------------------------------------------------


def test_parse_ok():
    editor = parse_editor("box", yaml.safe_load(YAML_OK))
    assert editor.title == "Коробка"
    assert editor.material == "PETG"
    assert [p.name for p in editor.params] == ["w", "d", "h", "lid", "style", "label_text"]
    assert editor.param("style").options == (("plain", "Гладкая"), ("rounded", "rounded"))
    assert editor.param("h").integer is True
    assert editor.defaults() == {
        "w": 20.0,
        "d": 10.0,
        "h": 10,
        "lid": False,
        "style": "plain",
        "label_text": "",
    }
    assert [c.rule for c in editor.checks] == ["d <= w", "h >= 2"]
    assert editor.checks[1].message == "Нужно, чтобы h >= 2"


@pytest.mark.parametrize(
    "patch, text",
    [
        (("title: Коробка", "title: ''"), "title"),
        (("name: w\n", "name: W-1\n"), "имя параметра"),
        (("type: bool", "type: toggle"), "тип"),
        (
            ("min: 5\n    max: 100\n    step: 0.5", "min: 500\n    max: 100\n    step: 0.5"),
            "min больше max",
        ),
        (("step: 0.5", "step: 0"), "step"),
        (("default: plain", "default: fancy"), "default не из options"),
        (("maxlen: 12", "maxlen: 0"), "maxlen"),
        (("rule: d <= w", "rule: d <= nope"), "неизвестный"),
        (("rule: d <= w", "rule: d != w"), "правило"),
        (("default: 20", "default: 1"), "default у параметра w не проходит"),
    ],
)
def test_parse_errors(patch, text):
    broken = YAML_OK.replace(*patch)
    assert broken != YAML_OK
    with pytest.raises(EditorError, match=text):
        parse_editor("box", yaml.safe_load(broken))


def test_parse_duplicate_param_and_no_params():
    dup = YAML_OK.replace("name: d\n", "name: w\n")
    with pytest.raises(EditorError, match="дважды"):
        parse_editor("box", yaml.safe_load(dup))
    with pytest.raises(EditorError, match="ни одного"):
        parse_editor("box", {"title": "Пусто"})
    with pytest.raises(EditorError, match="Имя папки"):
        parse_editor("Bad Slug", yaml.safe_load(YAML_OK))


# --- проверка параметров ---------------------------------------------------------------


def test_validate_params_defaults_and_cleaning():
    editor = parse_editor("box", yaml.safe_load(YAML_OK))
    clean, errors = validate_params(editor, {})
    assert errors == {}
    assert clean == editor.defaults()

    clean, errors = validate_params(
        editor,
        {
            "w": "30,26",
            "d": 12.3456,
            "h": "7",
            "lid": "true",
            "style": "rounded",
            "label_text": " Hi ",
        },
    )
    assert errors == {}
    assert clean == {
        "w": 30.3,  # запятая как разделитель; округление до знаков шага (0.5 → 1 знак)
        "d": 12.346,  # без шага — 3 знака
        "h": 7,  # integer
        "lid": True,
        "style": "rounded",
        "label_text": "Hi",
    }


def test_validate_params_errors():
    editor = parse_editor("box", yaml.safe_load(YAML_OK))
    _, errors = validate_params(
        editor,
        {
            "w": "abc",
            "d": 200,
            "h": 2.5,
            "lid": "maybe",
            "style": "fancy",
            "label_text": "очень длинная надпись",
            "extra": 1,
        },
    )
    assert errors == {
        "w": "Нужно число.",
        "d": "Не больше 100.",
        "h": "Нужно целое число.",
        "lid": "Нужно да или нет.",
        "style": "Выберите один из вариантов.",
        "label_text": "Не длиннее 12 символов.",
        "extra": "Неизвестный параметр.",
    }
    _, errors = validate_params(editor, {"w": 4})
    assert errors == {"w": "Не меньше 5 мм."}
    _, errors = validate_params(editor, {"label_text": "a\nb"})
    assert "служебных" in errors["label_text"]
    _, errors = validate_params(editor, {"w": float("inf")})
    assert errors == {"w": "Нужно число."}


def test_validate_params_checks():
    editor = parse_editor("box", yaml.safe_load(YAML_OK))
    _, errors = validate_params(editor, {"w": 10, "d": 20})
    assert errors == {"d": "Глубина не больше ширины."}
    _, errors = validate_params(editor, {"h": 1})
    assert errors == {"h": "Нужно, чтобы h >= 2"}
    # правила не проверяются, пока есть ошибки по полям — чтобы не сравнивать мусор
    _, errors = validate_params(editor, {"w": "x", "d": 20})
    assert errors == {"w": "Нужно число."}


# --- команда OpenSCAD ------------------------------------------------------------------


def test_scad_literal_escapes_strings():
    assert scad_literal(True) == "true"
    assert scad_literal(False) == "false"
    assert scad_literal(12) == "12"
    assert scad_literal(12.5) == "12.5"
    assert scad_literal("abc") == '"abc"'
    # кавычки и слэши экранируются — из строки нельзя «выйти» в код
    assert scad_literal('a"b\\c') == '"a\\"b\\\\c"'
    assert scad_literal("x\ny") == '"x\\ny"'
    with pytest.raises(OpenScadError):
        scad_literal(float("nan"))
    with pytest.raises(OpenScadError):
        scad_literal([1, 2])


def test_build_command(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "/opt/openscad/bin/openscad --foo")
    cmd = build_command(tmp_path / "m.scad", tmp_path / "o.stl", {"w": 20, "lid": True, "t": "hi"})
    assert cmd == [
        "/opt/openscad/bin/openscad",
        "--foo",
        "-o",
        str(tmp_path / "o.stl"),
        "--export-format",
        "binstl",
        "-D",
        "w=20",
        "-D",
        "lid=true",
        "-D",
        't="hi"',
        str(tmp_path / "m.scad"),
    ]


def test_error_text():
    out = (
        "ERROR: Assertion 'false' failed: \"inner too big\""
        " in file /srv/editors/x/model.scad, line 7\n"
        "TRACE: called by 'assert' in file /srv/editors/x/model.scad, line 7\n"
        "Current top level object is empty.\n"
    )
    assert error_text(out) == "ERROR: Assertion 'false' failed: \"inner too big\""
    assert (
        error_text("Geometries in cache: 1\nCurrent top level object is empty.\n") == EMPTY_MESSAGE
    )
    assert error_text("a\nb\nc\nd\n") == "b | c | d"


def test_describe_params():
    editor = parse_editor("box", yaml.safe_load(YAML_OK))
    text = ed.describe_params(
        editor, {"w": 20.5, "d": 10, "h": 3, "lid": True, "style": "rounded", "label_text": "M8"}
    )
    assert text == "Ширина 20,5 мм, Глубина 10, Высота 3, Крышка: да, Стиль: rounded, Надпись: «M8»"
    assert ed.describe_params(editor, {"label_text": " "}) == ""


# --- API: схемы ------------------------------------------------------------------------


def test_list_editors_sorted_and_cards(client, editors_dir):
    r = client.get("/api/v1/editors")
    assert r.status_code == 200
    editors = r.json()["editors"]
    assert [e["slug"] for e in editors] == ["second", "bad-scad", "box"]  # order 1, 5, 5 (по slug)
    box = next(e for e in editors if e["slug"] == "box")
    assert box["title"] == "Коробка"
    assert box["material"] == "PETG"
    assert box["scad_ready"] is True
    style = next(p for p in box["params"] if p["name"] == "style")
    assert style["options"] == [
        {"value": "plain", "label": "Гладкая"},
        {"value": "rounded", "label": "rounded"},
    ]
    assert box["checks"][0] == {"rule": "d <= w", "message": "Глубина не больше ширины."}

    assert client.get("/api/v1/editors/box").json()["slug"] == "box"
    assert client.get("/api/v1/editors/nope").status_code == 404
    assert client.get("/api/v1/editors/Bad..Slug").status_code == 404


def test_broken_yaml_is_500_with_text(client, editors_dir):
    (editors_dir / "box" / "editor.yaml").write_text("title: Коробка\nparams: []\n", "utf-8")
    future = time.time() + 5
    os.utime(editors_dir / "box" / "editor.yaml", (future, future))
    r = client.get("/api/v1/editors/box")
    assert r.status_code == 500
    assert "ни одного параметра" in r.json()["detail"]
    assert client.get("/api/v1/editors").status_code == 500


def test_editor_reloads_when_yaml_changes(client, editors_dir):
    assert client.get("/api/v1/editors/box").json()["title"] == "Коробка"
    path = editors_dir / "box" / "editor.yaml"
    path.write_text(YAML_OK.replace("title: Коробка", "title: Ящик"), "utf-8")
    future = time.time() + 5
    os.utime(path, (future, future))
    assert client.get("/api/v1/editors/box").json()["title"] == "Ящик"


# --- API: сборки -----------------------------------------------------------------------


def _events(name: str) -> list[Event]:
    with Session(get_engine()) as db:
        return list(db.execute(select(Event).where(Event.name == name)).scalars())


def test_build_ok_and_cached(client, editors_dir, fake_openscad):
    r = client.post(
        "/api/v1/editors/box/builds",
        json={"params": {"w": 30, "h": 5, "lid": True, "label_text": "Hi"}},
    )
    assert r.status_code == 202, r.text
    build = r.json()
    assert build["status"] == "done"
    assert build["editor"] == "box"
    assert build["params"] == {
        "w": 30,
        "d": 10,
        "h": 5,
        "lid": True,
        "style": "plain",
        "label_text": "Hi",
    }
    assert build["mesh"]["bbox_mm"] == {
        "x": 30.0,
        "y": 10.0,
        "z": 5.0,
    }  # подделка строит коробку w×d×h
    assert build["error"] is None
    assert build["file_url"] == f"/api/v1/editors/box/builds/{build['id']}/file"

    # что ушло в OpenSCAD через -D
    stl = ed.stl_path("box", build["id"])
    passed = json.loads(stl.with_name("model.stl.params.json").read_text())
    assert passed == {
        "w": "30",
        "d": "10",
        "h": "5",
        "lid": "true",
        "style": '"plain"',
        "label_text": '"Hi"',
    }

    # файл отдаётся, запись читается
    assert client.get(build["file_url"]).content == stl.read_bytes()
    assert client.get(f"/api/v1/editors/box/builds/{build['id']}").json()["status"] == "done"

    # те же параметры (в другом порядке и как строки) → та же сборка, OpenSCAD не запускается
    stl.unlink()  # если бы строили заново — файл появился бы снова
    r2 = client.post(
        "/api/v1/editors/box/builds",
        json={"params": {"label_text": "Hi", "lid": "true", "h": "5", "w": "30.0"}},
    )
    assert r2.status_code == 202
    assert r2.json()["id"] == build["id"]
    assert not stl.exists()

    events = _events("editor_build")
    assert [e.props["cached"] for e in events] == [False, True]
    assert events[0].props["editor_slug"] == "box"
    assert events[0].props["params"]["w"] == 30


def test_build_validation_errors(client, editors_dir, fake_openscad):
    r = client.post("/api/v1/editors/box/builds", json={"params": {"w": 1000, "zzz": 1}})
    assert r.status_code == 422
    assert r.json()["detail"]["errors"] == {
        "w": "Не больше 100 мм.",
        "zzz": "Неизвестный параметр.",
    }
    assert client.post("/api/v1/editors/nope/builds", json={"params": {}}).status_code == 404
    assert _events("editor_build") == []  # до сборки дело не дошло — события нет


def test_build_with_defaults(client, editors_dir, fake_openscad):
    r = client.post("/api/v1/editors/box/builds", json={})
    assert r.status_code == 202
    assert r.json()["params"] == {
        "w": 20,
        "d": 10,
        "h": 10,
        "lid": False,
        "style": "plain",
        "label_text": "",
    }


def test_build_openscad_error(client, editors_dir, fake_openscad):
    r = client.post("/api/v1/editors/bad-scad/builds", json={"params": {}})
    assert r.status_code == 202
    build = r.json()
    assert build["status"] == "error"
    assert "Parser error" in build["error"]
    assert "/model.scad" not in build["error"]  # путей к файлам клиенту не показываем
    assert build["mesh"] is None
    assert client.get(build["file_url"]).status_code == 404
    assert client.post(f"/api/v1/editors/bad-scad/builds/{build['id']}/upload").status_code == 409
    # ошибочную сборку можно запросить снова — построим заново
    (editors_dir / "bad-scad" / "model.scad").write_text(SCAD_OK, "utf-8")
    r2 = client.post("/api/v1/editors/bad-scad/builds", json={"params": {}})
    assert r2.json()["status"] == "done"
    assert r2.json()["id"] != build["id"]  # дата scad-файла поменялась → новый id


def test_build_missing_openscad(client, editors_dir, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "/nonexistent/openscad")
    monkeypatch.setattr(settings, "redis_url", "")
    build = client.post("/api/v1/editors/box/builds", json={}).json()
    assert build["status"] == "error"
    assert "Не найден OpenSCAD" in build["error"]


def test_build_scad_changed_gives_new_id(client, editors_dir, fake_openscad):
    first = client.post("/api/v1/editors/box/builds", json={}).json()
    scad = editors_dir / "box" / "model.scad"
    future = time.time() + 5
    os.utime(scad, (future, future))
    second = client.post("/api/v1/editors/box/builds", json={}).json()
    assert first["id"] != second["id"]


def test_build_unknown_id_404(client, editors_dir):
    assert client.get("/api/v1/editors/box/builds/" + "0" * 32).status_code == 404
    assert client.get("/api/v1/editors/box/builds/../x").status_code == 404
    assert client.get("/api/v1/editors/box/builds/zzz/file").status_code == 404


def test_build_queued_with_redis(client, editors_dir, fake_openscad, monkeypatch):
    """С REDIS_URL задача уходит в очередь, ответ — queued; строит её worker (build_editor)."""
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    calls = []

    async def fake_enqueue(request, slug, build_id, attempt=0):
        calls.append((slug, build_id))

    monkeypatch.setattr(ed, "_enqueue", fake_enqueue)
    r = client.post("/api/v1/editors/box/builds", json={})
    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert calls == [("box", r.json()["id"])]

    # повторный запрос пока строится — та же запись, второй раз в очередь не кладём
    assert client.post("/api/v1/editors/box/builds", json={}).json()["status"] == "queued"
    assert len(calls) == 1

    # worker делает ровно это:
    import asyncio

    from app.worker import WorkerSettings, build_editor

    assert build_editor in WorkerSettings.functions
    result = asyncio.run(build_editor({}, "box", r.json()["id"]))
    assert result["status"] == "done"
    assert client.get(f"/api/v1/editors/box/builds/{r.json()['id']}").json()["status"] == "done"


# --- «Заказать» → загрузка -------------------------------------------------------------


def test_order_from_build_makes_upload(client, editors_dir, fake_openscad):
    build = client.post("/api/v1/editors/box/builds", json={"params": {"w": 40}}).json()
    r = client.post(f"/api/v1/editors/box/builds/{build['id']}/upload")
    assert r.status_code == 201, r.text
    meta = r.json()
    upload_id = meta["id"]
    assert meta["source"] == "editor"
    assert meta["editor"] == {
        "slug": "box",
        "title": "Коробка",
        "material": "PETG",
        "build_id": build["id"],
        "params": build["params"],
        "summary": "Ширина 40 мм, Глубина 10, Высота 10, Крышка: нет, Стиль: Гладкая",
    }
    assert meta["original_name"] == "Коробка.stl"
    assert meta["ext"] == "stl"
    assert meta["units"] == "mm"
    assert meta["mesh"]["bbox_mm"] == {"x": 40.0, "y": 10.0, "z": 10.0}
    # дальше работает весь обычный путь загрузки; файл — своя копия
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["id"] == upload_id
    assert (
        client.get(f"/api/v1/uploads/{upload_id}/file").content
        == ed.stl_path("box", build["id"]).read_bytes()
    )
    shutil.rmtree(ed.build_dir("box", build["id"]))
    assert client.get(f"/api/v1/uploads/{upload_id}/file").status_code == 200

    with Session(get_engine()) as db:
        event = db.execute(select(Event).where(Event.upload_id == upload_id)).scalar_one()
    assert event.name == "upload"
    assert event.props["source"] == "editor"
    assert event.props["editor_slug"] == "box"
    assert event.props["build_id"] == build["id"]


def test_order_from_unknown_build(client, editors_dir, fake_openscad):
    assert client.post("/api/v1/editors/box/builds/" + "0" * 32 + "/upload").status_code == 404
    assert client.post("/api/v1/editors/nope/builds/" + "0" * 32 + "/upload").status_code == 404


# --- уборка ----------------------------------------------------------------------------


def test_cleanup_builds(client, editors_dir, fake_openscad):
    old = client.post("/api/v1/editors/box/builds", json={"params": {"w": 11}}).json()
    fresh = client.post("/api/v1/editors/box/builds", json={"params": {"w": 12}}).json()
    old_dir = ed.build_dir("box", old["id"])
    record = json.loads((old_dir / "build.json").read_text())
    record["created_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat(timespec="seconds")
    (old_dir / "build.json").write_text(json.dumps(record))
    # папка без build.json — по дате папки (старая)
    orphan = ed.builds_root("box") / ("f" * 32)
    orphan.mkdir()
    long_ago = time.time() - 40 * 86400
    os.utime(orphan, (long_ago, long_ago))
    (ed.builds_root("box") / "not-a-build").mkdir()  # чужая папка — не трогаем

    dry = ed.cleanup_builds(30, dry_run=True)
    assert dry == {"checked": 3, "deleted": 2, "freed_bytes": dry["freed_bytes"]}
    assert old_dir.exists()

    report = ed.cleanup_builds(30)
    assert report["deleted"] == 2
    assert not old_dir.exists() and not orphan.exists()
    assert ed.build_dir("box", fresh["id"]).exists()
    assert (ed.builds_root("box") / "not-a-build").exists()
    assert ed.cleanup_builds(0) == {"checked": 0, "deleted": 0, "freed_bytes": 0}


def test_cleanup_job_includes_builds(client, editors_dir, fake_openscad, monkeypatch):
    from app.cleanup import cleanup_job

    build = client.post("/api/v1/editors/box/builds", json={}).json()
    folder = ed.build_dir("box", build["id"])
    record = json.loads((folder / "build.json").read_text())
    record["created_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat(timespec="seconds")
    (folder / "build.json").write_text(json.dumps(record))
    result = cleanup_job()
    assert result["editor_builds"] == 1
    assert not folder.exists()


# --- настоящие редакторы (spacer, bracket, box, label) и настоящий OpenSCAD -------------------


@pytest.fixture
def real_editors(monkeypatch, data_dir):
    monkeypatch.setattr(settings, "editors_dir", REPO_ROOT / "editors")
    monkeypatch.setattr(settings, "redis_url", "")
    ed.reload_editors()
    yield
    ed.reload_editors()


def test_repo_editors_are_valid(client, real_editors):
    """Все редакторы в editors/ читаются, у каждого есть scad-файл, умолчания проходят проверку."""
    r = client.get("/api/v1/editors")
    assert r.status_code == 200, r.text
    editors = r.json()["editors"]
    slugs = [e["slug"] for e in editors]
    assert slugs[:4] == ["spacer", "bracket", "box", "label"]  # order: 10, 20, 30, 40
    for card in editors:
        assert card["scad_ready"], f"у редактора {card['slug']} нет scad-файла"
        editor = ed.load_editor(card["slug"])
        _, errors = validate_params(editor, {})
        assert errors == {}, (card["slug"], errors)
        # каждый параметр объявлен переменной в scad — иначе -D не на что ляжет
        scad = ed.scad_path(editor).read_text("utf-8")
        for p in editor.params:
            assert f"{p.name} =" in scad or f"{p.name}=" in scad, (card["slug"], p.name)


@pytest.mark.skipif(shutil.which("openscad") is None, reason="нужен настоящий OpenSCAD")
def test_spacer_with_real_openscad(client, real_editors, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "openscad")
    build = client.post(
        "/api/v1/editors/spacer/builds",
        json={
            "params": {"outer_d": 30, "inner_d": 10, "height": 8, "shape": "hex", "chamfer": True}
        },
    ).json()
    assert build["status"] == "done", build["error"]
    m = build["mesh"]
    assert m["watertight"] is True
    assert m["bbox_mm"]["z"] == 8.0
    assert abs(m["bbox_mm"]["y"] - 30.0) < 0.1  # размер под ключ по Y
    assert m["bbox_mm"]["x"] > 30.0  # по углам шестигранник шире

    bad = client.post(
        "/api/v1/editors/spacer/builds", json={"params": {"outer_d": 10, "inner_d": 12}}
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["errors"] == {
        "inner_d": "Отверстие должно быть меньше внешнего диаметра."
    }


def test_bracket_schema_and_checks(client, real_editors):
    """Кронштейн (B22): схема формы и правила между параметрами — без OpenSCAD."""
    editor = ed.load_editor("bracket")
    assert editor.title == "Кронштейн / уголок"
    assert [p.name for p in editor.params] == [
        "length_a",
        "length_b",
        "width",
        "thickness",
        "hole_d",
        "holes_a",
        "holes_b",
        "hole_type",
        "rib",
        "rounded",
    ]
    assert editor.param("holes_a").integer is True
    assert dict(editor.param("hole_type").options) == {
        "plain": "Обычные",
        "countersunk": "Под потайной винт",
    }
    # отверстие шире полки
    _, errors = validate_params(editor, {"width": 8, "hole_d": 8})
    assert list(errors) == ["hole_d"]
    # толщина не меньше длины полки
    _, errors = validate_params(editor, {"length_b": 15, "thickness": 15})
    assert list(errors) == ["thickness"]
    # дробное число отверстий
    _, errors = validate_params(editor, {"holes_a": 1.5})
    assert errors == {"holes_a": "Нужно целое число."}
    clean, errors = validate_params(editor, {"holes_b": "3", "thickness": "3,5"})
    assert errors == {} and clean["holes_b"] == 3 and clean["thickness"] == 3.5


@pytest.mark.skipif(shutil.which("openscad") is None, reason="нужен настоящий OpenSCAD")
def test_bracket_with_real_openscad(client, real_editors, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "openscad")

    def build(params: dict) -> dict:
        r = client.post("/api/v1/editors/bracket/builds", json={"params": params})
        assert r.status_code == 202, r.text
        record = r.json()
        assert record["status"] == "done", record["error"]
        assert record["mesh"]["watertight"] is True
        return record["mesh"]

    # Голый уголок без отверстий и косынок: объём считается руками.
    # 50×25×4 (полка A) + 46×25×4 (полка B над ней) = 9600 мм³ = 9.6 см³.
    m = build({"holes_a": 0, "holes_b": 0, "rib": False, "rounded": False})
    assert m["bbox_mm"] == {"x": 50.0, "y": 25.0, "z": 50.0}
    assert abs(m["volume_cm3"] - 9.6) < 0.01

    # Умолчания: отверстия и косынки убавляют/прибавляют объём, габариты те же.
    m = build({})
    assert m["bbox_mm"] == {"x": 50.0, "y": 25.0, "z": 50.0}
    assert 11.5 < m["volume_cm3"] < 12.5

    # Потай срезает ещё немного материала.
    sunk = build({"hole_type": "countersunk"})
    assert sunk["volume_cm3"] < m["volume_cm3"]

    # Отверстия, которые не помещаются на короткой полке, пропускаются — модель всё равно
    # строится, а не ломается.
    m = build({"length_a": 15, "length_b": 15, "thickness": 14, "holes_a": 4, "holes_b": 4})
    assert m["bbox_mm"] == {"x": 15.0, "y": 25.0, "z": 15.0}


def test_box_schema_and_checks(client, real_editors):
    """Коробка (B23): схема формы и правила между параметрами — без OpenSCAD."""
    editor = ed.load_editor("box")
    assert editor.title == "Коробка / органайзер"
    assert [p.name for p in editor.params] == [
        "length",
        "width",
        "height",
        "wall",
        "floor_t",
        "corner_r",
        "cells_x",
        "cells_y",
        "divider",
        "lid",
        "lid_gap",
    ]
    assert editor.param("cells_x").integer is True
    assert list(dict(editor.param("lid").options)) == ["none", "inset", "cap"]
    # дно не тоньше высоты
    _, errors = validate_params(editor, {"height": 10, "floor_t": 4})
    assert errors == {}
    _, errors = validate_params(editor, {"height": 10, "floor_t": 12})
    assert list(errors) == ["floor_t"]
    # дробное число ячеек и чужая крышка
    _, errors = validate_params(editor, {"cells_y": 2.5, "lid": "hinge"})
    assert set(errors) == {"cells_y", "lid"}
    clean, errors = validate_params(editor, {"cells_x": "3", "wall": "2,0", "lid": "cap"})
    assert errors == {} and clean["cells_x"] == 3 and clean["wall"] == 2.0


@pytest.mark.skipif(shutil.which("openscad") is None, reason="нужен настоящий OpenSCAD")
def test_box_with_real_openscad(client, real_editors, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "openscad")

    def build(params: dict) -> dict:
        r = client.post("/api/v1/editors/box/builds", json={"params": params})
        assert r.status_code == 202, r.text
        record = r.json()
        assert record["status"] == "done", record["error"]
        assert record["mesh"]["watertight"] is True
        return record["mesh"]

    # Коробка без скруглений и перегородок: объём считается руками.
    # 100×70×40 − (100−3,2)×(70−3,2)×(40−1,6) = 280 000 − 248 303,6 = 31 696 мм³.
    m = build({"corner_r": 0, "cells_x": 1, "cells_y": 1})
    assert m["bbox_mm"] == {"x": 100.0, "y": 70.0, "z": 40.0}
    assert abs(m["volume_cm3"] - 31.696) < 0.01

    # Умолчания: скругление чуть убавляет, перегородка прибавляет; габариты те же.
    m = build({})
    assert m["bbox_mm"] == {"x": 100.0, "y": 70.0, "z": 40.0}
    assert 33 < m["volume_cm3"] < 36

    # Вкладная крышка лежит рядом по Y (коробка не шире, чем длиннее): габарит по Y
    # = ширина + 10 мм + ширина; по X крышка не выступает.
    inset = build({"lid": "inset"})
    assert inset["bbox_mm"] == {"x": 100.0, "y": 150.0, "z": 40.0}
    assert inset["volume_cm3"] > m["volume_cm3"] + 10

    # Колпачок больше коробки на зазор и стенку с каждой стороны: 100 + 2·0,3 + 2·1,6 = 103,8.
    cap = build({"lid": "cap"})
    assert cap["bbox_mm"] == {"x": 103.8, "y": 153.8, "z": 40.0}

    # Коробка шире, чем длиннее → крышка ложится по X.
    wide = build({"length": 30, "width": 120, "lid": "cap"})
    assert wide["bbox_mm"]["x"] > 60 and wide["bbox_mm"]["y"] < 125

    # Крошечная коробка с толстыми стенками: 8×8 ячеек не помещаются — лишние перегородки
    # пропускаются, скругление 15 мм ужимается до размера; модель строится, а не ломается.
    m = build(
        {
            "length": 20,
            "width": 20,
            "height": 10,
            "wall": 4,
            "floor_t": 4,
            "corner_r": 15,
            "cells_x": 8,
            "cells_y": 8,
        }
    )
    assert m["bbox_mm"] == {"x": 20.0, "y": 20.0, "z": 10.0}


def test_label_schema_and_checks(client, real_editors):
    """Табличка (B24): схема формы и правила — без OpenSCAD."""
    editor = ed.load_editor("label")
    assert editor.title == "Табличка / бирка с текстом"
    assert [p.name for p in editor.params] == [
        "text",
        "text2",
        "font_size",
        "font",
        "bold",
        "style",
        "text_h",
        "thickness",
        "width",
        "height",
        "margin",
        "corner_r",
        "frame",
        "hole",
        "hole_d",
    ]
    assert editor.param("text").type == "text" and editor.param("text").maxlen == 30
    assert editor.param("text2").default == ""
    assert list(dict(editor.param("font").options)) == ["sans", "serif", "mono"]
    assert list(dict(editor.param("style").options)) == ["raised", "engraved"]
    assert list(dict(editor.param("hole").options)) == ["none", "left", "both"]
    # глубина букв не меньше толщины — текст прорезал бы табличку
    _, errors = validate_params(editor, {"thickness": 1, "text_h": 1})
    assert list(errors) == ["text_h"]
    # слишком длинная надпись и перенос строки
    _, errors = validate_params(editor, {"text": "x" * 31, "text2": "две\nстроки"})
    assert set(errors) == {"text", "text2"}
    # кириллица, кавычки и пустая вторая строка — нормальный ввод
    clean, errors = validate_params(editor, {"text": 'Ёжик "в" тумане', "text2": "", "width": "0"})
    assert errors == {} and clean["text"] == 'Ёжик "в" тумане' and clean["width"] == 0


def test_label_text_goes_to_openscad_quoted(tmp_path):
    """Надпись уходит в OpenSCAD строкой в кавычках: кавычки и слэши экранированы."""
    params = {"text": 'Ёжик "в" \\ 1', "bold": True}
    cmd = build_command(tmp_path / "m.scad", tmp_path / "o.stl", params)
    assert "-D" in cmd
    assert cmd[cmd.index("-D") + 1] == 'text="Ёжик \\"в\\" \\\\ 1"'
    assert "bold=true" in cmd


@pytest.mark.skipif(shutil.which("openscad") is None, reason="нужен настоящий OpenSCAD")
def test_label_with_real_openscad(client, real_editors, monkeypatch):
    monkeypatch.setattr(settings, "openscad_bin", "openscad")

    def build(params: dict) -> dict:
        r = client.post("/api/v1/editors/label/builds", json={"params": params})
        assert r.status_code == 202, r.text
        record = r.json()
        assert record["status"] == "done", record["error"]
        assert record["mesh"]["watertight"] is True
        return record["mesh"]

    # Пустая табличка без надписи: поля 4 мм с каждой стороны, скругление не ломает модель.
    # 8 × (8 + 10,5 высота строки) × 2 мм — объём чуть меньше из-за скруглённых углов.
    m = build({"text": "", "text2": ""})
    assert m["bbox_mm"]["x"] == 8.0 and m["bbox_mm"]["z"] == 2.0
    assert 0.25 < m["volume_cm3"] < 0.3

    # Умолчания «ТУЦ»: выпуклый текст поднимает высоту до 2 + 1 мм, ширина — по надписи.
    m = build({})
    assert m["bbox_mm"]["z"] == 3.0
    assert 30 < m["bbox_mm"]["x"] < 45

    # Углублённый текст не меняет габариты и убавляет объём по сравнению с плоской табличкой.
    plain = build({"text": "ТУЦ", "style": "engraved", "width": 40, "height": 20, "corner_r": 0})
    assert plain["bbox_mm"] == {"x": 40.0, "y": 20.0, "z": 2.0}
    assert plain["volume_cm3"] < 1.6  # 40 × 20 × 2 = 1,6 см³ минус буквы

    # Две строки, отверстие слева, рамка: табличка выше и шире (место под отверстие),
    # кириллица и латиница в одной надписи.
    m = build({"text": "Ключи от дачи", "text2": "Return to Girg", "hole": "left", "frame": True})
    assert m["bbox_mm"]["y"] > 30 and m["bbox_mm"]["x"] > 90
    assert m["bbox_mm"]["z"] == 3.0

    # Заданный размер меньше, чем нужно тексту: буквы ужимаются, габарит — ровно заданный.
    m = build({"text": "Очень длинная надпись", "width": 50, "height": 15})
    assert m["bbox_mm"] == {"x": 50.0, "y": 15.0, "z": 3.0}

    # Огромный шрифт: автоматическая ширина упирается в 250 мм (стол принтера), не больше.
    m = build({"text": "ОСТОРОЖНО, ЗЛАЯ СОБАКА", "font_size": 40})
    assert m["bbox_mm"]["x"] == 250.0

    # Кавычки и слэш в надписи не ломают запуск OpenSCAD.
    m = build({"text": 'Ёжик "в" \\ тумане', "font": "serif", "bold": False})
    assert m["bbox_mm"]["z"] == 3.0


def test_repo_editors_explain_every_param():
    """B67: у каждого параметра настоящих редакторов есть подсказка «зачем он» (hint)."""
    root = REPO_ROOT / "editors"
    slugs = sorted(p.name for p in root.iterdir() if (p / "editor.yaml").is_file())
    assert slugs
    for slug in slugs:
        raw = yaml.safe_load((root / slug / "editor.yaml").read_text("utf-8"))
        editor = parse_editor(slug, raw)
        missing = [p.name for p in editor.params if not p.hint]
        assert not missing, f"{slug}: нет hint у {missing}"
