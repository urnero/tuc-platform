"""Сторож стендов deploy/uptime.sh (B54): запускаем скрипт с поддельными curl и gh.

Поддельный curl отвечает кодом из файла codes/<prod|staging>, поддельный gh пишет
свои аргументы в gh.log, а на `gh api …/issues` отвечает номером из open_issue / last_issue.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "uptime.sh"

FAKE_CURL = """#!/usr/bin/env bash
url="${@: -1}"
case "$url" in
  *staging*) cat "$FAKE_DIR/codes/staging" ;;
  *) cat "$FAKE_DIR/codes/prod" ;;
esac
"""

FAKE_GH = """#!/usr/bin/env bash
args="$*"; echo "${args//$'\n'/ }" >> "$FAKE_DIR/gh.log"  # тело в одну строку
if [ "$1" = "api" ]; then
  case "$*" in
    *"state=open"*) cat "$FAKE_DIR/open_issue" 2>/dev/null ;;
    *) cat "$FAKE_DIR/last_issue" 2>/dev/null ;;
  esac
fi
if [ "$1 $2" = "issue create" ]; then echo 7 > "$FAKE_DIR/open_issue"; fi
if [ "$1 $2" = "issue close" ]; then rm -f "$FAKE_DIR/open_issue"; fi
exit 0
"""


@pytest.fixture
def watch(tmp_path):
    if not Path("/bin/bash").exists():
        pytest.skip("нужен bash")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "codes").mkdir()
    for name, text in (("curl", FAKE_CURL), ("gh", FAKE_GH)):
        f = bin_dir / name
        f.write_text(text)
        f.chmod(0o755)

    def run(prod: str, staging: str = "200") -> list[str]:
        """Один запуск сторожа; возвращает вызовы gh этого запуска (кроме поиска issue)."""
        (tmp_path / "codes" / "prod").write_text(prod)
        (tmp_path / "codes" / "staging").write_text(staging)
        log = tmp_path / "gh.log"
        log.write_text("")
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_DIR": str(tmp_path),
            "STATE_FILE": str(tmp_path / "state"),
            "REPO": "owner/repo",
        }
        res = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return [c for c in log.read_text().splitlines() if not c.startswith("api ")]

    run.dir = tmp_path
    return run


def test_all_up_is_silent(watch):
    assert watch("200") == []
    assert watch("200") == []


def test_one_failure_is_not_alarm(watch):
    # одна неудача — может быть сетевой мигание, не будим владельца
    assert watch("000") == []
    assert watch("200") == []
    assert watch("000") == []


def test_two_failures_open_issue_then_recovery_closes(watch):
    assert watch("000") == []
    calls = watch("502")
    assert any(c.startswith("label create outage") for c in calls)
    created = [c for c in calls if c.startswith("issue create")]
    assert len(created) == 1
    assert "Прод не отвечает с" in created[0] and "--label outage" in created[0]
    # дальше лежит — не спамим и второе issue не создаём
    assert watch("000") == []
    calls = watch("200")
    assert len(calls) == 1 and calls[0].startswith("issue close 7") and "Прод ответил" in calls[0]


def test_existing_open_issue_gets_comment_not_new_issue(watch):
    (watch.dir / "open_issue").write_text("3")
    watch("000")
    calls = watch("000")
    assert [c.split(" --")[0] for c in calls] == ["issue comment 3 -R owner/repo"]


def test_daily_reminder(watch):
    calls = [watch("000") for _ in range(2 + 48)]
    reminders = [c for run in calls for c in run if "всё ещё не отвечает" in c]
    assert len(reminders) == 1


def test_staging_only_comments(watch):
    (watch.dir / "last_issue").write_text("5")
    assert watch("200", "000") == []
    calls = watch("200", "000")
    assert len(calls) == 1 and calls[0].startswith("issue comment 5") and "Staging" in calls[0]
    calls = watch("200", "200")
    assert len(calls) == 1 and "Staging ответил" in calls[0]
    assert not any("issue create" in c for c in calls)


def test_staging_without_any_issue_only_warns(watch):
    watch("200", "000")
    assert watch("200", "000") == []
