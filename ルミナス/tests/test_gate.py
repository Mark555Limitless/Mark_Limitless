"""Gate fault injection: only temporary rosters/ledgers, no external calls."""

import importlib
import json
import multiprocessing
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

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
             "rollback_to": "stop", "review_by": "2026-11-01", "caps": {"calls_per_day": 1000}}
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


def assert_denied(setup, reason=None, **overrides):
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
    if reason is not None:
        assert error.value.reason == reason


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
        bad._reserve.assert_not_called()


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
    assert_denied(setup, budget=Budget(setup[2], {}), reason="task_unavailable")


@pytest.mark.parametrize("mode", ["true", "raise", "non_boolean"])
def test_detector_fail_closed(setup, mode):
    def detector(text):
        if mode == "raise":
            raise RuntimeError(FAKE_SECRET)
        return True if mode == "true" else None
    assert_denied(setup, detector=detector, reason="detector_error" if mode == "raise" else "detector_denied")


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
def test_late_settlement_closes_reservation_after_restart(setup, explicit):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    budget.stop(reservation["epoch"]) if explicit else budget.stop()
    result = Budget(setup[2], {}).settle("task", 0, 0, reservation["epoch"])
    assert result["kind"] == "late"
    assert all(row["kind"] != "settle" for row in rows(setup[2]))
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied) as error:
        budget.settle("task", 0, 0, reservation["epoch"])
    assert error.value.reason == "already_settled"
    assert setup[2].read_bytes() == before
    fresh = send(setup, budget=Budget(setup[2], {"usd_per_day": 0.4}))
    assert fresh["epoch"] > reservation["epoch"]
    assert Budget(setup[2], {}).settle("task", 0.4, 1, fresh["epoch"])["kind"] == "settle"


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
@pytest.mark.parametrize("bad", ["0", -1, float("nan"), float("inf"), True, None])
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
    path = write_roster(setup)
    def reserve(index):
        try:
            return gate(path, "test", ["https://api.example.test"], [("ok", "A")], 2,
                        Budget(setup[2], {"calls_per_day": 1}), 1, 1, 1, str(index))
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


@pytest.mark.parametrize("caller_limit", [None, 1, 0.3])
def test_roster_and_caller_use_stricter_cap(setup, caller_limit):
    setup[0]["caps"] = {"usd_per_day": 0.35}
    caller_caps = {} if caller_limit is None else {"usd_per_day": caller_limit}
    budget = Budget(setup[2], caller_caps)
    assert_denied(setup, budget=budget, reason="budget_exceeded")
    # Caller wins when stricter, even when the roster would allow this amount.
    if caller_limit == 0.3:
        assert_denied(setup, budget=budget, max_in_tokens=310000, max_out_tokens=0,
                      reason="budget_exceeded")


@pytest.mark.parametrize("caps", [{"unknown": 1}, None, [], {"usd_per_month": "1"},
                                  {"usd_per_day": -1}, {"calls_per_day": True}])
def test_invalid_roster_caps(setup, caps):
    setup[0]["caps"] = caps
    assert_denied(setup, reason="invalid_caps")


@pytest.mark.parametrize("present", [True, False])
def test_no_limits_denied(setup, present):
    if present:
        setup[0]["caps"] = {}
    else:
        del setup[0]["caps"]
    assert_denied(setup, reason="missing_caps")


def test_caller_only_cap_still_works(setup):
    del setup[0]["caps"]
    budget = Budget(setup[2], {"calls_per_day": 1})
    send(setup, budget=budget)
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")


def test_caps_union_and_entry_limits_do_not_mutate_budget(setup):
    budget = Budget(setup[2], {"calls_per_day": 1})
    original_caps = dict(budget.caps)
    setup[0]["caps"] = {"usd_per_day": 0.3}
    assert_denied(setup, budget=budget, reason="budget_exceeded")
    setup[0]["caps"] = {"usd_per_day": 0.4}
    reservation = send(setup, budget=budget)
    budget.settle("task", 0, 0, reservation["epoch"])
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")
    assert budget.caps == original_caps


def jst_timestamp(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute,
                    tzinfo=timezone(timedelta(hours=9))).timestamp()


@pytest.mark.parametrize("year,month,day", [(2026, 10, 31), (2026, 12, 31)])
def test_monthly_limit_uses_jst_calendar_month(setup, monkeypatch, year, month, day):
    last_minute = jst_timestamp(year, month, day, 23, 59)
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute - 86400)
    setup[0]["caps"] = {"usd_per_month": 0.4}
    budget = Budget(setup[2], {})
    reservation = send(setup, budget=budget)
    budget.settle("task", 0.4, 1, reservation["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute)
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute + 60)
    send(setup, budget=budget, task_id="next")
    assert_denied(setup, budget=budget, task_id="third", reason="budget_exceeded")


def test_pending_reservation_counts_in_next_month(setup, monkeypatch):
    last_minute = jst_timestamp(2026, 10, 31, 23, 59)
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute)
    budget = Budget(setup[2], {"usd_per_month": 0.4})
    reservation = send(setup, budget=budget)
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute + 60)
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")
    budget.settle("task", 0.1, 1, reservation["epoch"])
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")
    send(setup, budget=budget, task_id="next", max_in_tokens=300000, max_out_tokens=0)


def test_day_boundary_is_midnight_jst(setup, monkeypatch):
    last_minute = jst_timestamp(2026, 10, 15, 23, 59)
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute)
    budget = Budget(setup[2], {"usd_per_day": 0.4, "calls_per_day": 1})
    reservation = send(setup, budget=budget)
    budget.settle("task", 0.4, 1, reservation["epoch"])
    assert_denied(setup, budget=budget, task_id="next", reason="budget_exceeded")
    monkeypatch.setattr(gate_module.time, "time", lambda: last_minute + 60)
    send(setup, budget=budget, task_id="next")


@pytest.mark.parametrize("settle_x", [False, True])
@pytest.mark.parametrize("cap,limit", [("usd_per_day", 0.4), ("usd_per_month", 0.4),
                                      ("calls_per_day", 1), ("tokens_per_day", 200000)])
def test_shared_ledger_accounts_only_for_selected_entry(setup, settle_x, cap, limit):
    setup[0]["caps"] = {cap: limit}
    reservation = send(setup)
    if settle_x:
        settled = Budget(setup[2], {}).settle("task", 0.4, 200000, reservation["epoch"])
        assert settled["entry_id"] == "test"
    other = dict(setup[0], id="other")
    setup[1].write_text(json.dumps({"entries": [setup[0], other]}))
    budget = Budget(setup[2], {})
    result = gate(setup[1], "other", ["https://api.example.test"], [("ok", "A")],
                  10, budget, 1, 100000, 100000, "other-task")
    assert result["entry_id"] == "other"
    assert reservation["entry_id"] == "test"
    assert_denied(setup, task_id="third", reason="budget_exceeded")


@pytest.mark.parametrize("actual", [0.1, None])
def test_late_charge_once_on_receipt_day_then_expires(setup, monkeypatch, actual):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    budget.stop()
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 86400)
    closed = Budget(setup[2], {}).settle("task", actual, None, reservation["epoch"])
    amount = 0.4 if actual is None else actual
    assert closed["actual_usd"] == amount
    assert closed["actual_tokens"] == reservation["reserved_tokens"]
    assert closed["entry_id"] == reservation["entry_id"]
    assert_denied(setup, task_id="other", budget=Budget(setup[2], {"usd_per_day": amount}),
                  reason="budget_exceeded")
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied) as error:
        budget.settle("task", actual, None, reservation["epoch"])
    assert error.value.reason == "already_settled"
    assert setup[2].read_bytes() == before
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 2 * 86400)
    send(setup, budget=Budget(setup[2], {"usd_per_day": 0.4, "calls_per_day": 1,
                                      "tokens_per_day": 200000}))


@pytest.mark.parametrize("late", [False, True])
def test_stopped_task_requires_explicit_release(setup, late):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    if late:
        budget.stop()
    budget.settle("task", 0.8, 1, reservation["epoch"])
    assert_denied(setup, reason="task_unavailable")
    release = Budget(setup[2], {}).release("task", "reviewed overrun")
    assert release["kind"] == "release"
    assert release["entry_id"] == "test"
    assert rows(setup[2])[-1] == release
    # Release clears only the task stop, not historical budget consumption.
    assert_denied(setup, budget=Budget(setup[2], {"usd_per_day": 0.8}),
                  reason="budget_exceeded")
    fresh = send(setup)
    assert fresh["epoch"] > reservation["epoch"]
    budget.settle("task", 0.8, 1, fresh["epoch"])
    assert_denied(setup, reason="task_unavailable")
    budget.release("task", "second review")
    send(setup)


def test_release_resets_expired_task_window(setup, monkeypatch):
    budget = Budget(setup[2], {"seconds_per_task": 10})
    reservation = send(setup, budget=budget)
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 11)
    budget.settle("task", 0.4, 1, reservation["epoch"])
    budget.release("task", "reviewed timeout")
    assert send(setup, budget=budget)["deadline"] == NOW + 21


def test_time_limit_uses_only_selected_entry_history(setup, monkeypatch):
    setup[0]["caps"] = {"seconds_per_task": 10}
    budget = Budget(setup[2], {})
    reservation = send(setup, budget=budget)
    budget.settle("task", 0.4, 1, reservation["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 11)
    assert_denied(setup, budget=budget, reason="task_timeout")
    other = dict(setup[0], id="other")
    setup[1].write_text(json.dumps({"entries": [setup[0], other]}))
    result = gate(setup[1], "other", ["https://api.example.test"], [("ok", "A")],
                  10, budget, 1, 100000, 100000, "task")
    assert result["deadline"] == NOW + 21


def test_release_cannot_replay_old_stop_epoch(setup):
    budget = Budget(setup[2], {})
    first = send(setup)
    budget.settle("task", 0.8, 1, first["epoch"])
    release = budget.release("task", "first review")
    second = send(setup)
    budget.settle("task", 0.8, 1, second["epoch"])
    with setup[2].open("a") as stream:
        stream.write(json.dumps(release) + "\n")
    assert_denied(setup, reason="ledger_release")


@pytest.mark.parametrize("kind", ["reserve", "settle", "late", "release"])
@pytest.mark.parametrize("invalid_id", [None, "", 1])
def test_corrupt_entry_id_blocks_ledger_replay(setup, kind, invalid_id):
    budget = Budget(setup[2], {})
    reservation = send(setup)
    if kind == "late":
        budget.stop()
    if kind != "reserve":
        budget.settle("task", 0.8, 1, reservation["epoch"])
    if kind == "release":
        budget.release("task", "review")
    ledger_rows = rows(setup[2])
    ledger_rows[-1]["entry_id"] = invalid_id
    setup[2].write_text("".join(json.dumps(row) + "\n" for row in ledger_rows))
    assert_denied(setup, task_id="next", reason="ledger_entry")


def test_settlement_entry_cannot_be_reassigned(setup):
    reservation = send(setup)
    Budget(setup[2], {}).settle("task", 0.4, 1, reservation["epoch"])
    ledger_rows = rows(setup[2])
    ledger_rows[-1]["entry_id"] = "other"
    setup[2].write_text("".join(json.dumps(row) + "\n" for row in ledger_rows))
    assert_denied(setup, task_id="next", reason="ledger_task")


@pytest.mark.parametrize("reason", [None, "", " ", 1])
def test_release_requires_reason(setup, reason):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    budget.settle("task", 0.8, 1, reservation["epoch"])
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied) as error:
        budget.release("task", reason)
    assert error.value.reason == "invalid_release_reason"
    assert setup[2].read_bytes() == before
    assert_denied(setup, reason="task_unavailable")


def test_release_cannot_clear_pending_or_unknown_task(setup):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    for task in ("task", "unknown"):
        with pytest.raises(GateDenied) as error:
            budget.release(task, "review")
        assert error.value.reason == "task_not_stopped"
    assert_denied(setup, reason="task_unavailable")
    budget.settle("task", 0.8, 1, reservation["epoch"])
    budget.release("task", FAKE_SECRET)
    assert FAKE_SECRET not in setup[2].read_text()
    before = setup[2].read_bytes()
    with pytest.raises(GateDenied) as error:
        budget.release("task", "duplicate")
    assert error.value.reason == "task_not_stopped"
    assert setup[2].read_bytes() == before


@pytest.mark.parametrize("in_allowlist", [False, True])
def test_non_ascii_host_cannot_lowercase_to_ascii(setup, in_allowlist):
    setup[0]["hosts"] = ["\u212a.example.test" if in_allowlist else "k.example.test"]
    hop = "https://k.example.test" if in_allowlist else "https://\u212a.example.test"
    assert_denied(setup, hops=[hop], reason="invalid_host")


@pytest.mark.parametrize("parts", [[(PRIVATE_PATH.lower(), "A")], [(PRIVATE_PATH.swapcase(), "A")],
                                  [("/us", "A"), ("ers/example", "A")]])
def test_private_paths_ignore_case(setup, parts):
    assert classify(parts) == "C"
    assert_denied(setup, parts=parts, reason="data_class_denied")


@pytest.mark.parametrize("overrides,reason", [
    ({"hops": ["https://unknown.test"]}, "host_not_allowed"),
    ({"hops": ["https://api.example.test", "https://unknown.test"]}, "host_not_allowed"),
    ({"hops": ["https://api.example.test", "https://unknown.test", "https://api.example.test"]},
     "host_not_allowed"),
    ({"parts": [("public", "B")]}, "data_class_denied"),
])
def test_fault_reason_codes(setup, overrides, reason):
    assert_denied(setup, reason=reason, **overrides)


def test_unknown_price_reason(setup):
    setup[0]["price"] = None
    assert_denied(setup, reason="unknown_price")


def _process_reserve(ledger, path, barrier, results):
    """Spawn-safe worker: no sockets, APIs or subprocess commands."""
    original_read = Budget._read

    def slow_read(self, stream):
        state = original_read(self, stream)
        # Widen the read/write race: removing flock must overbook the cap.
        gate_module.time.sleep(0.15)
        return state

    with patch.object(Budget, "_read", slow_read), patch.object(gate_module.time, "time", return_value=NOW):
        barrier.wait(timeout=20)
        try:
            gate(path, "test", ["https://api.example.test"], [("ok", "A")], 2,
                 Budget(ledger, {"calls_per_day": 1}), 1, 1, 1,
                 str(multiprocessing.current_process().pid))
        except GateDenied as error:
            results.put(error.reason)
        else:
            results.put("reserved")


def test_multiprocess_reservations_respect_cap(setup):
    path = write_roster(setup)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(8)
    results = context.Queue()
    processes = [context.Process(target=_process_reserve, args=(setup[2], path, barrier, results))
                 for _ in range(8)]
    try:
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert outcomes.count("reserved") == 1
        assert outcomes.count("budget_exceeded") == 7
        assert len(rows(setup[2])) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=5)
        results.close()
        results.join_thread()


@pytest.mark.parametrize("kind", ["reserve", "settle", "late", "release"])
def test_legacy_row_without_entry_id_has_specific_reason(setup, kind):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    if kind == "late":
        budget.stop()
    if kind != "reserve":
        budget.settle("task", 0.8, 1, reservation["epoch"])
    if kind == "release":
        budget.release("task", "review")
    ledger = rows(setup[2])
    del ledger[-1]["entry_id"]
    setup[2].write_text("".join(json.dumps(row) + "\n" for row in ledger))
    assert_denied(setup, task_id="next", reason="ledger_entry")


def test_release_keeps_other_entry_time_window(setup, monkeypatch):
    setup[0]["caps"] = {"seconds_per_task": 10}
    budget = Budget(setup[2], {})
    first = send(setup)
    budget.settle("task", 0.4, 1, first["epoch"])
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 5)
    setup[1].write_text(json.dumps({"entries": [setup[0], dict(setup[0], id="other")]}))
    other = gate(setup[1], "other", ["https://api.example.test"], [("ok", "A")],
                 2, budget, 1, 100000, 100000, "task")
    budget.settle("task", 0.8, 1, other["epoch"])
    budget.release("task", "review other only")
    monkeypatch.setattr(gate_module.time, "time", lambda: NOW + 11)
    assert_denied(setup, reason="task_timeout")


def test_reservation_is_internal_and_gate_enforces_roster_caps(setup):
    assert not hasattr(Budget, "reserve")
    setup[0]["caps"] = {"calls_per_day": 0}
    assert_denied(setup, budget=Budget(setup[2], {"calls_per_day": 100}), reason="budget_exceeded")


def test_human_closes_abandoned_reservation_at_estimate(setup):
    reservation = send(setup)
    budget = Budget(setup[2], {})
    budget.stop()
    closed = budget.settle("task", None, None, reservation["epoch"])
    assert closed["kind"] == "late"
    assert closed["actual_usd"] == reservation["estimated_usd"]
    assert closed["actual_tokens"] == reservation["reserved_tokens"]
    assert_denied(setup, task_id="next", budget=Budget(setup[2], {"usd_per_day": 0.4}),
                  reason="budget_exceeded")


@pytest.mark.parametrize("kind", ["row", "jurisdictions", "providers"])
@pytest.mark.parametrize("existing", [False, True])
def test_roster_stop_denies_before_reservation(setup, monkeypatch, kind, existing):
    entry, path, ledger = setup
    if existing:
        send(setup)
    data = {"entries": [entry]}
    entry["jurisdiction"] = "US"
    if kind == "row":
        entry["stopped"] = True
    else:
        data["stops"] = {kind: ["us" if kind == "jurisdictions" else entry["provider"]]}
    path.write_text(json.dumps(data))
    before = ledger.read_bytes() if existing else None
    reserve = Mock(side_effect=AssertionError("reservation forbidden"))
    monkeypatch.setattr(Budget, "_reserve", reserve)
    with pytest.raises(GateDenied, match="^entry_stopped$"):
        gate(path, "test", ["https://api.example.test"], [("public", "A")],
             100, Budget(ledger, {}), 1, 10, 10, "blocked")
    reserve.assert_not_called()
    assert (ledger.read_bytes() if ledger.exists() else None) == before
    for check in (lambda: check_destination(data, "test", ["https://api.example.test"]),
                  lambda: check_send(data, "test", [("public", "A")], 100)):
        with pytest.raises(GateDenied, match="^entry_stopped$"):
            check()


@pytest.mark.parametrize("stops", [None, "stop", 1, [],
    {"jurisdictions": "US"}, {"providers": 1}, {"providers": None},
    {"jurisdictions": [1]}, {"providers": ["example", 1]},
])
def test_invalid_bulk_stops(setup, stops):
    entry, path, ledger = setup
    data = {"entries": [entry], "stops": stops}
    path.write_text(json.dumps(data))
    for check in (lambda: load_roster(path),
                  lambda: check_destination(data, "test", ["https://api.example.test"]),
                  lambda: check_send(data, "test", [("public", "A")], 100),
                  lambda: gate(path, "test", ["https://api.example.test"],
                               [("public", "A")], 100, Budget(ledger, {}), 1, 10, 10, "task")):
        with pytest.raises(GateDenied, match="^invalid_stops$"):
            check()
    assert not ledger.exists()


def test_stopped_entry_keeps_inactive_precedence(setup):
    entry = setup[0]
    entry.update(state="hold", stopped=True)
    assert_denied(setup, "entry_inactive")
