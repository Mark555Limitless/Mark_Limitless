import json
from datetime import timedelta

from orch import config, usage
from tests.conftest import read_ledger


def test_record_and_totals(isolated_env):
    usage.record("gemini", model="m", purpose="p", usd=0.25, in_tokens=10, out_tokens=5, ms=100)
    usage.record("gemini", usd=0.5, status="error")
    usage.record("jev", usd=0.001)
    assert abs(usage.today_usd("gemini") - 0.75) < 1e-9
    assert usage.today_calls("gemini") == 2
    assert abs(usage.month_usd("jev") - 0.001) < 1e-9
    rows = read_ledger(isolated_env)
    assert rows[0]["vendor"] == "gemini" and rows[0]["status"] == "ok" and rows[0]["ts"].endswith("+09:00")


def test_yesterday_not_counted_today(isolated_env):
    path = usage.ledger_path()
    y = (config.now_jst() - timedelta(days=1)).isoformat(timespec="seconds")
    path.write_text(json.dumps({"ts": y, "vendor": "gemini", "calls": 1, "usd": 9.0}) + "\n", encoding="utf-8")
    assert usage.today_usd("gemini") == 0.0
    assert usage.summarize(2)  # 2日分の集計には入る


def test_bad_lines_are_skipped(isolated_env):
    usage.ledger_path().write_text("not json\n{\"x\":1}\n", encoding="utf-8")
    assert usage.today_usd("gemini") == 0.0


def test_redacts_secret_values(isolated_env, monkeypatch):
    fake = "AI" "za" + "FAKE" * 8 + "12"  # 偽の鍵は実行時に組み立てる
    monkeypatch.setenv("GEMINI_API_KEY", fake)
    usage.record("gemini", purpose="leak " + fake)
    assert fake not in usage.ledger_path().read_text(encoding="utf-8")


def test_cli_record_and_summary(isolated_env, capsys):
    assert usage.main(["record", "--vendor", "codex", "--status", "ok", "--ms", "1500", "--model", "gpt-6-astra"]) == 0
    assert usage.main(["--days", "1"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "1.5" in out
