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


@pytest.mark.parametrize("label", [None, "B", "C"])
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
    ("null", "空応答"), ("json", "解析失敗"), ("malformed", "解析失敗")])
def test_content(setup, kind, reason):
    payload = copy.deepcopy(OK)
    if kind == "filter":
        payload["choices"][0]["finish_reason"] = "content_filter"
    elif kind == "empty":
        payload["choices"][0]["message"]["content"] = " "
    elif kind == "null":
        payload["choices"][0]["message"]["content"] = None
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
      "token_details": {"orchestration_output_tokens": 100}}, 0.0056),
    ({"prompt_tokens": "1000", "completion_tokens": 500}, 0.05),
    ({"prompt_tokens": 1000, "completion_tokens": 500,
      "token_details": {"unknown": 100}}, 0.005),
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


def test_halt_immediately_before_gate(setup, monkeypatch):
    halt = Mock(side_effect=[False, False, True])
    gate_call = Mock()
    monkeypatch.setattr(config, "global_halt", halt)
    monkeypatch.setattr(gate, "gate", gate_call)
    with pytest.raises(config.GlobalHalt):
        fugu.generate("hello", data_class="A")
    gate_call.assert_not_called()
    setup[1].post.assert_not_called()


def test_entry_cli_forwarding(setup, monkeypatch):
    roster = json.loads(setup[0].read_text())
    roster["entries"][0].update(id="other-fugu", model="other-model")
    setup[0].write_text(json.dumps(roster))
    monkeypatch.setattr("sys.stdin", io.StringIO("hello"))
    assert fugu.main(["gen", "--entry", "other-fugu", "--data-class", "A"]) == 0
    assert setup[1].post.call_args.kwargs["json"]["model"] == "other-model"


@pytest.mark.parametrize("quiet,expected", [(False, 2), (True, 0)])
def test_failed_check_exit_code(setup, quiet, expected):
    setup[1].get.return_value = FakeResp(401)
    assert fugu.main(["check"] + (["--quiet"] if quiet else [])) == expected


@pytest.mark.parametrize("style", ["chat", "responses", "token_details"])
def test_orchestration_counts_and_accounting(setup, isolated_env, style):
    inp = {"cached_tokens": 400, "orchestration_input_tokens": 200,
           "orchestration_input_cached_tokens": 100}
    out = {"reasoning_tokens": 300, "orchestration_output_tokens": 50}
    md = {"prompt_tokens": 1000, "completion_tokens": 500}
    if style == "chat":
        md.update(prompt_tokens_details=inp, completion_tokens_details=out)
    elif style == "responses":
        md = {"input_tokens": 1000, "output_tokens": 500,
              "input_tokens_details": inp, "output_tokens_details": out}
    else:
        md["token_details"] = dict(inp, **out)
    payload = copy.deepcopy(OK)
    payload["usage"] = md
    setup[1].post.return_value = FakeResp(200, payload)
    res = fugu.generate("hello", data_class="A")
    assert res.usd == pytest.approx(0.0059)
    row = read_ledger(isolated_env)[0]
    assert (row["in_tokens"], row["out_tokens"]) == (1300, 550)
    assert row["usd"] == pytest.approx(res.usd)


@pytest.mark.parametrize("kind", [
    "missing", "timeout", "requests_timeout", "communication", "5xx",
    "json", "non_dict", "malformed", "unknown_chat", "unknown_responses",
    "unknown_generic",
])
def test_unknown_usage_uses_estimate_for_both_ledgers(setup, isolated_env, monkeypatch, kind):
    # 長い UTF-8 入力で見込み額を $0.05 より大きくし、固定額への退行を検出する。
    prompt = "あ" * 6000
    estimate = (len(prompt.encode("utf-8")) * 2 + 2048 * 6) / 1_000_000 + 0.007 * 3
    payload = copy.deepcopy(OK)
    if kind == "missing":
        payload.pop("usage")
    elif kind.startswith("unknown_"):
        detail = {"unknown_chat": "prompt_tokens_details",
                  "unknown_responses": "output_tokens_details",
                  "unknown_generic": "token_details"}[kind]
        payload["usage"][detail] = {"new_orchestration_tokens": 1}
    elif kind == "malformed":
        payload["choices"] = [42]
    elif kind == "non_dict":
        payload = []
    elif kind == "json":
        payload = None
    setup[1].post.return_value = FakeResp(503 if kind == "5xx" else 200, payload)
    errors = {"timeout": TimeoutError, "requests_timeout": fugu.RequestsTimeout,
              "communication": RuntimeError}
    if kind in errors:
        setup[1].post.side_effect = errors[kind]()
    # autospec 相当の束縛を維持し、実際の台帳更新も検証する。
    original = gate.Budget.settle
    calls = []
    def capture(self, *args):
        calls.append(args)
        return original(self, *args)
    monkeypatch.setattr(gate.Budget, "settle", capture)
    res = fugu.generate(prompt, data_class="A")
    assert estimate > fugu.UNKNOWN_USAGE_USD
    assert res.usd == pytest.approx(estimate)
    assert read_ledger(isolated_env)[0]["usd"] == pytest.approx(estimate)
    assert len(calls) == 1 and calls[0][1] == pytest.approx(estimate)
    rows = [json.loads(line) for line in
            (isolated_env / "data" / "gate_ledger.jsonl").read_text().splitlines()]
    assert any(row.get("kind") == "settle" for row in rows)


@pytest.mark.parametrize("value", [-1, 1.5, "1", True, None])
@pytest.mark.parametrize("name", ["orchestration_input_tokens",
                                 "orchestration_input_cached_tokens",
                                 "orchestration_output_tokens"])
def test_invalid_orchestration_value(setup, value, name):
    md = dict(OK["usage"], token_details={name: value})
    with pytest.raises(ValueError, match="invalid_usage"):
        fugu._counts(md)


@pytest.mark.parametrize("value", [-1, 1.5, "1", True, None])
@pytest.mark.parametrize("name", ["input_tokens", "output_tokens"])
def test_invalid_responses_counts(setup, value, name):
    md = {"input_tokens": 1, "output_tokens": 1}
    md[name] = value
    with pytest.raises(ValueError, match="invalid_usage"):
        fugu._counts(md)


def test_chat_counts_take_precedence(setup):
    assert fugu._counts({"prompt_tokens": 1, "completion_tokens": 2,
                         "input_tokens": 10, "output_tokens": 20}) == (1, 2)


@pytest.mark.parametrize("prompt", [None, 123, [], {}, b"hello"])
def test_non_string_prompt(setup, isolated_env, prompt):
    res = fugu.generate(prompt, data_class="A")
    assert (res.rc, res.reason, res.usd) == (2, "入力不正", 0)
    assert read_ledger(isolated_env)[0]["calls"] == 0
    setup[1].post.assert_not_called()


def test_daily_usage_read_failure(setup, monkeypatch):
    monkeypatch.setattr(fugu, "daily_usd", Mock(side_effect=OSError))
    res = fugu.generate("hello", data_class="A")
    assert (res.rc, res.reason, res.usd) == (2, "上限到達", 0)
    setup[1].post.assert_not_called()


# --- 第 4 往復の合意（2026-10-16）: 実行時モデル ID・要照合・unknown の記録 ---
@pytest.mark.parametrize("served,ok", [("fugu-max", True), ("fugu-max-v1.0", True), ("fugu-max-20260615", True), (None, True),
                                       ("fugu-ultra-v2.0", False), ("fugu-max-lite", False), ("fugu-maxi", False),
                                       ("fugu-max-8b-001", False)])
def test_served_model_prefix_match(setup, isolated_env, served, ok):
    body = copy.deepcopy(OK)
    if served is not None:
        body["model"] = served
    setup[1].post.return_value = FakeResp(200, body)
    res = fugu.generate("hello", data_class="A")
    if ok:
        assert res.rc == 0 and res.served == (served or "")
    else:
        assert (res.rc, res.reason, res.text) == (2, "served_model_mismatch", "")
        assert res.usd == pytest.approx(0.005)  # 費用は実額
    assert setup[1].post.call_count == 1
    rows = read_ledger(isolated_env)
    assert rows[-1].get("served", "") == (served or "")
    assert f"served={served or '-'}" in (isolated_env / "logs" / "fugu.log").read_text()


@pytest.mark.parametrize("mode", ["timeout", "500", "no_usage", "not_dict", "bad_choice"])
def test_unknown_flag_recorded(setup, isolated_env, monkeypatch, mode):
    if mode == "not_dict":
        setup[1].post.return_value = FakeResp(200, [])
    elif mode == "bad_choice":  # 使用量は読めるが本文の形が崩れている→控えめな額＋印
        setup[1].post.return_value = FakeResp(200, {"choices": ["x"], "usage": OK["usage"]})
    elif mode == "timeout":
        monkeypatch.setattr(fugu, "_post_with_timeout", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    elif mode == "500":
        setup[1].post.return_value = FakeResp(500, {})
    else:
        setup[1].post.return_value = FakeResp(200, {"choices": [{"message": {"content": "x"}}]})
    res = fugu.generate("hello", data_class="A")
    assert res.unknown is True
    rows = read_ledger(isolated_env)
    if res.rc == 0:
        assert "unknown" not in rows[-1]  # 成功は要照合の回数に数えない（費用は控えめな額）
        assert res.usd >= fugu.UNKNOWN_USAGE_USD
    else:
        assert rows[-1]["unknown"] is True and rows[-1]["status"] == "error"


def test_reconcile_stop_after_two_unknown(setup, isolated_env, monkeypatch):
    for _ in range(2):
        usage.record("fugu", usd=0.05, status="error", unknown=True)
    res = fugu.generate("hello", data_class="A")
    assert (res.rc, res.reason) == (2, "要照合")
    setup[1].post.assert_not_called()
    ok, line = fugu.check_status(net=False)
    assert not ok and "要照合" in line
    monkeypatch.setenv("ORCH_FUGU_RECONCILED", "1")
    assert fugu.generate("hello", data_class="A").rc == 0


def test_served_value_is_sanitized_in_log(setup, isolated_env):
    body = copy.deepcopy(OK); body["model"] = "fugu-max\nrc=0\tx"
    setup[1].post.return_value = FakeResp(200, body)
    res = fugu.generate("hello", data_class="A")
    assert res.served == "fugu-maxrc0x" and res.rc == 2
    log = (isolated_env / "logs" / "fugu.log").read_text()
    assert len(log.splitlines()) == 1 and "served=fugu-maxrc0x" in log


def test_unreadable_ledger_stops(setup, monkeypatch):
    monkeypatch.setattr(usage, "today_unknown", lambda v: (_ for _ in ()).throw(OSError()))
    assert fugu.generate("hello", data_class="A").reason == "要照合"
    setup[1].post.assert_not_called()


@pytest.mark.parametrize("kind", ["row", "jurisdictions", "providers"])
def test_roster_stops_block_network(setup, isolated_env, kind):
    path, client = setup
    data = json.loads(path.read_text())
    entry = data["entries"][0]
    entry["jurisdiction"] = "US"
    if kind == "row":
        entry["stopped"] = True
    else:
        data["stops"] = {kind: ["us" if kind == "jurisdictions" else entry["provider"]]}
    path.write_text(json.dumps(data))
    result = fugu.generate("public", data_class="A")
    assert (result.rc, result.reason) == (2, "entry_stopped")
    client.post.assert_not_called()
    assert not (isolated_env / "data" / "gate_ledger.jsonl").exists()
    assert read_ledger(isolated_env)[-1]["calls"] == 0
