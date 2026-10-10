"""tools/ の Codex ラッパーと鍵の入力スクリプトを、偽の codex と擬似端末で試す（本物の Codex・ネットワークは使わない）。"""
import json
import os
import pty
import shutil
import signal
import stat
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARK = "/Us" + "ers/someone/secret"  # 非公開の印は実行時に組み立てる（本文に置かない）

FAKE_CODEX = r"""#!/usr/bin/env bash
# 偽の codex: FAKE_MODE で振る舞いを変える。呼ばれた引数を記録する
echo "$*" >> "$FAKE_LOG"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
cat > /dev/null
G="git -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null"
case "$FAKE_MODE" in
  allowed) echo "VERSION_INFO = (0, 1, 0)" >> orch/__init__.py ;;
  outside) echo "x" >> README.md ;;
  private) printf 'P = "%s"\n' "$FAKE_MARK" >> orch/__init__.py ;;
  envfile) echo "X=1" >> .env ;;
  fail) exit 1 ;;
  fail_changed) echo "x = 1" >> orch/__init__.py; exit 1 ;;
  limit) echo "You've hit your usage limit. try again at 10:00" >&2; exit 1 ;;
  limit_dirty) echo "x" >> README.md; echo "try again at 10:00" >&2; exit 1 ;;
  ratelimit_ok) echo "VERSION_INFO = 1" >> orch/__init__.py; echo "rate limit を考慮しました" ;;
  widen) sed -i.bak 's#orch/__init__.py#orch/__init__.py\nREADME.md#' docs/specs/s.md; rm -f docs/specs/s.md.bak; echo x >> README.md ;;
  untracked_edit) printf '%s\n' "$FAKE_MARK" >> notes.md ;;
  ignored) mkdir -p data && echo "import os" > data/evil.pth ;;
  newdir) mkdir -p hidden && echo '*' > hidden/.gitignore && echo x > hidden/payload.py ;;
  commit) echo "x" >> README.md && $G add README.md && $G commit -q -m sneaky ;;
  rename) $G mv orch/__init__.py orch/renamed.py ;;
  tamper) printf 'import sys\nprint("scope_check: OK")\nsys.exit(0)\n' > tools/scope_check.py; echo x >> README.md ;;
  japanese) echo "追記" >> "docs/ルミナス メモ.md" ;;
  glob) echo "# glob" >> orch/config.py ;;
  pycache) mkdir -p orch/__pycache__ .pytest_cache && echo x > orch/__pycache__/evil.cpython-39.pyc && echo x > .pytest_cache/v ;;
  opinion) echo "意見です" ;;
  halt_during) mkdir -p data && printf '%s test\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > data/.luminous_halt; exit 1 ;;
  halt_eraser) trap 'rm -f data/.luminous_halt; exit 1' TERM; i=0; while [ "$i" -lt "${FAKE_ERASER_N:-300}" ]; do rm -f data/.luminous_halt; sleep 0.1; i=$((i+1)); done ;;
  nestedgit) git init -q . && printf '#!/bin/sh\ntouch "%s"\n' "$FAKE_PWNED" > .git/fsm.sh && chmod +x .git/fsm.sh && git config core.fsmonitor "$PWD/.git/fsm.sh" ;;
  nestedgit_sub) git init -q orch && printf '#!/bin/sh\ntouch "%s"\n' "$FAKE_PWNED" > orch/.git/fsm.sh && chmod +x orch/.git/fsm.sh && git -C orch config core.fsmonitor "$PWD/orch/.git/fsm.sh" ;;
  gitconfig) printf '#!/bin/sh\ntouch "%s"\n' "$FAKE_PWNED" > "$FAKE_PWNED.sh" && chmod +x "$FAKE_PWNED.sh" && git config core.fsmonitor "$FAKE_PWNED.sh" ;;
  pycache_link) ln -s "$FAKE_TARGET" orch/__pycache__ ;;
  pytestcache_file) echo x > .pytest_cache ;;
  syswrites) mkdir -p logs state/.sessions && echo '{"b":2}' >> data/usage.jsonl && echo "g" >> logs/gemini.log && : > logs/gemini.lock \
             && : > data/usage.lock && date +%s > state/.sessions/other.start && : > state/.sessions/other.edited && echo "VERSION_INFO = 2" >> orch/__init__.py ;;
  truncate_log) : > data/usage.jsonl ;;
  exec_log) chmod +x data/usage.jsonl ;;
  fifo) mkfifo orch/pipe ;;
  fifo_env) rm -f .env && mkfifo .env ;;
  envchmod) chmod 644 .env ;;
  newexec) echo "x" >> orch/__init__.py && chmod +x orch/__init__.py ;;
  sleep) sleep 30 ;;
  upper_git) mkdir -p .GIT && echo "ref: refs/heads/main" > .GIT/HEAD && printf '[core]\n\tfsmonitor = /bin/false\n' > .GIT/config ;;
  upper_git_sub) mkdir -p orch/.Git && echo "ref: refs/heads/main" > orch/.Git/HEAD ;;
  linger) echo "VERSION_INFO = 3" >> orch/__init__.py; ( sleep 2; echo late > "$PWD/orch/late.py" ) > /dev/null 2>&1 & ;;
  escape) echo "VERSION_INFO = 4" >> orch/__init__.py
          python3 -c 'import os, sys, time; os.setsid(); time.sleep(3); open(sys.argv[1], "w").write("late")' "$PWD/orch/late.py" > /dev/null 2>&1 &
          sleep 1 ;;  # 抜け出したプロセスが setsid を済ませてから終わる
  negative_usd) echo '{"ts": "2026-10-08T00:00:00+09:00", "vendor": "gemini", "usd": -100}' >> data/usage.jsonl ;;
  nan_usd) echo '{"ts": "2026-10-08T00:00:00+09:00", "vendor": "gemini", "usd": NaN}' >> data/usage.jsonl ;;
  badjson) echo 'not json' >> data/usage.jsonl ;;
  pending_inject) mkdir -p state/.sessions && printf 'x | %s\n' "$FAKE_MARK" >> state/.sessions/escalations.pending && echo "VERSION_INFO = 6" >> orch/__init__.py ;;
  start_rewind) echo 1 > state/.sessions/s.start ;;
  start_forward) echo 2000000100 > state/.sessions/s.start ;;
  start_text) mkdir -p state/.sessions && echo abc > state/.sessions/new.start ;;
  edited_content) mkdir -p state/.sessions && echo payload > state/.sessions/x.edited ;;
  lock_content) echo payload >> data/usage.lock ;;
  escalations) mkdir -p state && printf 'x | %s\n' "$FAKE_MARK" >> state/escalations.log && echo "VERSION_INFO = 5" >> orch/__init__.py ;;
esac
[ -n "$out" ] && echo "変更しました" > "$out"
exit 0
"""

SPEC = "# s\n<!-- ALLOWED -->\norch/__init__.py\n<!-- /ALLOWED -->\n"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", *args],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout


def _build(tmp_path, parent):
    """parent=True なら、リポジトリの根を1つ上に置き、ルミナスをその中のフォルダにする（GitHub の写しと同じ形）。"""
    top = tmp_path / "repo" if parent else tmp_path / "ルミナス"
    p = top / "ルミナス" if parent else top
    p.mkdir(parents=True)
    for d in ("tools", "orch", "scripts"):
        shutil.copytree(ROOT / d, p / d, ignore=shutil.ignore_patterns("__pycache__"))
    (p / "docs" / "specs").mkdir(parents=True)
    (p / "docs" / "astra-packets").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "external-allowlist.txt", p / "docs" / "external-allowlist.txt")
    (p / "docs" / "astra-packets" / "p.md").write_text("問い: この設計の穴は？\n", encoding="utf-8")
    (p / "docs" / "ルミナス メモ.md").write_text("メモ\n", encoding="utf-8")
    (p / "README.md").write_text("readme\n", encoding="utf-8")
    (p / ".gitignore").write_text(".env\ndata/\nlogs/\n__pycache__/\nnotes.md\nstate/\n", encoding="utf-8")
    (p / ".env").write_text("A=1\n", encoding="utf-8")
    (p / ".env").chmod(0o600)
    (p / "docs" / "specs" / "s.md").write_text(SPEC, encoding="utf-8")
    git(top, "init", "-q")
    git(top, "add", "-A")
    git(top, "commit", "-q", "-m", "init")
    (p / "notes.md").write_text("既存のメモ\n", encoding="utf-8")  # 実行前からある ignore 対象のファイル
    fake = tmp_path / "bin" / "codex"
    fake.parent.mkdir()
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cache = Path.home() / ".cache" / f"luminous-test-{uuid.uuid4().hex[:8]}"  # Codex が書けない場所（/tmp の外）
    return p, fake, tmp_path / "fake.log", cache


@pytest.fixture
def proj(tmp_path):
    t = _build(tmp_path, parent=False)
    yield t
    shutil.rmtree(t[3], ignore_errors=True)


@pytest.fixture
def proj_parent(tmp_path):
    t = _build(tmp_path, parent=True)
    yield t
    shutil.rmtree(t[3], ignore_errors=True)


def env_for(proj, mode, extra_env=None):
    p, fake, log, cache = proj
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_MODE=mode, FAKE_LOG=str(log), FAKE_MARK=MARK, XDG_CACHE_HOME=str(cache),
               FAKE_PWNED=str(log.parent / "pwned"), FAKE_TARGET=str(log.parent / "target"), LUMINOUS_SETTLE_S="0")
    env.pop("CODEX_FALLBACK_MODEL", None)
    env.update(extra_env or {})
    return env


def run(proj, mode, *, script="codex_impl.sh", args=("docs/specs/s.md", "low"), extra_env=None, timeout=120):
    return subprocess.run(["bash", f"tools/{script}", *args], cwd=proj[0], env=env_for(proj, mode, extra_env),
                          capture_output=True, text=True, timeout=timeout)


def calls(proj):
    return proj[2].read_text().splitlines() if proj[2].exists() else []


# ---- 成功 ----
def test_allowed_change_ok_and_ledger(proj, isolated_env):
    r = run(proj, "allowed")
    assert r.returncode == 0, r.stderr
    assert "scope_check: OK" in r.stdout
    rows = [json.loads(l) for l in (isolated_env / "data" / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["vendor"] == "codex" and rows[-1]["status"] == "ok"
    assert "model_reasoning_effort=low" in calls(proj)[0] and "--disable memories" in calls(proj)[0]
    assert "-s workspace-write" in calls(proj)[0] and "danger" not in calls(proj)[0]
    assert not list(proj[3].glob("luminous-codex/run.*"))  # 安全な置き場は片付ける


def test_rate_limit_word_in_successful_output_is_ok(proj):
    assert run(proj, "ratelimit_ok").returncode == 0


def test_japanese_path_in_allowed(proj):
    (proj[0] / "docs" / "specs" / "jp.md").write_text("<!-- ALLOWED -->\n- docs/ルミナス メモ.md\n<!-- /ALLOWED -->\n", encoding="utf-8")
    r = run(proj, "japanese", args=("docs/specs/jp.md", "low"))
    assert r.returncode == 0, r.stderr


def test_glob_bullet_in_allowed(proj):
    (proj[0] / "docs" / "specs" / "glob.md").write_text("<!-- ALLOWED -->\n- orch/*.py\n<!-- /ALLOWED -->\n", encoding="utf-8")
    assert run(proj, "glob", args=("docs/specs/glob.md", "low")).returncode == 0


def test_pycache_is_removed_not_flagged(proj):
    r = run(proj, "pycache")
    assert r.returncode == 0, r.stderr
    assert not (proj[0] / "orch" / "__pycache__").exists() and not (proj[0] / ".pytest_cache").exists()


# ---- 違反（3） ----
@pytest.mark.parametrize("mode", ["outside", "private", "envfile", "widen", "untracked_edit", "ignored", "newdir", "commit", "rename", "tamper"])
def test_violations_are_3(proj, mode):
    r = run(proj, mode)
    assert r.returncode == 3, (mode, r.stdout, r.stderr)


def test_private_marker_in_allowed_untracked_file(proj):
    (proj[0] / "docs" / "specs" / "notes.md").write_text("<!-- ALLOWED -->\nnotes.md\n<!-- /ALLOWED -->\n", encoding="utf-8")
    r = run(proj, "untracked_edit", args=("docs/specs/notes.md", "low"))
    assert r.returncode == 3 and "非公開の印" in r.stderr


def test_violation_takes_priority_over_limit(proj):
    r = run(proj, "limit_dirty")
    assert r.returncode == 3 and len(calls(proj)) == 1


# ---- 上限・失敗・やり直し ----
def test_usage_limit_is_4_without_retry(proj):
    r = run(proj, "limit")
    assert r.returncode == 4 and len(calls(proj)) == 1


def test_fail_unchanged_retries_with_default_fallback(proj):
    r = run(proj, "fail")
    c = calls(proj)
    assert r.returncode == 5 and len(c) == 2 and "-m gpt-5.6-sol" in c[1]


def test_fallback_can_be_disabled(proj):
    r = run(proj, "fail", extra_env={"CODEX_FALLBACK_MODEL": ""})
    assert r.returncode == 5 and len(calls(proj)) == 1


def test_fail_with_changes_does_not_retry(proj):
    r = run(proj, "fail_changed")
    assert r.returncode == 5 and len(calls(proj)) == 1


def test_fallback_from_dotenv(proj):
    with open(proj[0] / ".env", "a", encoding="utf-8") as fh:
        fh.write("CODEX_FALLBACK_MODEL=other-model\n")
    git(proj[0], "status")  # .env は ignore 対象なので作業ツリーは汚れない
    run(proj, "fail")
    assert "-m other-model" in calls(proj)[1]


# ---- 前提の誤り（2） ----
def test_stop_switch_file(proj):
    (proj[0] / "data").mkdir(exist_ok=True)
    (proj[0] / "data" / ".codex_disabled").touch()
    assert run(proj, "allowed").returncode == 2 and not calls(proj)


def test_stop_switch_from_dotenv(proj):
    with open(proj[0] / ".env", "a", encoding="utf-8") as fh:
        fh.write("ORCH_CODEX=0\n")
    assert run(proj, "allowed").returncode == 2 and not calls(proj)


def test_dirty_tree_is_2(proj):
    (proj[0] / "README.md").write_text("dirty\n", encoding="utf-8")
    r = run(proj, "allowed")
    assert r.returncode == 2 and "未コミット" in r.stderr


def test_empty_allowed_is_2_before_launch(proj):
    (proj[0] / "docs" / "specs" / "empty.md").write_text("<!-- ALLOWED -->\n<!-- /ALLOWED -->\n", encoding="utf-8")
    assert run(proj, "allowed", args=("docs/specs/empty.md", "low")).returncode == 2 and not calls(proj)


def test_live_lock_is_2(proj):
    lock = proj[0] / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    (lock / "owner").write_text(f"{os.getpid()} 0\n")
    assert run(proj, "allowed").returncode == 2


def test_stale_lock_is_reclaimed(proj):
    lock = proj[0] / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    dead = subprocess.Popen(["true"]); dead.wait()
    (lock / "owner").write_text(f"{dead.pid} 0\n")
    assert run(proj, "allowed").returncode == 0


def test_scope_check_allowed_requires_block(proj, tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# no allowed\n", encoding="utf-8")
    r = subprocess.run(["python3", str(proj[0] / "tools" / "scope_check.py"), "allowed", str(bad)], capture_output=True, text=True)
    assert r.returncode == 2


def test_added_lines_starting_with_plus():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", ROOT / "tools" / "scope_check.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    assert sc.added_lines("a\n", "a\n++" + MARK + "\n") == ["++" + MARK]


# ---- 2回目の審査で指摘された抜け道（入れ子の .git・リンク・同時書き込み・FIFO・権限・中断・ロック） ----
def quarantined(proj):
    return list((proj[3] / "luminous-codex" / "quarantine").glob("*/*"))


@pytest.mark.parametrize("mode", ["nestedgit", "nestedgit_sub"])
def test_nested_git_with_fsmonitor_is_quarantined_before_any_git(proj_parent, mode):
    p = proj_parent[0]
    r = run(proj_parent, mode)
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert not (p.parent.parent / "pwned").exists(), "入れ子の .git の fsmonitor が実行された"
    assert not (p / ".git").exists() and not (p / "orch" / ".git").exists()
    assert len(quarantined(proj_parent)) == 1
    assert (p / "data" / ".codex_violation").exists()


def test_nested_git_sub_in_root_layout(proj):
    r = run(proj, "nestedgit_sub")
    assert r.returncode == 3 and not (proj[0].parent / "pwned").exists() and not (proj[0] / "orch" / ".git").exists()


def test_real_git_config_change_is_3_and_git_is_not_run(proj):
    r = run(proj, "gitconfig")
    assert r.returncode == 3 and "設定" in r.stderr
    assert not (proj[0].parent / "pwned").exists()


@pytest.mark.parametrize("where", ["orch/.git", ".git"])
def test_existing_nested_git_refuses_before_launch(proj_parent, where):
    (proj_parent[0] / where).mkdir()
    r = run(proj_parent, "allowed")
    assert r.returncode == 2 and ".git" in r.stderr and not calls(proj_parent)


def test_pycache_symlink_is_violation_and_link_removed(proj):
    target = proj[0].parent / "target"
    target.mkdir()
    (target / "keep.txt").write_text("消えないこと\n", encoding="utf-8")
    r = run(proj, "pycache_link")
    assert r.returncode == 3 and "__pycache__" in r.stderr
    assert not os.path.lexists(proj[0] / "orch" / "__pycache__")
    assert (target / "keep.txt").exists()


def test_pytest_cache_as_file_is_violation(proj):
    r = run(proj, "pytestcache_file")
    assert r.returncode == 3 and not os.path.lexists(proj[0] / ".pytest_cache")


def _seed_ledger(p):
    (p / "data").mkdir(exist_ok=True)
    (p / "data" / "usage.jsonl").write_text('{"a":1}\n', encoding="utf-8")


def test_concurrent_system_writes_are_not_violations(proj):
    _seed_ledger(proj[0])
    r = run(proj, "syswrites")
    assert r.returncode == 0, r.stderr
    assert "orch/__init__.py" in r.stdout


@pytest.mark.parametrize("mode", ["truncate_log", "exec_log"])
def test_ledger_rewrite_or_exec_is_violation(proj, mode):
    _seed_ledger(proj[0])
    r = run(proj, mode)
    assert r.returncode == 3, r.stderr


@pytest.mark.parametrize("mode", ["fifo", "fifo_env"])
def test_fifo_is_violation_without_hang(proj, mode):
    r = run(proj, mode, timeout=90)
    assert r.returncode == 3, r.stderr


def test_env_mode_change_is_violation(proj):
    r = run(proj, "envchmod")
    assert r.returncode == 3 and ".env" in r.stderr


def test_new_exec_bit_is_violation(proj):
    r = run(proj, "newexec")
    assert r.returncode == 3 and "実行権限" in r.stderr


def test_violation_marker_blocks_next_run(proj):
    assert run(proj, "outside").returncode == 3
    r = run(proj, "allowed")
    assert r.returncode == 2 and ".codex_violation" in r.stderr and len(calls(proj)) == 1


def test_sigterm_removes_safe_dir_and_releases_lock(proj):
    p, _, log, cache = proj
    proc = subprocess.Popen(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p, env=env_for(proj, "sleep"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.time() + 30
    while time.time() < deadline and not (log.exists() and log.read_text().strip()):
        time.sleep(0.1)
    assert log.exists(), "偽の codex が起動しなかった"
    time.sleep(0.3)
    os.killpg(proc.pid, signal.SIGTERM)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 130, (out, err)
    assert not list((cache / "luminous-codex").glob("run.*"))
    assert not (p / "data" / "codex_runs" / ".lock").exists()


def test_live_old_lock_is_not_reclaimed(proj):
    lock = proj[0] / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    (lock / "owner").write_text(f"{os.getpid()} 0\n")
    old = time.time() - 3 * 3600
    os.utime(lock, (old, old))
    r = run(proj, "allowed")
    assert r.returncode == 2 and not calls(proj) and lock.exists()


def test_lock_without_owner_is_not_reclaimed(proj):
    lock = proj[0] / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    assert run(proj, "allowed").returncode == 2 and lock.exists() and not calls(proj)


def test_spec_name_starting_with_dash_records_purpose(proj, isolated_env):
    (proj[0] / "docs" / "specs" / "-dash.md").write_text(SPEC, encoding="utf-8")
    r = run(proj, "allowed", args=("docs/specs/-dash.md", "low"))
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in (isolated_env / "data" / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["purpose"] == "-dash"


def test_parent_layout_allowed_change_ok(proj_parent):
    r = run(proj_parent, "allowed")
    assert r.returncode == 0, r.stderr


# ---- 3回目の審査で指摘された抜け道（大文字小文字の .git・追跡中の追記ファイル・残ったプロセス・台帳の数値） ----
@pytest.mark.parametrize("mode,where", [("upper_git", ".GIT"), ("upper_git_sub", "orch/.Git")])
def test_case_variant_git_is_quarantined(proj_parent, mode, where):
    p = proj_parent[0]
    r = run(proj_parent, mode)
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert not os.path.lexists(p / where) and len(quarantined(proj_parent)) == 1


def test_case_variant_git_refuses_before_launch(proj):
    (proj[0] / "orch" / ".GIT").mkdir()
    r = run(proj, "allowed")
    assert r.returncode == 2 and not calls(proj)


def test_scope_check_git_name_is_case_insensitive(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", ROOT / "tools" / "scope_check.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    for name in (".GIT", ".Git", ".gIt"):
        d = tmp_path / name.strip(".")
        (d / name).mkdir(parents=True)
        assert sc.find_git(str(d)) == [name]
        assert sc.snapshot(str(d))["files"][name]["t"] == "git"


@pytest.mark.parametrize("mode", ["negative_usd", "nan_usd", "badjson"])
def test_bad_ledger_append_is_violation(proj, mode):
    _seed_ledger(proj[0])
    r = run(proj, mode)
    assert r.returncode == 3, (r.stdout, r.stderr)


def test_append_to_tracked_escalations_log_is_violation(proj):
    r = run(proj, "escalations")
    assert r.returncode == 3 and "state/escalations.log" in r.stderr


def test_append_only_files_are_all_gitignored():
    """追記だけを許すファイルは公開されない（git の管理外）こと。追跡中のファイルを入れると非公開の印の検査を抜けるため。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", ROOT / "tools" / "scope_check.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    samples = sorted(sc.APPEND_ONLY) + ["logs/gemini.log", "data/usage.lock", "logs/jev.lock", "state/.sessions/x.start", "data/.gemini_disabled"]
    for rel in samples:
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT)
        assert r.returncode == 0, f"{rel} が .gitignore に入っていない"


def test_lingering_child_is_stopped_with_codex(proj):
    r = run(proj, "linger")
    assert r.returncode == 0, r.stderr
    time.sleep(3)
    assert not (proj[0] / "orch" / "late.py").exists(), "Codex の子プロセスが終了後に書き込んだ"


def test_escaped_late_writer_is_detected(proj):
    r = run(proj, "escape", extra_env={"LUMINOUS_SETTLE_S": "2"})
    assert r.returncode == 3, (r.stdout, r.stderr)


def test_ok_output_lists_system_file_changes(proj):
    _seed_ledger(proj[0])
    r = run(proj, "syswrites")
    assert r.returncode == 0 and "記録ファイルの追記" in r.stdout and "data/usage.jsonl" in r.stdout


# ---- 4回目の審査で指摘された抜け道（保留の記録・印のファイルの中身・HFS+ の無視される文字） ----
def _seed_markers(p):
    (p / "state" / ".sessions").mkdir(parents=True, exist_ok=True)
    (p / "state" / ".sessions" / "s.start").write_text("2000000000\n", encoding="utf-8")
    (p / "data").mkdir(exist_ok=True)
    (p / "data" / "usage.lock").write_text("", encoding="utf-8")


@pytest.mark.parametrize("mode", ["pending_inject", "start_rewind", "start_text", "edited_content", "lock_content"])
def test_marker_content_tampering_is_violation(proj, mode):
    _seed_markers(proj[0])
    r = run(proj, mode)
    assert r.returncode == 3, (mode, r.stdout, r.stderr)


def test_start_marker_may_move_forward(proj):
    _seed_markers(proj[0])
    r = run(proj, "start_forward")
    assert r.returncode == 0, r.stderr


def test_git_name_ignores_hfs_ignorable_chars():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", ROOT / "tools" / "scope_check.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    assert sc.is_git_name(".g\u200cit") and sc.is_git_name("\ufeff.GIT") and sc.is_git_name(".gi\u206at")
    assert not sc.is_git_name(".github") and not sc.is_git_name(".gitignore")


# ---- 意見役 ----
def opinion(proj, packet, mode="opinion"):
    return run(proj, mode, script="codex_opinion.sh", args=(packet,))


def test_opinion_ok_uses_public_export_readonly(proj):
    r = opinion(proj, "docs/astra-packets/p.md")
    assert r.returncode == 0, r.stderr
    c = calls(proj)[0]
    assert "-s read-only" in c and "luminous-public." in c
    out = next((proj[0] / "docs" / "astra-replies").glob("*-p.md")).read_text(encoding="utf-8")
    assert "意見です" in out


@pytest.mark.parametrize("packet", ["README.md", "docs/astra-packets/../../README.md"])
def test_opinion_rejects_outside_paths(proj, packet):
    assert opinion(proj, packet).returncode == 2 and not calls(proj)


def test_opinion_rejects_symlink(proj):
    link = proj[0] / "docs" / "astra-packets" / "link.md"
    link.symlink_to(proj[0] / "README.md")
    assert opinion(proj, "docs/astra-packets/link.md").returncode == 2 and not calls(proj)


def test_opinion_rejects_private_marker(proj):
    (proj[0] / "docs" / "astra-packets" / "x.md").write_text(f"参照: {MARK}\n", encoding="utf-8")
    assert opinion(proj, "docs/astra-packets/x.md").returncode == 6 and not calls(proj)


# ---- 鍵の入力（擬似端末） ----
def run_tty(cmd, cwd, env, text, timeout=60):
    master, slave = pty.openpty()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.close(slave)
    time.sleep(0.3)
    os.write(master, text.encode())
    try:
        out, err = proc.communicate(timeout=timeout)
    finally:
        os.close(master)
    return proc.returncode, out.decode(), err.decode()


def test_set_env_key_refuses_non_tty(proj):
    r = subprocess.run(["bash", "tools/set_env_key.sh", "GEMINI_API_KEY"], cwd=proj[0], input="AIzaFAKE\n", capture_output=True, text=True)
    assert r.returncode == 2 and "端末から直接" in r.stderr


def test_set_env_key_writes_600_and_backs_up(proj, tmp_path):
    p = proj[0]
    (p / ".env").write_text("GEMINI_API_KEY=old" + "\n" + "ORCH_GEMINI=1\n", encoding="utf-8")  # 鍵の代入の形を本文に置かない
    (p / ".env").chmod(0o644)
    priv = tmp_path / "priv"
    new = "new" + "value" + "1234567890"
    env = dict(os.environ, LUMINOUS_PRIVATE_DIR=str(priv), ORCH_GEMINI="0", GEMINI_API_KEY="stale-shell-value")
    rc, out, err = run_tty(["bash", "tools/set_env_key.sh", "GEMINI_API_KEY"], p, env, new + "\n")
    assert rc == 0, err
    text = (p / ".env").read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={new}" in text and "GEMINI_API_KEY=old" not in text and "ORCH_GEMINI=1" in text
    assert stat.S_IMODE((p / ".env").stat().st_mode) == 0o600
    backups = list((priv / "env_backups").glob(".env.bak.*"))
    assert len(backups) == 1 and "GEMINI_API_KEY=old" in backups[0].read_text(encoding="utf-8")
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600 and stat.S_IMODE(priv.stat().st_mode) == 0o700
    assert new not in out and new not in err


def test_set_env_key_stops_if_backup_fails(proj, tmp_path):
    p = proj[0]
    (p / ".env").write_text("GEMINI_API_KEY=old\n", encoding="utf-8")
    blocker = tmp_path / "priv"
    blocker.write_text("ファイルなので mkdir できない", encoding="utf-8")
    env = dict(os.environ, LUMINOUS_PRIVATE_DIR=str(blocker), ORCH_GEMINI="0")
    rc, out, err = run_tty(["bash", "tools/set_env_key.sh", "GEMINI_API_KEY"], p, env, "newvalue\n")
    assert rc == 1 and (p / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=old\n"


# ---- 全体停止（docs/specs/20261008_global_halt.md）----
import hashlib
import signal
import time


def _halt_path(proj):
    return proj[0] / "data" / ".luminous_halt"


def _make_halt(proj, text="2026-10-10T00:00:00Z 試験\n"):
    _halt_path(proj).parent.mkdir(exist_ok=True)
    _halt_path(proj).write_text(text, encoding="utf-8")


def _halt_cmd(proj, *args, stdin=subprocess.DEVNULL):
    return subprocess.run(["bash", "tools/luminous_halt.sh", *args], cwd=proj[0], env=env_for(proj, "x"),
                          capture_output=True, text=True, stdin=stdin, timeout=90)


def _safe_halt_log(proj):
    return proj[3] / "luminous-codex" / "halt.log"


def _wait_launch(proj, timeout=30):
    """偽の codex が起動した（引数を記録した）まで待つ。起動の前に印を作ると、ラッパーは起動せずに 7 で終わるため"""
    log = proj[2]
    for _ in range(timeout * 10):
        if log.exists() and log.read_text().strip():
            return
        time.sleep(0.1)
    raise AssertionError("偽の codex が起動しない")


def _wait_owner(p, timeout=20):
    owner = p / "data" / "codex_runs" / ".lock" / "owner"
    for _ in range(timeout * 10):
        if owner.exists() and owner.read_text().strip():
            return owner
        time.sleep(0.1)
    raise AssertionError("ロックの持ち主が書かれない")


def test_halt_marker_before_run_is_7_without_launch(proj):
    _make_halt(proj)
    r = run(proj, "allowed")
    assert r.returncode == 7 and "全体停止中" in r.stderr, (r.stdout, r.stderr)
    assert calls(proj) == [] and not (proj[0] / "data" / "codex_runs" / ".lock").exists()


def test_halt_marker_as_dangling_symlink_is_7(proj):
    (proj[0] / "data").mkdir(exist_ok=True)
    os.symlink("/nonexistent/luminous-halt-target", _halt_path(proj))
    r = run(proj, "allowed")
    assert r.returncode == 7 and calls(proj) == []


def test_halt_created_during_run_is_7_without_retry_or_violation(proj):
    r = run(proj, "halt_during", extra_env={"CODEX_FALLBACK_MODEL": "gpt-5.6-sol"})
    assert r.returncode == 7, (r.stdout, r.stderr)
    assert len(calls(proj)) == 1  # 失敗しても別のモデルでやり直さない
    assert not (proj[0] / "data" / ".codex_violation").exists()  # 印の作成は違反ではない
    assert _halt_path(proj).exists()


@pytest.mark.parametrize("own_session", [False, True])
def test_halt_terminated_impl_wrapper_exits_7(proj, tmp_path, own_session):
    p = proj[0]
    proc = subprocess.Popen(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p, env=env_for(proj, "sleep"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=own_session)
    try:
        _wait_launch(proj)
        time.sleep(0.3)
        t0 = time.monotonic()
        r = _halt_cmd(proj, "on", "試験で止める")
        assert r.returncode == 0 and "TERM を送りました" in r.stdout, (r.stdout, r.stderr)
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 7, (out, err)
    assert time.monotonic() - t0 < 25  # 偽の codex（sleep 30）を待たずに止めた
    assert not (p / "data" / "codex_runs" / ".lock").exists()
    assert not (p / "data" / ".codex_violation").exists()  # 印は残っているので違反ではない
    assert _halt_path(proj).exists() and "再作成" not in _halt_path(proj).read_text(encoding="utf-8")
    assert len(calls(proj)) == 1
    assert _safe_halt_log(proj).read_text(encoding="utf-8").count(" on ") == 1
    rows = [json.loads(l) for l in (tmp_path / "data" / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["vendor"] == "codex" and rows[-1]["status"] == "error" and rows[-1]["purpose"] == "s"  # 起動はした


def test_halt_eraser_codex_deleting_marker_is_violation_and_marker_recreated(proj):
    """実行中の Codex が印を消し続ける: ラッパーは安全な置き場の halt.log と突き合わせて違反（3）、
    luminous_halt.sh は印を作り直して 3 を返す。"""
    p = proj[0]
    proc = subprocess.Popen(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p, env=env_for(proj, "halt_eraser"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_launch(proj)
        time.sleep(0.3)
        r = _halt_cmd(proj, "on", "消す Codex を止める")
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 3 and "Codex が消した疑い" in err, (out, err)
    assert _halt_path(proj).exists() and "Codex が消した疑い" in _halt_path(proj).read_text(encoding="utf-8")  # ラッパーが作り直した
    assert r.returncode == 0 and "TERM を送りました" in r.stdout and "作り直しました" not in r.stderr, (r.stdout, r.stderr)  # 終了を待った時点で印はある
    assert (p / "data" / ".codex_violation").exists()
    assert not (p / "data" / "codex_runs" / ".lock").exists()
    assert (p / "logs" / "halt.log").read_text(encoding="utf-8").count(" on ") == 1
    assert _safe_halt_log(proj).read_text(encoding="utf-8").count(" on ") == 1
    assert len(calls(proj)) == 1  # やり直しはしない


def test_halt_eraser_env_mismatch_falls_back_to_recreate_by_halt_script(proj):
    """ラッパーの安全な置き場が halt スクリプトと別（環境変数の不一致）だと、ラッパー側の突き合わせは効かない。
    その場合も TERM の後の after_term が印を作り直し、3 で知らせる。"""
    p = proj[0]
    other = Path.home() / ".cache" / f"luminous-test-{uuid.uuid4().hex[:8]}"
    proc = subprocess.Popen(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p,
                            env=env_for(proj, "halt_eraser", {"XDG_CACHE_HOME": str(other)}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_launch(proj)
        time.sleep(0.3)
        r = _halt_cmd(proj, "on", "置き場が別")
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(other, ignore_errors=True)
    assert r.returncode == 3 and "TERM を送りました" in r.stdout and "作り直しました" in r.stderr, (r.stdout, r.stderr)
    assert proc.returncode in (7, 130) and "Codex が消した疑い" not in err, (out, err)  # ラッパーは気づけない
    assert not (p / "data" / ".codex_violation").exists()
    assert _halt_path(proj).exists() and "TERM の後に印が消えていた" in _halt_path(proj).read_text(encoding="utf-8")
    assert (p / "logs" / "halt.log").read_text(encoding="utf-8").count(" on ") == 2


def test_halt_wrapper_launched_from_parent_dir_detects_erased_marker_without_term(proj):
    """親フォルダから相対パスで起動されたラッパーには TERM を送らない（実パスが一致しない。安全側）。
    それでもラッパーは実行後に安全な置き場の halt.log と突き合わせ、消された印を違反にして作り直す。"""
    p = proj[0]
    proc = subprocess.Popen(["bash", "ルミナス/tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p.parent,
                            env=env_for(proj, "halt_eraser", {"FAKE_ERASER_N": "40"}),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_launch(proj)
        time.sleep(0.3)
        r = _halt_cmd(proj, "on", "親から起動")
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert r.returncode == 0 and "送りません" in r.stdout and "送りました" not in r.stdout, (r.stdout, r.stderr)
    assert proc.returncode == 3 and "Codex が消した疑い" in err, (out, err)
    assert _halt_path(proj).exists() and "Codex が消した疑い" in _halt_path(proj).read_text(encoding="utf-8")
    assert (p / "data" / ".codex_violation").exists()
    assert not (p / "data" / "codex_runs" / ".lock").exists()


def test_luminous_halt_off_refused_while_codex_running(proj):
    p = proj[0]
    proc = subprocess.Popen(["bash", "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p, env=env_for(proj, "sleep"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_launch(proj)
        _make_halt(proj)
        rc, out, err = run_tty(["bash", "tools/luminous_halt.sh", "off"], p, env_for(proj, "x"), "解除\n")
        assert rc == 2 and "実行中" in err and _halt_path(proj).exists(), (out, err)
        proc.send_signal(signal.SIGTERM)
        o, e = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 7, (o, e)
    rc, out, err = run_tty(["bash", "tools/luminous_halt.sh", "off"], p, env_for(proj, "x"), "解除\n")
    assert rc == 0 and not _halt_path(proj).exists(), (out, err)  # ラッパーが終われば解除できる


def test_opinion_halt_before_is_7(proj):
    _make_halt(proj)
    r = opinion(proj, "docs/astra-packets/p.md")
    assert r.returncode == 7 and calls(proj) == [], (r.stdout, r.stderr)
    assert not (proj[0] / "data" / "codex_runs" / ".lock").exists()


def test_opinion_term_stops_group_and_releases_lock(proj):
    p = proj[0]
    proc = subprocess.Popen(["bash", "tools/codex_opinion.sh", "docs/astra-packets/p.md"], cwd=p, env=env_for(proj, "sleep"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_launch(proj)
        time.sleep(0.3)
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 130, (out, err)
    assert time.monotonic() - t0 < 15  # グループごと止めたので sleep 30 を待たない
    assert not (p / "data" / "codex_runs" / ".lock").exists()
    assert not (p / "data" / ".codex_violation").exists()


def test_luminous_halt_on_status_and_nontty_off(proj):
    p = proj[0]
    r = _halt_cmd(proj, "on", "試験の理由")
    assert r.returncode == 0 and _halt_path(proj).exists(), (r.stdout, r.stderr)
    assert "試験の理由" in _halt_path(proj).read_text(encoding="utf-8")
    assert (p / "logs" / "halt.log").read_text(encoding="utf-8").count(" on ") == 1
    assert _safe_halt_log(proj).read_text(encoding="utf-8").count(" on ") == 1  # Codex が書けない置き場にも同じ記録
    s = _halt_cmd(proj, "status")
    assert "全体停止中" in s.stdout and "試験の理由" in s.stdout
    again = _halt_cmd(proj, "on", "二度目")
    assert again.returncode == 0 and "既に" in again.stdout and "試験の理由" in _halt_path(proj).read_text(encoding="utf-8")
    off = _halt_cmd(proj, "off")
    assert off.returncode == 2 and _halt_path(proj).exists()  # 端末でなければ消さない
    assert not (p / "state" / "halt.log").exists()


def test_luminous_halt_reason_is_treated_as_data(proj):
    r = _halt_cmd(proj, "on", "a\x1b[31mb\nc" + "長" * 300)
    assert r.returncode == 0
    text = _halt_path(proj).read_text(encoding="utf-8")
    assert "\x1b" not in text and text.count("\n") == 1 and len(text) < 260


def test_luminous_halt_on_without_reason(proj):
    r = _halt_cmd(proj, "on")
    assert r.returncode == 0 and _halt_path(proj).exists(), (r.stdout, r.stderr)
    assert "(理由なし)" in _halt_path(proj).read_text(encoding="utf-8")
    assert "(理由なし)" in _halt_cmd(proj, "status").stdout


def test_luminous_halt_reason_strips_c1_and_format_chars(proj):
    r = _halt_cmd(proj, "on", "a\u0085b\u202ec\u200bd\u2028e\tf")
    assert r.returncode == 0
    text = _halt_path(proj).read_text(encoding="utf-8")
    for ch in "\u0085\u202e\u200b\u2028\t":
        assert ch not in text
    assert "abcdef" in text


def test_luminous_halt_off_in_tty_requires_confirmation(proj):
    p = proj[0]
    _make_halt(proj, "2026-10-10T00:00:00Z 端末の試験\n")
    env = env_for(proj, "x")
    rc, out, err = run_tty(["bash", "tools/luminous_halt.sh", "off"], p, env, "いいえ\n")
    assert rc == 2 and _halt_path(proj).exists() and "中止" in out, (out, err)
    assert not (p / "state" / "halt.log").exists()
    rc, out, err = run_tty(["bash", "tools/luminous_halt.sh", "off"], p, env, "解除\n")
    assert rc == 0 and not _halt_path(proj).exists() and "解除しました" in out, (out, err)
    rec = " off 2026-10-10T00:00:00Z 端末の試験"  # 印の 1 行目（on の日時と理由）をそのまま記録する
    assert rec in (p / "state" / "halt.log").read_text(encoding="utf-8")
    assert rec in (p / "logs" / "halt.log").read_text(encoding="utf-8")
    assert rec in _safe_halt_log(proj).read_text(encoding="utf-8")
    assert "全体停止ではありません" in _halt_cmd(proj, "status").stdout
    assert _halt_cmd(proj, "off").returncode == 0  # 印が無ければ何もしないで 0


def test_luminous_halt_reports_when_marker_cannot_be_made(proj):
    p = proj[0]
    if (p / "data").exists():
        shutil.rmtree(p / "data")
    (p / "data").write_text("not a dir\n", encoding="utf-8")  # data が作れない
    r = _halt_cmd(proj, "on", "x")
    assert r.returncode == 1 and "止まっていません" in r.stderr


@pytest.mark.parametrize("owner_pid", ["-1", "0", "abc", "SLEEP", "999999999"])
def test_luminous_halt_does_not_term_bad_owner(proj, owner_pid):
    p = proj[0]
    lock = p / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        pid = str(sleeper.pid) if owner_pid == "SLEEP" else owner_pid
        (lock / "owner").write_text(f"{pid} {int(time.time())}\n", encoding="utf-8")
        r = _halt_cmd(proj, "on", "x")
        assert r.returncode == 0 and "送りません" in r.stdout and "送りました" not in r.stdout, (r.stdout, r.stderr)
        time.sleep(0.3)
        assert sleeper.poll() is None  # 無関係のプロセスは生きている
    finally:
        sleeper.kill(); sleeper.wait()


def test_luminous_halt_waits_for_owner_then_declines(proj):
    p = proj[0]
    (p / "data" / "codex_runs" / ".lock").mkdir(parents=True)  # 持ち主がまだ書かれていないロック
    t0 = time.monotonic()
    r = _halt_cmd(proj, "on", "x")
    assert r.returncode == 0 and "持ち主の記録が無い" in r.stdout and time.monotonic() - t0 >= 0.9


def test_luminous_halt_reads_owner_written_late(proj):
    """ロックはあるが持ち主がまだ書かれていない → 1 秒待って読み直す。その PID がラッパーでなければ送らない。"""
    p = proj[0]
    lock = p / "data" / "codex_runs" / ".lock"
    lock.mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        import threading
        threading.Timer(0.4, lambda: (lock / "owner").write_text(f"{sleeper.pid} {int(time.time())}\n", encoding="utf-8")).start()
        r = _halt_cmd(proj, "on", "x")
        assert r.returncode == 0 and "ラッパー（bash）ではない" in r.stdout and "送りました" not in r.stdout, (r.stdout, r.stderr)
        assert "持ち主の記録が無い" not in r.stdout  # 遅れて書かれた持ち主を読めた
        time.sleep(0.3)
        assert sleeper.poll() is None
    finally:
        sleeper.kill(); sleeper.wait()


def _launcher_code(script):
    """ラッパーの起動用 python（setsid の後・execv の前に印を見る）の本文を取り出す。両ラッパーで同じ文であること"""
    line = next(l for l in (ROOT / "tools" / script).read_text(encoding="utf-8").splitlines() if "os.setsid()" in l and "os.execv" in l)
    return line.split("-c '", 1)[1].split("'", 1)[0]


def test_launcher_checks_marker_after_setsid_before_exec(tmp_path):
    code = _launcher_code("codex_impl.sh")
    assert code == _launcher_code("codex_opinion.sh")
    marker = tmp_path / ".luminous_halt"
    launched = tmp_path / "launched"
    cmd = [os.path.realpath(ROOT / ".venv" / "bin" / "python"), "-I", "-S", "-c", code, str(marker), "/bin/sh", "-c", f"touch '{launched}'"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and launched.exists(), (r.stdout, r.stderr)  # 印が無ければ起動する
    launched.unlink()
    os.symlink("/nonexistent/halt-target", marker)  # 先の無いリンクでも停止中
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 7 and not launched.exists(), (r.stdout, r.stderr)  # 印があれば exec せずに 7


def test_scope_check_halt_marker_create_ok_delete_violation(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", ROOT / "tools" / "scope_check.py")
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    (tmp_path / "data").mkdir()
    f = tmp_path / "data" / ".luminous_halt"
    f.write_text("2026-10-10T00:00:00Z 理由\n", encoding="utf-8")
    b = f.read_bytes()
    a = {"t": "file", "m": 0o644, "n": len(b), "h": hashlib.sha256(b).hexdigest()}
    assert sc.is_system("data/.luminous_halt")
    assert sc.system_change_problem(str(tmp_path), "data/.luminous_halt", None, a) == ""  # 中身のある新規作成は可
    assert "削除" in sc.system_change_problem(str(tmp_path), "data/.luminous_halt", a, None)  # 消すのは違反

