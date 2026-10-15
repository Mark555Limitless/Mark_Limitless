"""Fugu の送信はすべてモック。名簿・台帳・ログは一時領域のみ。"""
import copy
import io
import json
import threading
from unittest.mock import Mock

import pytest

from orch import config, fugu, gate, usage
from tests.conftest import FakeResp, read_ledger

OK = {"choices": [{"message": {"content": "answer-private"}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}


@pytest.fixture(autouse=True)
def setup(isolated_env, monkeypatch):
    entry = dict(id="sakana-fugu-max", role=fugu.ROLE, provider="sakana", model="fugu-max",
                 state="trial", max_data_class="A", hosts=["api.sakana.ai"],
                 price={"input": 2.0, "output": 6.0, "unit": "usd_per_mtok"},
                 caps={"usd_per_day": 0.25}, version_kind="alias", evidence=[],
                 rollback_to="stop", review_by="2026-11-01")
    path = isolated_env / "roster.json"
    path.write_text(json.dumps({"entries": [entry]}))
    monkeypatch.setenv("ORCH_ROSTER", str(path))
    monkeypatch.setenv("SAKANA_API_KEY", "test-only-credential")
    client = Mock()
    client.post.return_value = FakeResp(200, copy.deepcopy(OK))
    client.get.return_value = FakeResp(200, {})
    monkeypatch.setattr(fugu, "requests", client)
    return path, client


def test_success_and_accounting(setup, isolated_env):
    res = fugu.generate("prompt-private", data_class="A")
    assert (res.rc, res.text) == (0, "answer-private")
    assert res.usd == pytest.approx(0.005) and isinstance(res.sec, float) and res.sec >= 0
    call = setup[1].post.call_args
    assert call.args == ("https://api.sakana.ai/v1/chat/completions",)
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["json"]["max_completion_tokens"] == 2048
    assert call.kwargs["headers"]["Authorization"] == "Bearer test-only-credential"
    log = (isolated_env / "logs" / "fugu.log").read_text()
    assert len(log.splitlines()) == 1
    assert all(secret not in log for secret in ("prompt-private", "answer-private", "test-only-credential"))
    rows = read_ledger(isolated_env)
    assert len(rows) == 1
    assert rows[0]["vendor"] == "fugu" and rows[0]["usd"] == pytest.approx(0.005)
    assert all(secret not in json.dumps(rows) for secret in ("prompt-private", "answer-private", "test-only-credential"))


@pytest.mark.parametrize("label", [None, "C"])
def test_class_denied(setup, label):
    assert fugu.generate("hello", data_class=label).reason == "data_class_denied"
    setup[1].post.assert_not_called()


def test_host_denied(setup, monkeypatch):
    monkeypatch.setattr(fugu, "_url", lambda *args: "https://other.example/v1/chat/completions")
    assert fugu.generate("hello", data_class="A").reason == "host_not_allowed"
    setup[1].post.assert_not_called()


@pytest.mark.parametrize("mode", ["env", "file", "halt", "key", "cap", "requests"])
def test_no_send(setup, isolated_env, monkeypatch, mode):
    expected = {"env": "停止中", "file": "停止中", "key": "鍵なし", "cap": "上限到達",
                "requests": fugu.REQUESTS_MISSING}
    if mode == "env":
        monkeypatch.setenv("ORCH_FUGU", "0")
    elif mode == "file":
        (config.data_dir() / ".fugu_disabled").touch()
    elif mode == "halt":
        monkeypatch.setattr(config, "global_halt", lambda: True)
    elif mode == "key":
        monkeypatch.delenv("SAKANA_API_KEY")
    elif mode == "cap":
        monkeypatch.setattr(fugu, "daily_usd", lambda: 0.23)
    else:
        monkeypatch.setattr(fugu, "requests", None)
    if mode == "halt":
        with pytest.raises(config.GlobalHalt):
            fugu.generate("hello", data_class="A")
    else:
        assert fugu.generate("hello", data_class="A").reason == expected[mode]
    setup[1].post.assert_not_called()


@pytest.mark.parametrize("code,reason,usd", [(401, "未認証", 0), (403, "未認証", 0),
    (429, "上限到達(429)", 0), (500, "API障害", 0.05), (302, "API障害(HTTP 302)", 0),
    (400, "API障害(HTTP 400)", 0)])
def test_http(setup, code, reason, usd):
    setup[1].post.return_value = FakeResp(code)
    res = fugu.generate("hello", data_class="A")
    assert (res.rc, res.reason, res.usd) == (2, reason, usd)
    setup[1].post.assert_called_once()
    assert setup[1].post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("kind,reason", [("filter", "安全フィルタ"), ("empty", "空応答"),
    ("json", "解析失敗"), ("malformed", "解析失敗")])
def test_content(setup, kind, reason):
    payload = copy.deepcopy(OK)
    if kind == "filter":
        payload["choices"][0]["finish_reason"] = "content_filter"
    elif kind == "empty":
        payload["choices"][0]["message"]["content"] = " "
    elif kind == "json":
        payload = None
    else:
        payload["choices"] = [42]
    setup[1].post.return_value = FakeResp(200, payload)
    res = fugu.generate("hello", data_class="A")
    assert (res.rc, res.reason) == (3, reason)
    if kind == "json":
        assert res.usd == 0.05


def test_timeout_settles(setup, isolated_env):
    release = threading.Event()
    setup[1].post.side_effect = lambda *a, **k: release.wait(1)
    try:
        res = fugu.generate("hello", data_class="A", timeout=0.01)
        assert (res.rc, res.reason, res.usd) == (2, "タイムアウト", 0.05)
        assert res.sec < 0.8
        ledger = (isolated_env / "data" / "gate_ledger.jsonl").read_text()
        assert '"settle"' in ledger
    finally:
        release.set()


def test_communication_error(setup):
    setup[1].post.side_effect = RuntimeError("private-error")
    res = fugu.generate("hello", data_class="A")
    assert (res.rc, res.reason, res.usd) == (2, "通信失敗", 0.05)


@pytest.mark.parametrize("kind", ["missing", "provider", "state", "model"])
def test_selection(setup, kind):
    path, client = setup
    data = json.loads(path.read_text())
    if kind == "missing":
        data["entries"] = []
    elif kind in ("provider", "state"):
        data["entries"][0][kind] = "hold"
    path.write_text(json.dumps(data))
    kwargs = {"model": "other"} if kind == "model" else {}
    res = fugu.generate("hello", data_class="A", **kwargs)
    assert res.reason == ("model_mismatch" if kind == "model" else "roster_selection")
    client.post.assert_not_called()


def test_check_cli(setup, capsys):
    assert fugu.main(["check", "--no-net"]) == 0
    assert "鍵あり" in capsys.readouterr().out
    setup[1].get.assert_not_called()
    assert fugu.main(["check"]) == 0
    call = setup[1].get.call_args
    assert call.args == ("https://api.sakana.ai/v1/models",)
    assert call.kwargs["allow_redirects"] is False and "json" not in call.kwargs


def test_gen_cli(setup, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("hello"))
    assert fugu.main(["gen", "--data-class", "A", "--max-output", "12"]) == 0
    out = capsys.readouterr()
    assert out.out == "answer-private" and "sec=" in out.err and "usd=0.005000" in out.err
    assert setup[1].post.call_args.kwargs["json"]["max_completion_tokens"] == 12
    setup[1].post.reset_mock()
    monkeypatch.setattr("sys.stdin", io.StringIO("hello"))
    assert fugu.main(["gen"]) == 2
    setup[1].post.assert_not_called()


def test_check_halt_precedes_roster(setup, monkeypatch):
    setup[0].write_text("invalid")
    monkeypatch.setattr(config, "global_halt", lambda: True)
    assert fugu.main(["check", "--quiet"]) == config.HALT_EXIT_CODE
    setup[1].get.assert_not_called()


def test_settlement_failure_stops(setup, monkeypatch):
    stop = Mock()
    monkeypatch.setattr(gate.Budget, "settle", Mock(side_effect=gate.GateDenied("ledger_write")))
    monkeypatch.setattr(gate.Budget, "stop", stop)
    assert fugu.generate("hello", data_class="A").reason == "ledger_write"
    stop.assert_called_once()


def test_logging_failure_does_not_escape(setup, monkeypatch):
    monkeypatch.setattr(usage, "record", Mock(side_effect=OSError))
    monkeypatch.setattr(config, "log_dir", Mock(side_effect=OSError))
    assert fugu.generate("hello", data_class="A").rc == 0


@pytest.mark.parametrize("md,expected", [
    ({"prompt_tokens": 1000, "completion_tokens": 500,
      "completion_tokens_details": {"reasoning_tokens": 200}}, 0.005),
    ({"prompt_tokens": 1000, "completion_tokens": 500,
      "token_details": {"adjustment_tokens": 100}}, 0.0056),
    ({"prompt_tokens": "1000", "completion_tokens": 500}, 0.05),
    ({"prompt_tokens": 1000, "completion_tokens": 500,
      "token_details": {"unknown": 100}}, 0.05),
])
def test_usage(setup, md, expected):
    payload = copy.deepcopy(OK)
    payload["usage"] = md
    setup[1].post.return_value = FakeResp(200, payload)
    assert fugu.generate("hello", data_class="A").usd == pytest.approx(expected)


@pytest.mark.parametrize("price", [None, {}, {"input": "2", "output": 6},
                                  {"input": -1, "output": 6}])
def test_invalid_price_denied(setup, price):
    path, client = setup
    data = json.loads(path.read_text())
    data["entries"][0]["price"] = price
    path.write_text(json.dumps(data))
    assert fugu.generate("hello", data_class="A").reason == "invalid_price"
    client.post.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_denied(setup, timeout):
    assert fugu.generate("hello", data_class="A", timeout=timeout).reason == "invalid_timeout"
    setup[1].post.assert_not_called()


def test_requests_timeout(setup):
    setup[1].post.side_effect = fugu.RequestsTimeout()
    assert fugu.generate("hello", data_class="A").reason == "タイムアウト"


def test_cap_includes_utf8_and_web_allowance(setup, monkeypatch):
    monkeypatch.setenv("ORCH_FUGU_DAILY_USD_CAP", "0.021011")
    assert fugu.generate("あ", data_class="A", max_output_tokens=1).reason == "上限到達"
    setup[1].post.assert_not_called()
