import pytest

from orch import jev, usage
from tests.conftest import FakeResp, read_ledger

KEY = "tsk_FAKEFAKEFAKEFAKEFAKE1234"
QS = {"q": {"type": "noul", "instructions": "質問か"}}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setenv("JEV_ENABLED", "1")


def _no_call(*a, **k):
    raise AssertionError("API を呼んではいけない")


def test_success(enabled, monkeypatch, isolated_env):
    seen = {}

    def post(url, **k):
        seen.update(url=url, **k)
        return FakeResp(200, {"model": "jev-1.13", "answers": {"q": {"type": "noul", "noul": 0.9}}, "usage": {"cost": 0.0002}})
    monkeypatch.setattr(jev.requests, "post", post)
    ans = jev.call("明日は晴れますか", QS, purpose="t")
    assert ans["q"]["noul"] == 0.9
    assert seen["url"].endswith("/v1/systemone") and seen["headers"]["Authorization"] == f"Bearer {KEY}"
    assert seen["json"]["model"] == "jev-latest" and isinstance(seen["json"]["state"], str)
    rows = read_ledger(isolated_env)
    assert rows[-1]["vendor"] == "jev" and rows[-1]["status"] == "ok" and abs(rows[-1]["usd"] - 0.0002) < 1e-9
    assert KEY not in (isolated_env / "logs" / "jev.log").read_text(encoding="utf-8")


def test_daily_max(enabled, monkeypatch):
    monkeypatch.setenv("ORCH_JEV_DAILY_MAX", "2")
    usage.record("jev"); usage.record("jev", status="error")
    monkeypatch.setattr(jev.requests, "post", _no_call)
    with pytest.raises(jev.JevUnavailable, match="回数"):
        jev.call("s", QS)


def test_monthly_usd(enabled, monkeypatch):
    monkeypatch.setenv("ORCH_JEV_MONTHLY_USD", "0.001")
    usage.record("jev", usd=0.002)
    monkeypatch.setattr(jev.requests, "post", _no_call)
    with pytest.raises(jev.JevUnavailable, match="月額"):
        jev.call("s", QS)


def test_stop_switch(enabled, monkeypatch):
    monkeypatch.setenv("ORCH_JEV", "0")
    monkeypatch.setattr(jev.requests, "post", _no_call)
    with pytest.raises(jev.JevUnavailable, match="停止中"):
        jev.call("s", QS)


def test_disabled_flag_or_no_key(monkeypatch):
    monkeypatch.setattr(jev.requests, "post", _no_call)
    with pytest.raises(jev.JevUnavailable):
        jev.call("s", QS)
    monkeypatch.setenv("JEV_ENABLED", "1")
    with pytest.raises(jev.JevUnavailable, match="鍵なし"):
        jev.call("s", QS)


@pytest.mark.parametrize("mode", ["http500", "network"])
def test_failures_are_counted(enabled, monkeypatch, isolated_env, mode):
    def post(url, **k):
        if mode == "network":
            raise jev.requests.ConnectionError("x")
        return FakeResp(500, {})
    monkeypatch.setattr(jev.requests, "post", post)
    with pytest.raises(jev.JevUnavailable):
        jev.call("s", QS)
    assert usage.today_calls("jev") == 1 and read_ledger(isolated_env)[-1]["status"] == "error"


def test_usd_estimates():
    assert abs(jev._usd({"usage": {"input_tokens": 1_000_000}}, 1) - 0.042) < 1e-9
    assert abs(jev._usd({}, 3) - 0.0009) < 1e-9


@pytest.mark.parametrize("payload", [[], None, {"answers": ["x"]}])
def test_malformed_response_is_counted(enabled, monkeypatch, isolated_env, payload):
    resp = FakeResp(200, payload) if payload is not None else FakeResp(200, None, text="not json")
    monkeypatch.setattr(jev.requests, "post", lambda url, **k: resp)
    with pytest.raises(jev.JevUnavailable):
        jev.call("s", QS)
    rows = read_ledger(isolated_env)
    assert len(rows) == 1 and rows[0]["status"] == "error" and usage.today_calls("jev") == 1


def test_json_decode_error_is_parse_failure(enabled, monkeypatch, isolated_env):
    monkeypatch.setattr(jev.requests, "post", lambda url, **k: FakeResp(200, None, text="<html>"))
    with pytest.raises(jev.JevUnavailable, match="解析失敗"):
        jev.call("s", QS)
    assert read_ledger(isolated_env)[-1]["usd"] > 0


@pytest.mark.parametrize("t,expected", [(2.0, (2.0, 2.0)), (8.0, (5.0, 8.0))])
def test_connect_timeout_respects_budget(enabled, monkeypatch, t, expected):
    seen = {}
    monkeypatch.setattr(jev.requests, "post", lambda url, **k: seen.update(k) or FakeResp(200, {"answers": {"q": {"noul": 0.5}}}))
    jev.call("s", QS, timeout_s=t)
    assert seen["timeout"] == expected


def test_call_halted_raises_without_network_and_counts_no_call(enabled, monkeypatch, isolated_env):
    from orch import config
    config.HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.HALT_PATH.write_text("2026-10-10T00:00:00Z 試験\n", encoding="utf-8")
    monkeypatch.setattr(jev.requests, "post", _no_call)
    with pytest.raises(config.GlobalHalt):
        jev.call("s", QS, purpose="t")
    led = read_ledger(isolated_env)
    assert led and led[-1]["status"] == "skip" and led[-1].get("calls", 1) == 0
    assert "全体停止中" in jev.status_line()

