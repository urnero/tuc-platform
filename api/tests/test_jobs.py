"""Застрявшие фоновые задачи (QA 2026-10-22, баг «НЕДОСТУПНОСТЬ»), app/jobs.py.

Два случая на каждый вид задачи (расчёт печати, сборка редактора, тиснение):
1. Redis недоступен при постановке в очередь → 503, записи не остаётся, можно повторить.
2. Запись queued/running старше таймаута → error с текстом, следующий POST ставит
   задачу заново под новым id arq (суффикс :r1).
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import REPO_ROOT, box_stl

from app import editors as ed
from app import jobs
from app.config import settings

OLD = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="seconds")
FRESH = datetime.now(UTC).isoformat(timespec="seconds")


# --- чистые функции ----------------------------------------------------------------------


def test_is_stuck_by_status_and_age():
    assert jobs.is_stuck({"status": "queued", "created_at": OLD})
    assert not jobs.is_stuck({"status": "queued", "created_at": FRESH})
    # running: отсчёт от started_at, даже если в очереди ждала долго
    assert not jobs.is_stuck({"status": "running", "created_at": OLD, "started_at": FRESH})
    assert jobs.is_stuck({"status": "running", "created_at": OLD, "started_at": OLD})
    # старая запись без started_at — по created_at
    assert jobs.is_stuck({"status": "running", "created_at": OLD})
    # done/error и записи без дат не трогаем
    assert not jobs.is_stuck({"status": "done", "created_at": OLD})
    assert not jobs.is_stuck({"status": "error", "created_at": OLD})
    assert not jobs.is_stuck({"status": "queued"})
    assert not jobs.is_stuck({"status": "queued", "created_at": "не дата"})


def test_stuck_threshold_matches_worker_timeout(monkeypatch):
    """Порог «брошена» = таймаут задачи в worker: дольше задача жить не может."""
    from app.worker import WorkerSettings

    assert jobs.stuck_after_s() == jobs.job_timeout_s() == WorkerSettings.job_timeout
    monkeypatch.setattr(settings, "slice_timeout_s", 10)
    assert jobs.stuck_after_s() == 10 + jobs.JOB_TIMEOUT_EXTRA_S
    just_over = (datetime.now(UTC) - timedelta(seconds=71)).isoformat(timespec="seconds")
    assert jobs.is_stuck({"status": "queued", "created_at": just_over})


def test_settle_marks_error_and_saves():
    saved = []
    rec = jobs.settle({"status": "queued", "created_at": OLD}, saved.append)
    assert rec["status"] == "error" and rec["error"] == jobs.STUCK_ERROR and rec["finished_at"]
    assert saved == [rec]
    assert jobs.settle(None, saved.append) is None
    fresh = {"status": "queued", "created_at": FRESH}
    assert jobs.settle(fresh, saved.append) is fresh and len(saved) == 1


def test_retry_job_id_and_attempt():
    assert jobs.retry_job_id("slice:x", 0) == "slice:x"
    assert jobs.retry_job_id("slice:x", 2) == "slice:x:r2"
    assert jobs.next_attempt(None) == 0
    assert jobs.next_attempt({"status": "error"}) == 1  # старая запись без поля attempt
    assert jobs.next_attempt({"status": "error", "attempt": 3}) == 4


# --- общие заготовки для API ------------------------------------------------------------


@pytest.fixture
def queue(monkeypatch):
    """Вместо Redis: список положенных задач; `queue.down = True` — Redis «не отвечает»."""
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")

    class Queue:
        down = False
        jobs: list[tuple] = []

        async def enqueue(self, request, function, *args, job_id):
            if self.down:
                raise jobs.QueueUnavailable("Connection refused")
            self.jobs.append((function, args, job_id))

    q = Queue()
    monkeypatch.setattr(jobs, "enqueue", q.enqueue)
    return q


def _age(path, **fields):
    """Подменяет даты в сохранённой записи — как будто она лежит давно."""
    rec = json.loads(path.read_text("utf-8"))
    rec.update(fields)
    path.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    return rec


def _upload(client) -> str:
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    assert r.status_code == 201
    return r.json()["id"]


# --- расчёт печати -----------------------------------------------------------------------


def test_slice_redis_down_503_and_no_record(client, data_dir, queue):
    """Redis недоступен → 503 с текстом, записи нет (GET 404); когда Redis вернулся —
    тот же POST ставит задачу как в первый раз."""
    uid = _upload(client)
    queue.down = True
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={"material": "PLA"})
    assert r.status_code == 503
    assert r.json()["detail"] == jobs.QUEUE_UNAVAILABLE
    assert not (data_dir / "uploads" / uid / "slices" / "PLA.json").exists()
    assert client.get(f"/api/v1/uploads/{uid}/slice?material=PLA").status_code == 404

    queue.down = False
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={"material": "PLA"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert r.json()["attempt"] == 0
    assert queue.jobs == [("slice_upload", (uid, "PLA", False), f"slice:{uid}:PLA:False:mm")]


def test_slice_real_redis_unreachable_503(client, data_dir, monkeypatch):
    """Без подмены: настоящий arq не достучался до Redis → наш 503, а не 500."""
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    uid = _upload(client)
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={"material": "PLA"})
    assert r.status_code == 503, r.text
    assert not (data_dir / "uploads" / uid / "slices" / "PLA.json").exists()


def test_slice_stuck_queued_becomes_error_then_retry(client, data_dir, queue):
    """queued старше таймаута → GET отдаёт error (опрос на сайте остановится),
    POST ставит заново: attempt = 1, id задачи arq с суффиксом :r1."""
    uid = _upload(client)
    assert client.post(f"/api/v1/uploads/{uid}/slice", json={}).json()["status"] == "queued"
    path = data_dir / "uploads" / uid / "slices" / "PLA.json"
    _age(path, created_at=OLD)

    r = client.get(f"/api/v1/uploads/{uid}/slice")
    assert r.status_code == 200
    assert r.json()["status"] == "error" and r.json()["error"] == jobs.STUCK_ERROR
    assert json.loads(path.read_text("utf-8"))["status"] == "error"  # сохранили

    r = client.post(f"/api/v1/uploads/{uid}/slice", json={})
    assert r.status_code == 202
    assert r.json()["status"] == "queued" and r.json()["attempt"] == 1
    assert queue.jobs[-1][2] == f"slice:{uid}:PLA:False:mm:r1"
    assert len(queue.jobs) == 2


def test_slice_stuck_running_detected_in_post(client, data_dir, queue):
    """running с давним started_at → брошена; running, взятая недавно после долгой очереди —
    нет, повторный POST её не трогает."""
    uid = _upload(client)
    client.post(f"/api/v1/uploads/{uid}/slice", json={})
    path = data_dir / "uploads" / uid / "slices" / "PLA.json"

    _age(path, status="running", created_at=OLD, started_at=FRESH)
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={})
    assert r.json()["status"] == "running" and len(queue.jobs) == 1

    _age(path, status="running", created_at=OLD, started_at=OLD)
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={})
    assert r.json()["status"] == "queued" and r.json()["attempt"] == 1
    assert len(queue.jobs) == 2


def test_slice_error_retry_gets_new_arq_id(client, queue):
    """Повтор после ошибки слайсера — тоже новый id arq, иначе arq час молчал бы
    (результат прежней задачи он хранит keep_result)."""
    uid = _upload(client)
    client.post(f"/api/v1/uploads/{uid}/slice", json={})
    from app.slice_jobs import load_record, save_record

    rec = load_record(uid, "PLA")
    rec.update(status="error", error="слайсер упал")
    save_record(uid, rec)
    r = client.post(f"/api/v1/uploads/{uid}/slice", json={})
    assert r.json()["status"] == "queued" and r.json()["attempt"] == 1
    assert queue.jobs[-1][2].endswith(":r1")


def test_run_slice_sets_started_at(client, fake_slicer):
    uid = _upload(client)
    rec = client.post(f"/api/v1/uploads/{uid}/slice", json={}).json()
    assert rec["status"] == "done" and rec["started_at"] and rec["attempt"] == 0


# --- редактор ----------------------------------------------------------------------------


@pytest.fixture
def real_editors(monkeypatch):
    """Настоящие редакторы из editors/ (нужен только slug spacer)."""
    monkeypatch.setattr(settings, "editors_dir", REPO_ROOT / "editors")
    ed.reload_editors()
    yield
    ed.reload_editors()


def test_editor_build_redis_down_and_stuck(client, data_dir, queue, real_editors):
    first = client.post("/api/v1/editors/spacer/builds", json={})
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "queued"
    build_id = first.json()["id"]
    path = ed.record_path("spacer", build_id)
    assert path.is_file()

    # брошена → error в GET и в POST, повтор под новым id
    _age(path, created_at=OLD)
    r = client.get(f"/api/v1/editors/spacer/builds/{build_id}")
    assert r.json()["status"] == "error" and r.json()["error"] == jobs.STUCK_ERROR
    r = client.post("/api/v1/editors/spacer/builds", json={})
    assert r.json()["status"] == "queued" and r.json()["attempt"] == 1
    assert queue.jobs[-1][2] == f"editor:spacer:{build_id}:r1"

    # Redis упал: 503, записи нет, повтор возможен
    _age(path, created_at=OLD)
    queue.down = True
    r = client.post("/api/v1/editors/spacer/builds", json={})
    assert r.status_code == 503 and not path.exists()
    assert client.get(f"/api/v1/editors/spacer/builds/{build_id}").status_code == 404
    queue.down = False
    assert client.post("/api/v1/editors/spacer/builds", json={}).json()["status"] == "queued"


# --- тиснение ----------------------------------------------------------------------------


def _emboss(client, upload_id):
    body = {"kind": "text", "text": "ТУЦ", "size_mm": 8, "depth_mm": 1, "face": "top"}
    return client.post(f"/api/v1/uploads/{upload_id}/embosses", json={"params": body})


def test_emboss_redis_down_and_stuck(client, data_dir, queue):
    uid = _upload(client)
    queue.down = True
    r = _emboss(client, uid)
    assert r.status_code == 503 and r.json()["detail"] == jobs.QUEUE_UNAVAILABLE
    assert not (data_dir / "uploads" / uid / "embosses").exists() or not any(
        (data_dir / "uploads" / uid / "embosses").glob("*.json")
    )

    queue.down = False
    r = _emboss(client, uid)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    job_id = r.json()["id"]
    (path,) = (data_dir / "uploads" / uid).rglob(f"{job_id}.json")

    _age(path, status="running", created_at=OLD, started_at=OLD)
    r = client.get(f"/api/v1/uploads/{uid}/embosses/{job_id}")
    assert r.json()["status"] == "error" and r.json()["error"] == jobs.STUCK_ERROR
    r = _emboss(client, uid)
    assert r.json()["status"] == "queued" and r.json()["attempt"] == 1
    assert queue.jobs[-1][2] == f"emboss:{uid}:{job_id}:r1"
