"""tools/ の Codex ラッパーと scope_check を、偽の codex で試す（本物の Codex・ネットワークは使わない）。"""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FAKE_CODEX = r"""#!/usr/bin/env bash
# 偽の codex: FAKE_MODE で振る舞いを変える。呼ばれた回数とモデルを記録する
echo "$*" >> "$FAKE_LOG"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
cat > /dev/null
case "$FAKE_MODE" in
  allowed) echo "VERSION = '0.1.1'" >> orch/__init__.py ;;
  outside) echo "x" >> README.md ;;
  private) printf 'P = "%s/someone/secret"\n' "/Us""ers" >> orch/__init__.py ;;
  envfile) echo "X=1" >> .env ;;
  fail) exit 1 ;;
  limit) echo "You've hit your usage limit. try again at 10:00" >&2; exit 1 ;;
esac
[ -n "$out" ] && echo "変更しました" > "$out"
exit 0
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "ルミナス"
    p.mkdir()
    for d in ("tools", "orch", "scripts"):
        shutil.copytree(ROOT / d, p / d, ignore=shutil.ignore_patterns("__pycache__"))
    (p / "docs" / "specs").mkdir(parents=True)
    (p / "README.md").write_text("readme\n", encoding="utf-8")
    (p / ".gitignore").write_text(".env\ndata/\nlogs/\n__pycache__/\n", encoding="utf-8")
    (p / ".env").write_text("A=1\n", encoding="utf-8")
    (p / "docs" / "specs" / "s.md").write_text("# s\n<!-- ALLOWED -->\norch/__init__.py\n<!-- /ALLOWED -->\n", encoding="utf-8")
    git(p, "init", "-q")
    git(p, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(p, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "init")
    fake = tmp_path / "bin" / "codex"
    fake.parent.mkdir()
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return p, fake, tmp_path / "fake.log"


def run_impl(proj, mode, *, extra_env=None):
    p, fake, log = proj
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_MODE=mode, FAKE_LOG=str(log))
    env.update(extra_env or {})
    return subprocess.run(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p, env=env, capture_output=True, text=True)


def test_allowed_change_ok(proj, isolated_env):
    r = run_impl(proj, "allowed")
    assert r.returncode == 0, r.stderr
    assert "scope_check: OK" in r.stdout
    rows = [json.loads(l) for l in (isolated_env / "data" / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["vendor"] == "codex" and rows[-1]["status"] == "ok"
    assert "model_reasoning_effort=low" in proj[2].read_text() and "--disable memories" in proj[2].read_text()


def test_outside_allowed_is_3(proj):
    assert run_impl(proj, "outside").returncode == 3


def test_private_marker_is_3(proj):
    r = run_impl(proj, "private")
    assert r.returncode == 3 and "非公開の印" in r.stderr


def test_env_change_is_3(proj):
    assert run_impl(proj, "envfile").returncode == 3


def test_usage_limit_is_4_without_retry(proj):
    r = run_impl(proj, "limit", extra_env={"CODEX_FALLBACK_MODEL": "gpt-5.6-sol"})
    assert r.returncode == 4 and len(proj[2].read_text().splitlines()) == 1


def test_fail_unchanged_retries_once_with_fallback(proj):
    r = run_impl(proj, "fail", extra_env={"CODEX_FALLBACK_MODEL": "gpt-5.6-sol"})
    calls = proj[2].read_text().splitlines()
    assert r.returncode == 5 and len(calls) == 2 and "-m gpt-5.6-sol" in calls[1]


def test_stop_switch_is_2(proj):
    p = proj[0]
    (p / "data").mkdir(exist_ok=True)
    (p / "data" / ".codex_disabled").touch()
    assert run_impl(proj, "allowed").returncode == 2


def test_dirty_tree_is_2(proj):
    (proj[0] / "README.md").write_text("dirty\n", encoding="utf-8")
    r = run_impl(proj, "allowed")
    assert r.returncode == 2 and "未コミット" in r.stderr


def test_lock_held_is_2(proj):
    (proj[0] / "data" / "codex_runs" / ".lock").mkdir(parents=True)
    assert run_impl(proj, "allowed").returncode == 2


def test_scope_check_requires_allowed(proj):
    p = proj[0]
    (p / "docs" / "specs" / "bad.md").write_text("# no allowed\n", encoding="utf-8")
    r = subprocess.run(["python3", "tools/scope_check.py", "docs/specs/bad.md"], cwd=p, capture_output=True, text=True)
    assert r.returncode == 2


def test_set_env_key_refuses_non_tty(proj):
    r = subprocess.run(["bash", "tools/set_env_key.sh", "GEMINI_API_KEY"], cwd=proj[0], input="AIzaFAKE\n", capture_output=True, text=True)
    assert r.returncode == 2 and "端末から直接" in r.stderr
