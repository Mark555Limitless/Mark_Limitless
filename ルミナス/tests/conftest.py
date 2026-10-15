"""テスト共通: 外部 API は呼ばない。.env を読まず、台帳とログは一時ディレクトリへ。"""
import getpass
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SECRET_VARS = ("GEMINI_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
# orch と tools/ が読む環境変数（Mark が .zshrc 等で export していても、試験には持ち込まない）。
# 足すときは test_health.py の test_flag_vars_cover_env_read_by_orch_and_tools が漏れを知らせる
FLAG_VARS = ("ORCH_GEMINI", "ORCH_JEV", "ORCH_CODEX", "JEV_ENABLED", "DECISION_BACKEND", "CYCLE_START_EPOCH",
             "ORCH_GEMINI_DAILY_USD_CAP", "ORCH_JEV_DAILY_MAX", "ORCH_JEV_MONTHLY_USD", "DECISION_SHADOW_LOG",
             "CODEX_BIN", "CODEX_MODEL", "CODEX_FALLBACK_MODEL", "FABLE5_HEADLESS", "JEV_MODEL",
             "CODEX_OLD_BIN", "ORCH_GEMINI_MODEL", "ORCH_GEMINI_PRICE_IN", "ORCH_GEMINI_PRICE_OUT",
             "ORCH_GEMINI_THINKING", "JEV_ENDPOINT", "DECISION_TIMEOUT_MS", "CYCLE_LIMIT_S",
             "CODEX_DISABLE_FEATURES", "LUMINOUS_SAFE_DIR", "LUMINOUS_PRIVATE_DIR", "LUMINOUS_SETTLE_S", "ORCH_ROSTER")


def _clear_immutable(root) -> int:
    """試験の一時領域の uchg だけを外す。リンク先には触らず、失敗件数を返す。"""
    if not hasattr(os, "chflags"):
        return 0
    failures = 0

    def failed(_error):
        nonlocal failures
        failures += 1

    def clear(path, info=None):
        try:
            info = os.lstat(path) if info is None else info
            if info.st_flags & stat.UF_IMMUTABLE:
                os.chflags(path, info.st_flags & ~stat.UF_IMMUTABLE, follow_symlinks=False)
        except (OSError, ValueError, NotImplementedError) as error:
            failed(error)

    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        return 1
    if stat.S_ISLNK(info.st_mode):
        return 0
    clear(root, info)
    if stat.S_ISDIR(info.st_mode):
        try:
            for parent, dirs, files in os.walk(root, followlinks=False, onerror=failed):
                for name in dirs + files:
                    clear(Path(parent) / name)
        except (OSError, ValueError, NotImplementedError) as error:
            failed(error)
    return failures


def _sweep_stale_halt_markers(root) -> int:
    """pytest が消し損ねた garbage-* の data/.luminous_halt だけを救済する。"""
    if not hasattr(os, "chflags"):
        return 0
    failures = 0

    def failed(_error):
        nonlocal failures
        failures += 1

    try:
        root = Path(root)
        info = os.lstat(root)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        return 1
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        return 0
    try:
        for child in root.iterdir():
            if not child.name.startswith("garbage-"):
                continue
            try:
                if not stat.S_ISDIR(os.lstat(child).st_mode):
                    continue
                for parent, dirs, files in os.walk(child, followlinks=False, onerror=failed):
                    if Path(parent).name != "data" or ".luminous_halt" not in dirs + files:
                        continue
                    marker = Path(parent) / ".luminous_halt"
                    try:
                        flags = os.lstat(marker).st_flags
                        if flags & stat.UF_IMMUTABLE:
                            os.chflags(marker, flags & ~stat.UF_IMMUTABLE, follow_symlinks=False)
                    except (OSError, ValueError, NotImplementedError) as error:
                        failed(error)
            except (OSError, ValueError, NotImplementedError) as error:
                failed(error)
    except (OSError, ValueError, NotImplementedError) as error:
        failed(error)
    return failures


def _pytest_temproot(config) -> Optional[Path]:
    if config.option.basetemp is not None:
        return None
    try:
        user = getpass.getuser() or "unknown"
    except Exception:
        user = "unknown"
    return Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve() / f"pytest-of-{user}"


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    root = _pytest_temproot(session.config)
    if root is not None:
        _sweep_stale_halt_markers(root)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_SKIP_DOTENV", "1")
    monkeypatch.setenv("ORCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORCH_LOG_DIR", str(tmp_path / "logs"))
    from orch import config as _config  # 全体停止の印の場所を一時ディレクトリへ（本物の data/ を見ない）
    monkeypatch.setattr(_config, "HALT_PATH", tmp_path / "data" / ".luminous_halt")
    for v in SECRET_VARS + FLAG_VARS:
        monkeypatch.delenv(v, raising=False)
    yield tmp_path
    _clear_immutable(tmp_path)


class FakeResp:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def fake_resp():
    return FakeResp


def read_ledger(tmp_path):
    p = tmp_path / "data" / "usage.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
