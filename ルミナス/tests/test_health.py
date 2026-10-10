import os
import re
import subprocess
import sys

from orch import config, health
from tests.conftest import FLAG_VARS, ROOT, SECRET_VARS


def test_lines_without_network(monkeypatch):
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health, "CODEX_USER_APP_PATH", "/nonexistent/codex", raising=False)  # ~/Applications の同梱版も見ない
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    lines = health.lines(net=False)
    assert len(lines) == 3
    assert lines[0].startswith("codex: 本体=なし") and lines[1].startswith("gemini: 鍵なし") and lines[2].startswith("jev: 鍵=なし")


def test_codex_disabled(monkeypatch):
    monkeypatch.setenv("ORCH_CODEX", "0")
    assert "停止中" in health.codex_line()


def test_lines_show_halt_without_exception(monkeypatch, isolated_env):
    from orch import config
    config.HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.HALT_PATH.write_text("2026-10-10T00:00:00Z 試験\n", encoding="utf-8")
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health, "CODEX_USER_APP_PATH", "/nonexistent/codex", raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    lines = health.lines(net=False)
    assert len(lines) == 4 and lines[0].startswith("!!! 全体停止中")
    assert "停止中" in lines[1] and "全体停止中" in lines[2] and "全体停止中" in lines[3]


# ---- 試験の環境の分離（conftest の FLAG_VARS）----
def test_flag_vars_cover_env_read_by_orch_and_tools():
    """orch と tools/ が読む環境変数は、conftest がすべて消す（または決め直す）。漏れると Mark の export で試験の結果が変わる"""
    names = set()
    for f in (ROOT / "orch").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        names |= set(re.findall(r'\benv(?:_int|_float)?\(\s*"([A-Z][A-Z0-9_]*)"', text))
        names |= set(re.findall(r'environ(?:\.get\(|\[)\s*"([A-Z][A-Z0-9_]*)"', text))
        names |= {f"ORCH_{v.upper()}" for v in re.findall(r'disabled\(\s*"([a-z]+)"', text)}  # config.disabled の ORCH_<VENDOR>
    for f in (ROOT / "tools").glob("*.sh"):
        text = f.read_text(encoding="utf-8")
        assigned = set(re.findall(r'^\s*([A-Z][A-Z0-9_]*)=', text, re.M))  # スクリプトの中で決める名前（環境からは読まない）
        names |= set(re.findall(r'\$\{?((?:CODEX|ORCH|LUMINOUS|JEV|DECISION|CYCLE)_[A-Z0-9_]*)', text)) - assigned
        for group in re.findall(r'for _n in ([A-Z0-9_ ]+); do _dotenv_var', text):  # .env から読む名前
            names |= set(group.split())
    assert {"CODEX_OLD_BIN", "JEV_ENDPOINT", "DECISION_TIMEOUT_MS", "LUMINOUS_SAFE_DIR", "ORCH_CODEX"} <= names  # 走査が働いている
    reset_by_conftest = {"ORCH_SKIP_DOTENV", "ORCH_DATA_DIR", "ORCH_LOG_DIR"}  # 消さずに試験用の値へ決め直す
    assert not sorted(names - set(FLAG_VARS) - set(SECRET_VARS) - reset_by_conftest)
    assert set(config.SECRET_ENV_NAMES) <= set(SECRET_VARS)


def test_shell_exported_settings_do_not_leak_into_tests(tmp_path):
    """シェルに export された設定（古い本体の場所・単価・接続先・待ち時間・安全な置き場）があっても、試験は既定の値で通る。
    消し漏れがあると、ここで選んだ試験が落ちる"""
    leak = tmp_path / "leak"
    env = dict(os.environ, CODEX_OLD_BIN="/bin/sh", ORCH_GEMINI_PRICE_IN="1", ORCH_GEMINI_PRICE_OUT="4",
               JEV_ENDPOINT="https://example.invalid/other", DECISION_TIMEOUT_MS="1", LUMINOUS_SAFE_DIR=str(leak))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'inner'}",
                        "tests/test_health.py::test_lines_without_network",
                        "tests/test_gemini.py::test_success_excludes_thoughts_and_costs",
                        "tests/test_jev.py::test_success", "tests/test_decisions.py",
                        "tests/test_tools.py::test_luminous_halt_on_status_and_nontty_off"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert not leak.exists()  # 試験が Mark の安全な置き場（halt.log）に書かない
