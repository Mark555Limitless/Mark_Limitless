"""Gate fault injection: only temporary rosters/ledgers, no external calls."""

import importlib
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from orch.gate import Budget, GateDenied, check_destination, check_send, classify, gate, load_roster


gate_module = importlib.import_module("orch.gate")
NOW = 1792022400.0
PRIVATE_PATH = "/Us" + "ers/example"
PRIVATE_NAME = "_" + "非公開"
FAKE_SECRET = "sk" + "-" + "FAKE" * 6
FIELDS = "id role provider model version_kind state max_data_class hosts price evidence rollback_to review_by".split()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW)
    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    entry = {"id": "test", "role": "test", "provider": "example", "model": "test-model",
             "version_kind": "snapshot", "state": "adopted", "max_data_class": "A",
             "hosts": ["api.example.test", "redirect.example.test"],
             "price": {"input": 1.0, "output": 3.0}, "evidence": [],
             "rollback_to": "stop", "review_by": "2026-11-01"}
    roster_path = tmp_path / "roster.json"
    ledger = tmp_path / "gate.jsonl"
    return entry, roster_path, ledger


def write_roster(setup):
    entry, roster_path, _ = setup
    roster_path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    return roster_path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def send(setup, **overrides):
    _, _, ledger = setup
    args = dict(roster_path=write_roster(setup), entry_id="test", hops=["https://api.example.test/v1"],
                parts=[("public", "A")], max_chars=100, budget=Budget(ledger, {}), calls=1,
                max_in_tokens=100000, max_out_tokens=100000, task_id="task")
    args.update(overrides)
    return gate(**args)


def assert_denied(setup, **overrides):
    ledger = setup[2]
    before = ledger.read_bytes() if ledger.exists() else b""
    external = Mock()
    with pytest.raises(GateDenied) as error:
        reservation = send(setup, **overrides)
        external(reservation)
    external.assert_not_called()
    assert (ledger.read_bytes() if ledger.exists() else b"") == before
    assert len(error.value.reason) < 80
    assert FAKE_SECRET not in str(error.value)


@pytest.mark.parametrize("state", ["adopted", "trial"])
def test_allowed(setup, state):
    setup[0]["state"] = state
    result = send(setup)
    assert rows(setup[2]) == [result]
    assert result["kind"] == "reserve"
    assert result["estimated_usd"] == 0.4
    assert result["reserved_tokens"] == 200000
    assert result["epoch"] > 0


@pytest.mark.parametrize("hops", [
    ["https://unknown.test"],
    ["https://api.example.test", "https://unknown.test", "https://api.example.test"],
    ["https://api.example.test", "https://unknown.test"],
    ["http://api.example.test"], ["https://127.0.0.1"], ["https://[::1]"],
    ["https://api.example.test:443"], ["https://api.example.test:"],
    ["https://user@api.example.test"], ["https://user:pass@api.example.test"],
    ["https://api.example.test.evil.test"], ["https://sub.api.example.test"],
    ["https://api.example.test."], ["https://api.example.test\\@unknown.test"],
    ["https://api.exam\nple.test"], [" https://api.example.test"],
    ["https://%61pi.example.test"], ["https://[invalid"], [], None,
    "https://api.example.test", [None], ["//api.example.test"],
])
def test_bad_destinations(setup, hops):
    assert_denied(setup, hops=hops)


def test_case_and_all_hops(setup):
    setup[0]["hosts"] = ["API.EXAMPLE.TEST", "redirect.example.test"]
    send(setup, hops=iter(["HTTPS://api.example.test/x", "https://REDIRECT.example.test/y"]))


@pytest.mark.parametrize("hosts", [[], None, "api.example.test", ["127.0.0.1"], ["2130706433"],
                                        ["0x7f000001"], ["127.1"], ["0177.0.0.1"],
                                        ["api.example.test:443"], ["*.example.test"], [None]])
def test_invalid_host_allowlist(setup, hosts):
    setup[0]["hosts"] = hosts
    assert_denied(setup)


@pytest.mark.parametrize("state", ["candidate", "hold", "stopped", "rejected", "retired", None])
def test_inactive(setup, state):
    setup[0]["state"] = state
    assert_denied(setup)


def test_unknown_id(setup):
    assert_denied(setup, entry_id="absent")


@pytest.mark.parametrize("parts", [[("private", "B")], [("unlabelled", None)], [("unknown", "D")],
                                    [(PRIVATE_PATH, "A")], [(PRIVATE_NAME, "A")], [(FAKE_SECRET, "A")],
                                    [("safe", "A"), ("private", "B")], [("secret", "C")],
                                    [("/Us", "A"), ("ers/example", "A")],
                                    [("sk-", "A"), ("FAKE" * 6, "A")]])
def test_data_refused(setup, parts):
    assert_denied(setup, parts=parts)


@pytest.mark.parametrize("text", ["AI" + "za" + "FAKE" * 8, "AQ" + "." + "FAKE" * 6,
                                   "Bearer " + "FAKE" * 4])
def test_other_secret_shapes(setup, text):
    assert classify([(text, "A")]) == "C"
    assert_denied(setup, parts=[(text, "A")])


def test_class_composition_and_generator(setup):
    setup[0]["max_data_class"] = "B"
    assert classify([("a", "A"), ("b", "B")]) == "B"
    assert classify([("a", "B"), ("b", "A")]) == "B"
    assert classify([("a", "B"), ("b", None)]) == "C"
    send(setup, parts=iter([("a", "A"), ("b", "B")]), max_chars=2)


@pytest.mark.parametrize("label", ["C", "D", None, []])
def test_invalid_class_limit(setup, label):
    setup[0]["max_data_class"] = label
    assert_denied(setup)


@pytest.mark.parametrize("bad", [None, [None], [(1, "A")], [("x",)], "text"])
def test_malformed_parts(setup, bad):
    assert_denied(setup, parts=bad)


def test_character_boundary(setup):
    send(setup, parts=[("日本", "A"), ("語", "A")], max_chars=3)
    assert_denied(setup, parts=[("日本", "A"), ("語x", "A")], max_chars=3, task_id="next")


@pytest.mark.parametrize("bad", [-1, None, True, 1.5])
def test_invalid_character_limit(setup, bad):
    assert_denied(setup, max_chars=bad)


@pytest.mark.parametrize("field", ["input", "output"])
@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), float("-inf"), "1", None, True, {}])
def test_invalid_prices(setup, field, bad):
    setup[0]["price"][field] = bad
    assert_denied(setup)


@pytest.mark.parametrize("price", [None, {}, "free"])
def test_unknown_price(setup, price):
    setup[0]["price"] = price
    assert_denied(setup)


@pytest.mark.parametrize("cap,limit", [("usd_per_day", 0.4), ("calls_per_day", 1), ("tokens_per_day", 200000)])
def test_caps_equal_then_exceeded(setup, cap, limit):
    budget = Budget(setup[2], {cap: limit})
    send(setup, budget=budget)
    assert_denied(setup, budget=Budget(setup[2], {cap: limit}), task_id="next")


@pytest.mark.parametrize("cap,limit", [("usd_per_day", 0.399999), ("calls_per_day", 0), ("tokens_per_day", 199999)])
def test_caps_reject_first_call(setup, cap, limit):
    assert_denied(setup, budget=Budget(setup[2], {cap: limit}))


def test_amount_boundary_one_dollar_more(setup):
    setup[0]["price"] = {"input": 1, "output": 0}
    budget = Budget(setup[2], {"usd_per_day": 1})
    assert_denied(setup, budget=budget, max_in_tokens=2000000, max_out_tokens=0)
    send(setup, budget=budget, max_in_tokens=1000000, max_out_tokens=0)


def test_decimal_budget_boundary(setup):
    setup[0]["price"] = {"input": 1, "output": 0}
    budget = Budget(setup[2], {"usd_per_day": 0.3})
    for index in range(3):
        send(setup, budget=budget, max_out_tokens=0, task_id=str(index))
    assert_denied(setup, budget=budget, max_in_tokens=1, max_out_tokens=0, task_id="extra")


def test_large_integer_amount_cannot_round_down_past_cap(setup):
    setup[0]["price"] = {"input": 10000000000000001, "output": 0}
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 10000000000000000}),
                  max_in_tokens=1000000, max_out_tokens=0)
    result = send(setup, budget=Budget(setup[2], {"usd_per_day": 10000000000000001}),
                  max_in_tokens=1000000, max_out_tokens=0)
    assert result["estimated_usd"] == 10000000000000001
    assert type(result["estimated_usd"]) is int


def test_fractional_amount_losing_json_precision_is_refused(setup):
    setup[0]["price"] = {"input": 10000000000000001, "output": 0}
    assert_denied(setup, max_in_tokens=1, max_out_tokens=0)


def test_large_and_small_amounts_are_summed_exactly(setup):
    setup[0]["price"] = {"input": 1, "output": 0}
    send(setup, max_in_tokens=10 ** 40, max_out_tokens=0)
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 10 ** 34}),
                  max_in_tokens=1000000, max_out_tokens=0, task_id="next")


def test_unrepresentable_fraction_raises_gate_denied(setup):
    setup[0]["price"] = {"input": 10 ** 400 + 1, "output": 0}
    assert_denied(setup, max_in_tokens=1, max_out_tokens=0)


@pytest.mark.parametrize("number", ["1e-400", "1e400", "0.10000000000000001"])
def test_json_price_cannot_lose_precision_during_loading(setup, number):
    text = json.dumps({"entries": [setup[0]]}).replace('"input": 1.0', '"input": ' + number)
    setup[1].write_text(text)
    with pytest.raises(GateDenied):
        gate(setup[1], "test", ["https://api.example.test"], [("ok", "A")], 100,
             Budget(setup[2], {}), 1, 1, 0, "task")
    assert not setup[2].exists()


@pytest.mark.parametrize("bad", [None, object(), Mock()])
def test_invalid_budget_cannot_bypass_reservation(setup, bad):
    assert_denied(setup, budget=bad)
    if isinstance(bad, Mock):
        bad.reserve.assert_not_called()


@pytest.mark.parametrize("caps", [{"usd_per_day": "1"}, {"usd_per_day": -1},
                                     {"seconds_per_task": float("nan")}, {"calls_per_day": True},
                                     {"unknown": 1}, None])
def test_invalid_caps(setup, caps):
    with pytest.raises(GateDenied):
        Budget(setup[2], caps)
    assert not setup[2].exists()


@pytest.mark.parametrize("field", ["calls", "max_in_tokens", "max_out_tokens"])
@pytest.mark.parametrize("bad", [-1, True, 1.5, "1", float("inf")])
def test_invalid_counts(setup, field, bad):
    assert_denied(setup, **{field: bad})


def test_zero_calls(setup):
    assert_denied(setup, calls=0)


def test_double_reservation_after_restart(setup):
    send(setup)
    assert_denied(setup, budget=Budget(setup[2], {}))


@pytest.mark.parametrize("mode", ["true", "raise", "non_boolean"])
def test_detector_fail_closed(setup, mode):
    def detector(text):
        if mode == "raise":
            raise RuntimeError(FAKE_SECRET)
        return True if mode == "true" else None
    assert_denied(setup, detector=detector)


def test_detector_safe_and_combined(setup):
    detector = Mock(return_value=False)
    send(setup, parts=[("one", "A"), ("two", "A")], detector=detector)
    assert [call.args[0] for call in detector.call_args_list] == ["one", "two", "onetwo"]
    assert_denied(setup, task_id="next", parts=[("one", "A"), ("two", "A")],
                  detector=lambda text: text == "onetwo")


@pytest.mark.parametrize("field", FIELDS)
def test_missing_roster_fields(setup, field):
    del setup[0][field]
    assert_denied(setup)


@pytest.mark.parametrize("text", ["{", "[]", "null", '{"entries": {}}', '{"entries": [null]}',
                                   '{"entries": [], "entries": []}'])
def test_malformed_roster(setup, text):
    setup[1].write_text(text)
    with pytest.raises(GateDenied):
        load_roster(setup[1])


def test_missing_and_duplicate_roster(setup):
    with pytest.raises(GateDenied):
        load_roster(setup[1])
    setup[1].write_text(json.dumps({"entries": [setup[0], setup[0]]}))
    with pytest.raises(GateDenied):
        load_roster(setup[1])


@pytest.mark.parametrize("text", ["broken\n", "{}\n", "null\n", "\n", '{"kind": "reserve"}',
                                   '{"kind": "stop", "at": "bad", "epoch": 0}\n'])
def test_corrupt_ledger(setup, text):
    setup[2].write_text(text)
    assert_denied(setup)


@pytest.mark.parametrize("field", ["estimated_usd", "reserved_tokens", "calls", "epoch", "at", "deadline"])
@pytest.mark.parametrize("bad", ["0", -1, float("nan"), float("inf"), True])
def test_corrupt_reservation_values(setup, field, bad):
    result = send(setup)
    result[field] = bad
    setup[2].write_text(json.dumps(result) + "\n")
    assert_denied(setup, task_id="next")


def test_settlement_replaces_estimate_without_refunding_calls(setup):
    result = send(setup)
    budget = Budget(setup[2], {"usd_per_day": 0.6, "tokens_per_day": 200010, "calls_per_day": 2})
    budget.settle("task", 0.2, 10, result["epoch"])
    send(setup, budget=budget, task_id="next")
    assert_denied(setup, budget=budget, task_id="third")


@pytest.mark.parametrize("actual,warning,stopped", [(0.599, False, False), (0.6, True, False),
                                                  (0.799, True, False), (0.8, True, True), (0.9, True, True)])
def test_overruns(setup, actual, warning, stopped):
    result = send(setup)
    settled = Budget(setup[2], {}).settle("task", actual, 12, result["epoch"])
    assert settled["warning"] is warning
    assert settled["stopped"] is stopped
    if stopped:
        assert_denied(setup)
    else:
        later = send(setup)
        assert later["epoch"] > result["epoch"]


@pytest.mark.parametrize("actual,stopped", [(0, False), (0.01, True)])
def test_zero_price(setup, actual, stopped):
    setup[0]["price"] = {"input": 0, "output": 0}
    result = send(setup)
    settled = Budget(setup[2], {}).settle("task", actual, 0, result["epoch"])
    assert settled["stopped"] is stopped


@pytest.mark.parametrize("explicit", [False, True])
def test_late_settlement_not_applied_after_restart(setup, explicit):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    budget.stop(reservation["epoch"]) if explicit else budget.stop()
    result = Budget(setup[2], {}).settle("task", 0, 0, reservation["epoch"])
    assert result["kind"] == "late"
    assert all(row["kind"] != "settle" for row in rows(setup[2]))
    assert_denied(setup)  # Original reservation remains pending.
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 0.4}), task_id="other")
    fresh = send(setup, task_id="fresh")
    assert fresh["epoch"] > reservation["epoch"]
    assert Budget(setup[2], {}).settle("fresh", 0.4, 1, fresh["epoch"])["kind"] == "settle"


def test_duplicate_and_wrong_settlements(setup):
    result = send(setup)
    budget = Budget(setup[2], {})
    for task, epoch in [("other", result["epoch"]), ("task", 500)]:
        with pytest.raises(GateDenied):
            budget.settle(task, 0.2, 1, epoch)
    budget.settle("task", 0.2, 1, result["epoch"])
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied):
        budget.settle("task", 0.2, 1, result["epoch"])
    assert setup[2].read_bytes() == before


def test_recreated_ledger_cannot_apply_response_from_previous_generation(setup):
    old = send(setup)
    Budget(setup[2], {}).stop()
    setup[2].write_text("")  # Simulate lost ledger; accounting recovery is out of scope.
    fresh = send(setup)
    assert fresh["epoch"] != old["epoch"]
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied):
        Budget(setup[2], {}).settle("task", 0, 0, old["epoch"])
    assert setup[2].read_bytes() == before


def test_stopping_older_epoch_does_not_invalidate_newer_reservation(setup):
    old = send(setup)
    new = send(setup, task_id="new")
    budget = Budget(setup[2], {})
    budget.stop(old["epoch"])
    assert budget.settle("task", 0, 0, old["epoch"])["kind"] == "late"
    assert budget.settle("new", 0.2, 1, new["epoch"])["kind"] == "settle"


def test_stop_requires_known_explicit_epoch_and_allows_empty_noop(setup):
    budget = Budget(setup[2], {})
    assert budget.stop()["epoch"] == 0
    reservation = send(setup)
    before = setup[2].read_bytes()
    for bad in [0, -1, True, "1", reservation["epoch"] - 1, reservation["epoch"] + 1]:
        with pytest.raises(GateDenied):
            budget.stop(bad)
    assert setup[2].read_bytes() == before


@pytest.mark.parametrize("field", ["actual_usd", "actual_tokens"])
@pytest.mark.parametrize("bad", ["0", -1, float("nan"), float("inf"), True])
def test_invalid_settlement_values(setup, field, bad):
    result = send(setup)
    values = dict(task_id="task", actual_usd=0.1, actual_tokens=1, epoch=result["epoch"])
    values[field] = bad
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied):
        Budget(setup[2], {}).settle(**values)
    assert setup[2].read_bytes() == before


def test_corrupt_settlement_blocks_new_reservation(setup):
    result = send(setup)
    Budget(setup[2], {}).settle("task", 0.1, 1, result["epoch"])
    ledger_rows = rows(setup[2])
    ledger_rows[-1]["actual_usd"] = "invalid"
    setup[2].write_text("".join(json.dumps(row) + "\n" for row in ledger_rows))
    assert_denied(setup, task_id="next")


def test_time_cap_persists_across_settlements_and_restart(setup, monkeypatch):
    budget = Budget(setup[2], {"seconds_per_task": 10})
    result = send(setup, budget=budget)
    assert result["deadline"] == NOW + 10
    budget.settle("task", 0.2, 1, result["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 10)
    second = send(setup, budget=Budget(setup[2], {"seconds_per_task": 10}))
    budget.settle("task", 0.2, 1, second["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 11)
    assert_denied(setup, budget=Budget(setup[2], {"seconds_per_task": 10}))


def test_settlement_after_deadline_stops_task(setup, monkeypatch):
    result = send(setup, budget=Budget(setup[2], {"seconds_per_task": 10}))
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 11)
    settled = Budget(setup[2], {}).settle("task", 0.2, 1, result["epoch"])
    assert settled["stopped"] is True
    assert_denied(setup)


def test_daily_rollover_pending_and_settled(setup, monkeypatch):
    result = send(setup)
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 86400)
    assert_denied(setup, budget=Budget(setup[2], {"calls_per_day": 1}), task_id="next")
    Budget(setup[2], {}).settle("task", 0.2, 10, result["epoch"])
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 0.5}), task_id="next")
    send(setup, budget=Budget(setup[2], {"usd_per_day": 0.6, "calls_per_day": 1}), task_id="next")
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 2 * 86400)
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 0.7}), task_id="third")


def test_old_settled_usage_does_not_count_today(setup, monkeypatch):
    result = send(setup)
    Budget(setup[2], {}).settle("task", 0.4, 10, result["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 86400)
    send(setup, budget=Budget(setup[2], {"usd_per_day": 0.4}), task_id="next")


def test_concurrent_reservations_respect_cap(setup):
    def reserve(index):
        try:
            return Budget(setup[2], {"calls_per_day": 1}).reserve(setup[0], 1, 1, 1, str(index))
        except GateDenied:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(16)))
    assert sum(result is not None for result in results) == 1
    assert len(rows(setup[2])) == 1


def test_no_payload_or_raw_identifier_in_ledger(setup):
    result = send(setup, task_id=FAKE_SECRET)
    Budget(setup[2], {}).settle(FAKE_SECRET, 0.2, 1, result["epoch"])
    text = setup[2].read_text()
    assert FAKE_SECRET not in text
    assert "public" not in text


def test_io_errors_are_denials(setup, tmp_path):
    assert_denied(setup, budget=Budget(tmp_path / "missing" / "ledger", {}))
    assert_denied(setup, budget=Budget(tmp_path, {}))


def test_standalone_checks(setup):
    roster = load_roster(write_roster(setup))
    assert check_destination(roster, "test", ["https://api.example.test"]) == setup[0]
    assert check_send(roster, "test", [("ok", "A")], 2) == "A"
    assert not setup[2].exists()
