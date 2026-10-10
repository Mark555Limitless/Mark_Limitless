"""Mac への切替の監査（B 群: tools/・orch/）で直した点の試験。本物の Codex・ネットワークは使わない。

Mac の振る舞い（動かない /usr/bin/python3 のスタブ・Finder の .DS_Store・NFD で保存された名前・export された CDPATH・
使い回された PID・~/Applications の ChatGPT.app・requests の無い python3・LibreSSL の警告）は、一時フォルダと PATH の先頭の shim で模す。
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
import typing
import unicodedata
import uuid
from pathlib import Path

import pytest

from tests.test_tools import GIT_ENV, git, run_tty  # 試験の補助は test_tools と共有する（写しのずれを防ぐ。利用者の git 設定や pty の EIO の扱いも同じにする）

ROOT = Path(__file__).resolve().parents[1]
# LUMINOUS_TEST_BASH で別の bash（クラウドで作った 3.2 など）を指定できる（tests/test_tools.py と同じ。名前は bash のまま）
BASH = os.environ.get("LUMINOUS_TEST_BASH") or "/bin/bash"
assert os.path.basename(BASH) == "bash", BASH
SPEC = "# s\n<!-- ALLOWED -->\norch/__init__.py\n<!-- /ALLOWED -->\n"
APP_REL = Path("ChatGPT.app") / "Contents" / "Resources" / "codex-cli" / "bin" / "codex"

FAKE_CODEX = r"""#!/usr/bin/env bash
# 偽の codex: FAKE_MODE で振る舞いを変える。呼ばれた引数を記録する
echo "$*" >> "$FAKE_LOG"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
cat > /dev/null
case "$FAKE_MODE" in
  allowed) echo "VERSION_INFO = (0, 1, 0)" >> orch/__init__.py ;;
  dsstore) printf 'Bud1\000\000\000\001' > .DS_Store && printf 'Bud1\000\000\000\001' > docs/.DS_Store && echo "VERSION_INFO = 7" >> orch/__init__.py ;;
  dsstore_exec) printf 'Bud1' > docs/.DS_Store && chmod +x docs/.DS_Store && echo "VERSION_INFO = 8" >> orch/__init__.py ;;
  sleep) sleep "${FAKE_SLEEP:-5}" ;;
esac
[ -n "$out" ] && echo "変更しました" > "$out"
exit 0
"""

BROKEN_PY = "#!/bin/sh\n# Mac のコマンドラインツールが無いときの /usr/bin/python3 と同じ: 何も出さずに失敗する\necho 'xcode-select: note: No developer tools were found' >&2\nexit 1\n"



def _exe(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def proj(tmp_path):
    """作業フォルダの写し（リポジトリの根 = ルミナス）・偽の codex・呼び出しの記録・Codex が書けない置き場（/tmp の外）。"""
    p = tmp_path / "ルミナス"
    p.mkdir()
    for d in ("tools", "orch", "scripts"):
        shutil.copytree(ROOT / d, p / d, ignore=shutil.ignore_patterns("__pycache__"))
    (p / "docs" / "specs").mkdir(parents=True)
    (p / "docs" / "astra-packets").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "external-allowlist.txt", p / "docs" / "external-allowlist.txt")
    (p / "docs" / "astra-packets" / "p.md").write_text("問い: この設計の穴は？\n", encoding="utf-8")
    (p / "README.md").write_text("readme\n", encoding="utf-8")
    (p / ".gitignore").write_text(".env\ndata/\nlogs/\n__pycache__/\nstate/\n.DS_Store\n", encoding="utf-8")
    (p / ".env").write_text("A=1\n", encoding="utf-8")
    (p / ".env").chmod(0o600)
    (p / "docs" / "specs" / "s.md").write_text(SPEC, encoding="utf-8")
    git(p, "init", "-q")
    git(p, "add", "-A")
    git(p, "commit", "-q", "-m", "init")
    fake = _exe(tmp_path / "bin" / "codex", FAKE_CODEX)
    shim = tmp_path / "shim"   # ラッパーの中の「bash scripts/…」と偽の codex の #!/usr/bin/env bash も BASH で走らせる
    shim.mkdir()
    (shim / "bash").symlink_to(BASH)
    cache = Path.home() / ".cache" / f"luminous-test-{uuid.uuid4().hex[:8]}"
    yield p, fake, tmp_path / "fake.log", cache
    shutil.rmtree(cache, ignore_errors=True)
    if shutil.which("chflags"):   # Mac では全体停止の印に uchg が付く。外さないと一時フォルダを消せない
        subprocess.run(["chflags", "-R", "nouchg", str(tmp_path)], check=False, capture_output=True)


def env_for(t, mode="allowed", extra=None):
    p, fake, log, cache = t
    env = dict(os.environ, CODEX_BIN=str(fake), FAKE_MODE=mode, FAKE_LOG=str(log), XDG_CACHE_HOME=str(cache), LUMINOUS_SETTLE_S="0")
    for v in ("CODEX_FALLBACK_MODEL", "CODEX_OLD_BIN", "LUMINOUS_SAFE_DIR", "CDPATH"):
        env.pop(v, None)
    env.update(extra or {})
    env["PATH"] = f"{p.parent / 'shim'}:{env['PATH']}"   # PATH を差し替える試験でも、bash は BASH を使う
    return env


def run(t, mode="allowed", *, script="codex_impl.sh", args=None, env=None, timeout=120):
    if args is None:
        args = ("docs/specs/s.md", "low") if script == "codex_impl.sh" else ("docs/astra-packets/p.md",)
    return subprocess.run([BASH, f"tools/{script}", *args], cwd=t[0], env=env or env_for(t, mode),
                          capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def calls(t):
    return t[2].read_text().splitlines() if t[2].exists() else []


def _lock(t):
    return t[0] / "data" / "codex_runs" / ".lock"


def _sh(t, code, env):
    """作業フォルダの写しで _codex_common.sh を読み、関数を呼ぶ。"""
    return subprocess.run([BASH, "-c", f'set -u; . tools/_codex_common.sh; {code}'], cwd=t[0], env=env,
                          capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


def _good_python_dir(tmp_path) -> Path:
    d = tmp_path / "goodpy"
    d.mkdir(exist_ok=True)
    if not (d / "python3").exists():
        os.symlink(os.path.realpath(sys.executable), d / "python3")
    return d


# ---- safe_python: 実際に -I -S で動く python3 だけを選ぶ ----
def test_safe_python_skips_python3_that_cannot_run(proj, tmp_path):
    stub = _exe(tmp_path / "stub" / "python3", BROKEN_PY)
    env = env_for(proj, extra={"PATH": f"{stub.parent}:/usr/bin:/bin"})
    r = _sh(proj, "safe_python", env)
    chosen = r.stdout.strip()
    assert chosen != str(stub), (r.stdout, r.stderr)
    if r.returncode == 0:   # 決め打ちの候補（/usr/bin/python3 など）に動くものがある機械
        assert subprocess.run([chosen, "-I", "-S", "-c", "pass"], capture_output=True).returncode == 0, chosen


def test_safe_python_falls_through_to_working_python3(proj, tmp_path):
    good = _good_python_dir(tmp_path)
    stub = _exe(tmp_path / "stub" / "python3", BROKEN_PY)
    env = env_for(proj, extra={"PATH": f"{good}:{stub.parent}:/usr/bin:/bin"})
    r = _sh(proj, "safe_python", env)
    assert r.returncode == 0, r.stderr
    assert subprocess.run([r.stdout.strip(), "-I", "-S", "-c", "pass"], capture_output=True).returncode == 0, r.stdout


def test_safe_python_does_not_run_python3_inside_project(proj, tmp_path):
    """試しの起動は、作業領域の外と確かめた後だけ（作業領域の中の python3 は Codex が書き換えられる）。"""
    pwned = tmp_path / "pwned"
    inside = _exe(proj[0] / "bin" / "python3", f'#!/bin/sh\ntouch "{pwned}"\nexit 0\n')
    env = env_for(proj, extra={"PATH": f"{inside.parent}:/usr/bin:/bin"})
    r = _sh(proj, "safe_python", env)
    assert r.stdout.strip() != str(inside) and not pwned.exists(), (r.stdout, r.stderr)


def test_wrapper_with_only_broken_python3_says_python_not_git(proj, tmp_path):
    stub = _exe(tmp_path / "stub" / "python3", BROKEN_PY)
    env = env_for(proj, extra={"PATH": f"{stub.parent}:/usr/bin:/bin"})
    if _sh(proj, "safe_python", env).returncode == 0:
        pytest.skip("この機械には決め打ちの候補に動く python3 がある")
    r = run(proj, env=env)
    assert r.returncode == 2 and "動く python3 がありません" in r.stderr, r.stderr
    assert ".git があります" not in r.stderr and not calls(proj)


# ---- nested-git: 3 だけが「.git がある」。それ以外の失敗は「点検できなかった」 ----
@pytest.mark.parametrize("script", ["codex_impl.sh", "codex_opinion.sh"])
def test_nested_git_checker_failure_is_not_reported_as_git(proj, script):
    (proj[0] / "tools" / "scope_check.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    r = run(proj, script=script)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "点検を実行できませんでした（終了 1" in r.stderr and ".git があります" not in r.stderr, r.stderr
    assert not calls(proj) and not _lock(proj).exists()


@pytest.mark.parametrize("script", ["codex_impl.sh", "codex_opinion.sh"])
def test_nested_git_found_is_still_reported_as_git(proj, script):
    (proj[0] / "orch" / ".git").mkdir()
    r = run(proj, script=script)
    assert r.returncode == 2 and "作業フォルダ内に .git があります" in r.stderr, r.stderr
    assert "点検を実行できませんでした" not in r.stderr and not calls(proj)


# ---- find_codex: ~/Applications の ChatGPT.app・見つからないときの案内 ----
def _env_without_codex(proj, tmp_path, home):
    path = f"{_good_python_dir(tmp_path)}:/usr/bin:/bin"
    if shutil.which("codex", path=path) or (Path("/Applications") / APP_REL).exists():
        pytest.skip("この機械には PATH か /Applications に codex がある")
    env = env_for(proj, extra={"PATH": path, "HOME": str(home)})
    env.pop("CODEX_BIN", None)
    return env


def test_find_codex_uses_user_applications(proj, tmp_path):
    home = tmp_path / "home"
    shutil.copy(proj[1], _exe(home / "Applications" / APP_REL, ""))
    env = _env_without_codex(proj, tmp_path, home)
    r = run(proj, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert len(calls(proj)) == 1


@pytest.mark.parametrize("script", ["codex_impl.sh", "codex_opinion.sh"])
def test_codex_not_found_lists_where_it_looked(proj, tmp_path, script):
    env = _env_without_codex(proj, tmp_path, tmp_path / "emptyhome")
    r = run(proj, script=script, env=env)
    assert r.returncode == 2 and "Codex 本体が見つかりません" in r.stderr, r.stderr
    assert "探した場所" in r.stderr and "~/Applications/ChatGPT.app" in r.stderr and "CODEX_BIN" in r.stderr
    assert str(tmp_path / "emptyhome") not in r.stderr   # ホームは展開しない（ローカルパスを残さない）
    assert not _lock(proj).exists()


def test_health_codex_bin_finds_user_applications(monkeypatch, tmp_path):
    from orch import health
    home = tmp_path / "home"
    target = _exe(home / "Applications" / APP_REL, "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    assert health.codex_bin() == str(target)


# ---- make_safe_dir: 作れないときは理由を出す ----
def test_safe_dir_cannot_be_created_says_why(proj, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    r = run(proj, env=env_for(proj, extra={"LUMINOUS_SAFE_DIR": str(blocker / "luminous-codex")}))
    assert r.returncode == 2 and "安全な置き場" in r.stderr and "作れません" in r.stderr, r.stderr
    assert not calls(proj) and not _lock(proj).exists()


# ---- CDPATH を export していても、根を取り違えない ----
def test_luminous_halt_on_ignores_exported_cdpath(proj):
    r = subprocess.run([BASH, "tools/luminous_halt.sh", "on", "CDPATH の試験"], cwd=proj[0], env=env_for(proj, extra={"CDPATH": "."}),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "CDPATH の試験" in (proj[0] / "data" / ".luminous_halt").read_text(encoding="utf-8")
    assert not [c for c in proj[0].parent.iterdir() if "\n" in c.name]   # 改行を含む名前のフォルダに印を作っていない


def test_codex_impl_ignores_exported_cdpath(proj):
    r = run(proj, env=env_for(proj, extra={"CDPATH": "."}))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "scope_check: OK" in r.stdout


def test_set_env_key_ignores_exported_cdpath(proj, tmp_path):
    p = proj[0]
    env = env_for(proj, extra={"LUMINOUS_PRIVATE_DIR": str(tmp_path / "priv"), "ORCH_GEMINI": "0", "CDPATH": "."})
    rc, out, err = run_tty([BASH, "tools/set_env_key.sh", "GEMINI_API_KEY"], p, env, "newvalue\n")
    assert rc == 0, err
    assert "GEMINI_API_KEY=newvalue" in (p / ".env").read_text(encoding="utf-8")


# ---- ロック: 使い回された PID は回収し、本物の持ち主・確かめられないときは奪わない ----
@pytest.fixture
def sleeper():
    proc = subprocess.Popen(["sleep", "120"])
    yield proc
    proc.kill()
    proc.wait()


def _owner(t, pid, ts):
    _lock(t).mkdir(parents=True)
    (_lock(t) / "owner").write_text(f"{pid} {ts}\n")


def test_reused_pid_lock_is_reclaimed(proj, sleeper):
    _owner(proj, sleeper.pid, int(time.time()) - 3600)   # 記録の 1 時間後に始まったプロセス = 使い回された PID
    r = run(proj)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "古いロックを回収しました" in r.stderr and len(calls(proj)) == 1


def test_live_owner_with_consistent_time_is_not_reclaimed(proj, sleeper):
    _owner(proj, sleeper.pid, int(time.time()))
    r = run(proj)
    assert r.returncode == 2 and "別の Codex が実行中です" in r.stderr, r.stderr
    assert _lock(proj).exists() and not calls(proj)


@pytest.mark.parametrize("ts", ["0", "", "abc"])
def test_owner_without_usable_time_is_not_reclaimed(proj, sleeper, ts):
    _owner(proj, sleeper.pid, ts)
    r = run(proj)
    assert r.returncode == 2 and _lock(proj).exists() and not calls(proj), r.stderr


@pytest.mark.parametrize("ps_body", ["exit 1", "echo '(python3)'", "echo ''", "echo '1-'"])
def test_unreadable_ps_keeps_lock(proj, sleeper, tmp_path, ps_body):
    fake_ps = _exe(tmp_path / "fakeps" / "ps", f"#!/bin/sh\n{ps_body}\n")
    _owner(proj, sleeper.pid, int(time.time()) - 3600)
    r = run(proj, env=env_for(proj, extra={"PATH": f"{fake_ps.parent}:{os.environ['PATH']}"}))
    assert r.returncode == 2 and _lock(proj).exists() and not calls(proj), r.stderr


def test_running_wrapper_lock_is_not_reclaimed(proj):
    """本物のラッパーの実行中に 2 本目を起動しても、ロックを奪わない。"""
    p = proj[0]
    first = subprocess.Popen([BASH, "tools/codex_impl.sh", "docs/specs/s.md", "low"], cwd=p,
                             env=env_for(proj, "sleep", {"FAKE_SLEEP": "5"}), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        owner = _lock(proj) / "owner"
        for _ in range(300):
            if owner.exists() and owner.read_text().strip():
                break
            time.sleep(0.05)
        assert owner.read_text().split()[0] == str(first.pid)
        r = run(proj)
        if first.poll() is None:
            assert r.returncode == 2 and "別の Codex が実行中です" in r.stderr, r.stderr
    finally:
        first.communicate(timeout=120)


# ---- luminous_halt.sh の理由: python3 が動かない・UTF-8 でないロケール ----
def _halt(t, *args, env):
    return subprocess.run([BASH, "tools/luminous_halt.sh", *args], cwd=t[0], env=env,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)


def test_luminous_halt_reason_kept_when_python3_broken(proj, tmp_path):
    stub = _exe(tmp_path / "stub" / "python3", BROKEN_PY)
    env = env_for(proj, extra={"PATH": f"{stub.parent}:{os.environ['PATH']}"})
    r = _halt(proj, "on", "壊れた python の理由", env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "壊れた python の理由" in (proj[0] / "data" / ".luminous_halt").read_text(encoding="utf-8")
    assert "壊れた python の理由" in (proj[0] / "logs" / "halt.log").read_text(encoding="utf-8")
    assert "壊れた python の理由" in _halt(proj, "status", env=env).stdout


def _latin1_env(proj, tmp_path):
    probe = ('import locale, sys; locale.setlocale(locale.LC_CTYPE, ""); '
             'sys.exit(0 if locale.getpreferredencoding(False).lower().replace("-", "").replace("_", "") in ("iso88591", "latin1") else 1)')
    py = shutil.which("python3") or sys.executable
    for name in ("en_US.ISO8859-1", "en_US.ISO-8859-1"):   # Mac は最初の名前を持っている
        e = env_for(proj, extra={"LC_ALL": name})
        if subprocess.run([py, "-I", "-S", "-c", probe], env=e, capture_output=True).returncode == 0:
            return e
    if shutil.which("localedef"):
        loc = tmp_path / "loc"
        loc.mkdir()
        subprocess.run(["localedef", "-f", "ISO-8859-1", "-i", "en_US", str(loc / "en_US.ISO-8859-1")], capture_output=True)
        e = env_for(proj, extra={"LC_ALL": "en_US.ISO-8859-1", "LOCPATH": str(loc)})
        if subprocess.run([py, "-I", "-S", "-c", probe], env=e, capture_output=True).returncode == 0:
            return e
    pytest.skip("UTF-8 でないロケールを用意できない")


def test_luminous_halt_reason_is_utf8_and_filtered_under_latin1_locale(proj, tmp_path):
    """-I は PYTHONIOENCODING を無視する。-X utf8 で、ロケールに依らず python の経路（表示できない文字を落とす）で処理する。"""
    env = _latin1_env(proj, tmp_path)
    r = _halt(proj, "on", "日本語の理由😀‮abc", env=env)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    text = (proj[0] / "data" / ".luminous_halt").read_text(encoding="utf-8")
    assert "日本語の理由😀abc" in text and "‮" not in text, text
    log = (proj[0] / "logs" / "halt.log").read_text(encoding="utf-8")
    assert "日本語の理由😀abc" in log and "‮" not in log


# ---- set_env_key.sh: 置き場がまだ無くても ignore を判定できる ----

def _top_repo(tmp_path, ignore):
    top = tmp_path / "top"
    top.mkdir()
    subprocess.run(["git", "init", "-q", str(top)], check=True, env=dict(os.environ, **GIT_ENV))
    if ignore is not None:
        (top / ".gitignore").write_text(ignore, encoding="utf-8")
    return top


def _set_key(proj, priv):
    p = proj[0]
    (p / ".env").write_text("X=1\n", encoding="utf-8")
    env = env_for(proj, extra={"LUMINOUS_PRIVATE_DIR": str(priv), "ORCH_GEMINI": "0"})
    return run_tty([BASH, "tools/set_env_key.sh", "GEMINI_API_KEY"], p, env, "newvalue\n")


@pytest.mark.parametrize("ignore", ["priv/\n", "priv\n", "/priv/\n"])
def test_set_env_key_accepts_missing_ignored_private_dir(proj, tmp_path, ignore):
    top = _top_repo(tmp_path, ignore)
    assert not (top / "priv").exists()
    rc, out, err = _set_key(proj, top / "priv")
    assert rc == 0, err
    assert len(list((top / "priv" / "env_backups").glob(".env.bak.*"))) == 1
    assert "GEMINI_API_KEY=newvalue" in (proj[0] / ".env").read_text(encoding="utf-8")


@pytest.mark.parametrize("ignore,priv_rel", [
    (None, "priv"),                                  # ignore されていない
    ("priv/*\n!priv/env_backups/\n", "priv"),         # 控えのフォルダだけを戻している（フォルダ名だけの判定では見逃す）
    (None, "a/b/priv"),                               # 親のフォルダもまだ無い
])
def test_set_env_key_refuses_unignored_private_dir_in_repo(proj, tmp_path, ignore, priv_rel):
    top = _top_repo(tmp_path, ignore)
    rc, out, err = _set_key(proj, top / priv_rel)
    assert rc == 1 and "git の管理下" in err, (rc, err)
    assert (proj[0] / ".env").read_text(encoding="utf-8") == "X=1\n"
    assert not (top / priv_rel).exists()


# ---- scope_check.py: NFC・Finder の .DS_Store・compare の型 ----
def _sc():
    spec = importlib.util.spec_from_file_location("scope_check_mac", ROOT / "tools" / "scope_check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_allowed_matches_nfd_stored_name(tmp_path):
    sc = _sc()
    nfc = "prompts/ルミナス_最終プロンプト.md"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    (tmp_path / "prompts").mkdir()
    (tmp_path / nfd).write_text("a\n", encoding="utf-8")
    before = sc.snapshot(str(tmp_path))
    (tmp_path / nfd).write_text("a\nb\n", encoding="utf-8")
    problems, changed, after = sc.compare(str(tmp_path), before, [nfc])
    assert problems == [] and changed == [nfd], problems   # 記録する名前は保存名のまま
    assert sc.is_allowed(nfc, [nfd]) and sc.is_allowed(nfd, ["prompts/*プロンプト.md"])   # ALLOWED 側が NFD・glob でも一致
    (tmp_path / "other.md").write_text("x\n", encoding="utf-8")
    problems, _, _ = sc.compare(str(tmp_path), before, [nfc])
    assert any("ALLOWED 外の変更: other.md" in p for p in problems)   # 外の変更は従来どおり止める


def test_compare_annotation_matches_three_values():
    sc = _sc()
    assert typing.get_type_hints(sc.compare)["return"] == typing.Tuple[typing.List[str], typing.List[str], dict]
    assert "実行後のスナップショット" in sc.compare.__doc__


@pytest.fixture
def tree(tmp_path):
    r = tmp_path / "t"
    (r / "orch").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / "orch" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (r / "README.md").write_text("readme\n", encoding="utf-8")
    return r


def _ds(path: Path, size=16, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Bud1\0\0\0\1" + b"\0" * max(size - 8, 0))
    path.chmod(mode)


def test_finder_ds_store_is_not_violation(tree):
    sc = _sc()
    _ds(tree / "docs" / ".DS_Store")
    before = sc.snapshot(str(tree))
    _ds(tree / "docs" / ".DS_Store", size=64)   # 既存の書き換え
    _ds(tree / ".DS_Store")                     # 新規
    _ds(tree / "orch" / ".DS_Store", size=1 << 20)   # ちょうど 1 MiB
    (tree / "orch" / "__init__.py").write_text("x = 2\n", encoding="utf-8")
    problems, changed, after = sc.compare(str(tree), before, ["orch/__init__.py"])
    assert problems == [], problems
    assert {".DS_Store", "docs/.DS_Store", "orch/.DS_Store"} <= set(changed)
    _ds(tree / "docs" / ".DS_Store", size=128)   # 検査の後に Finder が書いても、比べ直しで違反にしない
    assert sc.recheck(str(tree), after) == []


def _mut_exec(r):
    _ds(r / "docs" / ".DS_Store", mode=0o755)


def _mut_big(r):
    _ds(r / "docs" / ".DS_Store", size=(1 << 20) + 1)


def _mut_symlink(r):
    os.symlink(str(r / "README.md"), str(r / "docs" / ".DS_Store"))


def _mut_dangling_symlink(r):
    os.symlink("/nonexistent/target", str(r / ".DS_Store"))


def _mut_under_dir(r):
    _ds(r / "docs" / ".DS_Store" / "payload.py")


def _mut_under_dir_same_name(r):
    _ds(r / "docs" / ".DS_Store" / ".DS_Store")


def _mut_hardlink(r):
    os.link(str(r / "README.md"), str(r / ".DS_Store"))


def _mut_fifo(r):
    os.mkfifo(str(r / "docs" / ".DS_Store"))


def _mut_lookalike(r):
    _ds(r / "docs" / ".DS_Store.py")


@pytest.mark.parametrize("mutate", [_mut_exec, _mut_big, _mut_symlink, _mut_dangling_symlink, _mut_under_dir,
                                    _mut_under_dir_same_name, _mut_hardlink, _mut_fifo, _mut_lookalike],
                         ids=lambda f: f.__name__[5:])
def test_ds_store_outside_conditions_is_violation(tree, mutate):
    sc = _sc()
    before = sc.snapshot(str(tree))
    mutate(tree)
    problems, _, after = sc.compare(str(tree), before, ["orch/__init__.py"])
    assert any(".DS_Store" in p for p in problems), problems


def test_ds_store_deleted_is_violation(tree):
    sc = _sc()
    _ds(tree / "docs" / ".DS_Store")
    before = sc.snapshot(str(tree))
    (tree / "docs" / ".DS_Store").unlink()
    problems, _, _ = sc.compare(str(tree), before, ["orch/__init__.py"])
    assert any("docs/.DS_Store" in p for p in problems), problems


def test_ds_store_turned_executable_after_check_is_recheck_violation(tree):
    sc = _sc()
    before = sc.snapshot(str(tree))
    _ds(tree / ".DS_Store")
    problems, _, after = sc.compare(str(tree), before, ["orch/__init__.py"])
    assert problems == []
    (tree / ".DS_Store").chmod(0o755)
    assert any(".DS_Store" in p for p in sc.recheck(str(tree), after))


def test_ds_store_cli_lists_record_change_and_count_ignores_it(tree, tmp_path):
    sc_path = str(ROOT / "tools" / "scope_check.py")
    py = [sys.executable, "-I", "-S", sc_path]
    before = tmp_path / "before.json"
    allowed = tmp_path / "allowed.txt"
    allowed.write_text("orch/__init__.py\n", encoding="utf-8")
    subprocess.run([*py, "snapshot", str(tree), str(before)], check=True)
    _ds(tree / "docs" / ".DS_Store")
    assert subprocess.run([*py, "count", str(tree), str(before)], capture_output=True, text=True).stdout.strip() == "0"
    (tree / "orch" / "__init__.py").write_text("x = 2\n", encoding="utf-8")
    assert subprocess.run([*py, "count", str(tree), str(before)], capture_output=True, text=True).stdout.strip() == "1"
    r = subprocess.run([*py, "compare", str(tree), str(before), str(allowed)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "変更 1 件" in r.stdout and "記録ファイルの変更" in r.stdout and "  - docs/.DS_Store" in r.stdout


def test_codex_impl_finder_ds_store_is_not_violation(proj):
    r = run(proj, "dsstore")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "記録ファイルの変更" in r.stdout and not (proj[0] / "data" / ".codex_violation").exists()


def test_codex_impl_executable_ds_store_is_violation(proj):
    r = run(proj, "dsstore_exec")
    assert r.returncode == 3 and "docs/.DS_Store" in r.stderr, (r.stdout, r.stderr)


def test_ds_store_is_gitignored():
    """.DS_Store を見ない前提（公開されない）を固定する。"""
    for rel in (".DS_Store", "docs/.DS_Store", "orch/sub/.DS_Store"):
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT, env=dict(os.environ, **GIT_ENV))  # 利用者の除外設定で通さない
        assert r.returncode == 0, f"{rel} が .gitignore に入っていない"


# ---- orch: requests が無い python3 でも点検と既定値の経路は動く ----
GKEY = "AI" "za" + "FAKE" * 8 + "12"   # 偽の鍵は実行時に組み立てる
JKEY = "tsk_" + "FAKE" * 5 + "1234"


def test_health_shows_missing_requests(monkeypatch):
    from orch import gemini, health, jev
    monkeypatch.setattr(gemini, "requests", None)
    monkeypatch.setattr(jev, "requests", None)
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health, "CODEX_USER_APP_PATH", "/nonexistent/codex2")
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    lines = health.lines(net=True)
    assert len(lines) == 4 and lines[1].startswith("!!! requests 未導入"), lines
    assert lines[2].startswith("gemini: 鍵なし") and "requests 未導入" in lines[3]


def test_gemini_without_requests_does_not_call_and_is_skip(monkeypatch, isolated_env):
    from orch import gemini
    from tests.conftest import read_ledger
    monkeypatch.setenv("GEMINI_API_KEY", GKEY)
    monkeypatch.setattr(gemini, "requests", None)
    r = gemini.generate("x")
    assert r.rc == 2 and r.reason == "requests 未導入"
    row = read_ledger(isolated_env)[-1]
    assert row["status"] == "skip" and row["calls"] == 0 and row["usd"] == 0
    ok, line = gemini.check_status(net=True)
    assert not ok and "requests 未導入" in line and GKEY not in line


def test_jev_without_requests_is_unavailable_and_not_counted(monkeypatch, isolated_env):
    from orch import decisions, jev
    from tests.conftest import read_ledger
    monkeypatch.setenv("JEV_ENABLED", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", JKEY)
    monkeypatch.setattr(jev, "requests", None)
    with pytest.raises(jev.JevUnavailable, match="requests 未導入"):
        jev.call("明日は晴れますか", {"q": {"type": "noul", "instructions": "質問か"}})
    assert not [r for r in read_ledger(isolated_env) if r.get("vendor") == "jev" and r.get("calls")]
    d = decisions.ask("明日は晴れますか", {"q": decisions.Noul("質問か", 0.5)}, backend="jev", fallback=False, purpose="t")
    assert d.backend == "rules" and d.answers == {"q": 0.5} and "requests 未導入" in d.reason


def test_orch_entry_points_run_without_requests(tmp_path):
    """requests の無い python3（.venv が未作成）を、import を None にして模す。点検と判断層の点検が落ちない。"""
    code = ("import sys; sys.modules['requests'] = None\n"
            "from orch import health, decisions\n"
            "health.main(['--quiet', '--no-net']); decisions.main(['--check'])\n")
    env = dict(os.environ, ORCH_SKIP_DOTENV="1", ORCH_DATA_DIR=str(tmp_path / "data"), ORCH_LOG_DIR=str(tmp_path / "logs"))
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "!!! requests 未導入" in r.stdout and "codex:" in r.stdout and "decisions:" in r.stdout


def test_libressl_warning_is_hidden_only_for_that_message():
    """Mac の Apple 製 python3（LibreSSL）で urllib3 v2 が出す NotOpenSSLWarning を伏せる。ほかの警告は伏せない。"""
    fake_ssl = "import ssl; ssl.OPENSSL_VERSION = 'LibreSSL 2.8.3'\n"
    base = subprocess.run([sys.executable, "-W", "default", "-c", fake_ssl + "import requests"], cwd=ROOT, capture_output=True, text=True)
    if "OpenSSL 1.1.1" not in base.stderr:
        pytest.skip("この環境の urllib3 は LibreSSL の警告を出さない（v1 か、無い）")
    code = fake_ssl + ("import warnings\nimport orch.health, orch.decisions\n"
                       "warnings.warn('ほかの警告', UserWarning)\n")
    r = subprocess.run([sys.executable, "-W", "default", "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, ORCH_SKIP_DOTENV="1"))
    assert r.returncode == 0, r.stderr
    assert "OpenSSL 1.1.1" not in r.stderr and "ほかの警告" in r.stderr, r.stderr


# ---- bash 3.2 の UTF-8 ロケールで壊れる変数参照（docs/specs/20261010_mac_bash32_tests.md (a)）----
# bash 3.2 は「$RC）」のように変数名の直後に非 ASCII が続くと、高位バイトを変数名に含めてしまう（set -u なら unbound variable、
# 無ければ値と直後の 1 文字が黙って消える）。${RC} と波括弧で囲めば通る。Mac で 2026-10-10 に実測（pytest 18 件が落ちた）。
_BASH32_BAD = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]")


def _bash32_bad_lines(paths):
    hits = []
    for p in paths:
        for i, line in enumerate(p.read_bytes().splitlines(), 1):
            if _BASH32_BAD.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{i}: {line.decode('utf-8', 'replace').strip()[:100]}")
    return hits


def _shell_sources():
    files = sorted(ROOT.glob("tools/*.sh")) + sorted(ROOT.glob("scripts/*.sh")) + sorted(ROOT.glob(".claude/hooks/*.sh"))
    files += [p for p in sorted(ROOT.glob(".githooks/*")) if p.is_file()]
    return files


def test_no_variable_reference_directly_followed_by_non_ascii():
    files = _shell_sources()
    assert len(files) >= 15
    assert _bash32_bad_lines(files) == []


def test_bash32_detector_catches_a_bad_reference(tmp_path):
    bad = tmp_path / "bad.sh"
    bad.write_bytes('echo "rc=$RC）"\n'.encode("utf-8"))
    good = tmp_path / "good.sh"
    good.write_bytes('echo "rc=${RC}）" "$HALT" "$n 件"\n'.encode("utf-8"))
    assert _BASH32_BAD.search(bad.read_bytes()) is not None
    assert _BASH32_BAD.search(good.read_bytes()) is None


@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="/bin/bash が無い")
def test_braced_reference_survives_utf8_locale_in_system_bash():
    # 3.2 でも 5.x でも、波括弧なら UTF-8 ロケールで値が残る（Mac の /bin/bash 3.2 ではこれが落ちる前提の修正）
    env = dict(os.environ, LC_ALL="C.UTF-8")
    r = subprocess.run(["/bin/bash", "-c", 'set -u; X=1; printf "%s" "${X}）"'], capture_output=True, env=env)
    assert r.returncode == 0 and r.stdout.decode("utf-8") == "1）", (r.returncode, r.stdout, r.stderr)
