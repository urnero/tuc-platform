import json

from conftest import box_3mf, box_stl

from app.config import settings


def _post(client, name: str, data: bytes):
    return client.post("/api/v1/uploads", files={"file": (name, data, "application/octet-stream")})


def test_upload_stl_ok(client, data_dir):
    r = _post(client, "деталь.stl", box_stl())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["original_name"] == "деталь.stl"
    assert body["ext"] == "stl"
    assert body["size_bytes"] == len(box_stl())
    assert body["mesh"]["bbox_mm"] == {"x": 20.0, "y": 30.0, "z": 40.0}
    assert body["mesh"]["watertight"] is True

    # Файл и meta.json лежат в DATA_DIR/uploads/<id>/
    folder = data_dir / "uploads" / body["id"]
    assert (folder / "model.stl").read_bytes() == box_stl()
    assert json.loads((folder / "meta.json").read_text("utf-8"))["id"] == body["id"]


def test_upload_3mf_ok(client):
    r = _post(client, "part.3MF", box_3mf())
    assert r.status_code == 201, r.text
    assert r.json()["ext"] == "3mf"


def test_get_upload_and_file(client):
    created = _post(client, "box.stl", box_stl()).json()
    r = client.get(f"/api/v1/uploads/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created

    f = client.get(f"/api/v1/uploads/{created['id']}/file")
    assert f.status_code == 200
    assert f.content == box_stl()


def test_get_unknown_upload_404(client):
    assert client.get("/api/v1/uploads/" + "0" * 32).status_code == 404
    assert client.get("/api/v1/uploads/../etc/passwd").status_code == 404
    assert client.get("/api/v1/uploads/not-an-id/file").status_code == 404


def test_wrong_extension_415(client):
    r = _post(client, "model.obj", b"v 0 0 0")
    assert r.status_code == 415


def test_path_in_filename_is_stripped(client):
    r = _post(client, "../../evil.stl", box_stl())
    assert r.status_code == 201
    assert r.json()["original_name"] == "evil.stl"


def test_broken_file_422(client):
    r = _post(client, "model.stl", b"definitely not an stl")
    assert r.status_code == 422
    assert r.json()["detail"]  # человекочитаемое сообщение для клиента


def test_empty_file_422(client):
    r = _post(client, "model.stl", b"")
    assert r.status_code == 422


def test_too_big_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = box_stl() + b"\0" * (1024 * 1024 + 1)
    r = _post(client, "big.stl", big)
    assert r.status_code == 413
