"""テスト共通: 外部 API は呼ばない。.env を読まず、台帳とログは一時ディレクトリへ。"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SECRET_VARS = ("GEMINI_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
FLAG_VARS = ("ORCH_GEMINI", "ORCH_JEV", "ORCH_CODEX", "JEV_ENABLED", "DECISION_BACKEND", "CYCLE_START_EPOCH",
             "ORCH_GEMINI_DAILY_USD_CAP", "ORCH_JEV_DAILY_MAX", "ORCH_JEV_MONTHLY_USD", "DECISION_SHADOW_LOG",
             "CODEX_BIN", "CODEX_MODEL", "CODEX_FALLBACK_MODEL", "FABLE5_HEADLESS")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_SKIP_DOTENV", "1")
    monkeypatch.setenv("ORCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORCH_LOG_DIR", str(tmp_path / "logs"))
    for v in SECRET_VARS + FLAG_VARS:
        monkeypatch.delenv(v, raising=False)
    yield tmp_path


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
