"""In-memory plans and temporary adapter rosters; never edit the live roster."""
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from orch import roster


@pytest.fixture(autouse=True)
def adapter_roster(isolated_env, monkeypatch):
    entries = []
    for name, role, provider, model, host, price, caps in [
        ("gemini-drafter", "下書き・別の視点", "google", "gemini-test", "gemini.example.test",
         {"input": 0.75, "output": 3.75}, {"usd_per_day": 0.25}),
        ("jev-signal", "構造化判断の信号（止める側だけ）", "typesafe", "jev-latest", "jev.example.test",
         {"input": 0.042, "output": 0.0}, {"calls_per_day": 60, "usd_per_month": 1.0}),
    ]:
        entries.append(dict(id=name, role=role, provider=provider, model=model, hosts=[host],
                            price=price, caps=caps, state="trial", max_data_class="A",
                            version_kind="alias", evidence=[], rollback_to="stop", review_by="2026-11-01"))
    path = isolated_env / "roster.json"
    path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    monkeypatch.setenv("ORCH_ROSTER", str(path))
    return path


def pair():
    return {"entries": [dict(id="A", role="draft", state="adopted", model="first"),
                        dict(id="B", role="draft", state="trial", model="second")]}


def test_switch_and_rollback_route_without_writing(tmp_path):
    original = pair()
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    adapter = Mock(side_effect=lambda entry: entry["id"])
    switched = roster.plan_switch(original, "draft", "B")
    assert original == pair()
    assert switched["entries"][0]["state"] == "hold"
    assert adapter(roster.active(switched, "draft")) == "B"
    # History survives JSON serialization; no process-global hidden state.
    reverted = roster.plan_rollback(json.loads(json.dumps(switched)), "draft")
    assert adapter(roster.active(reverted, "draft")) == "A"
    assert roster.active(switched, "draft")["id"] == "B"
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["role", "state", "unknown", "same"])
def test_invalid_switch(change):
    data = pair()
    target = "B"
    if change == "role":
        data["entries"][1]["role"] = "other"
    elif change == "state":
        data["entries"][1]["state"] = "hold"
    elif change == "unknown":
        target = "unknown"
    else:
        target = "A"
    before = deepcopy(data)
    with pytest.raises(ValueError):
        roster.plan_switch(data, "draft", target)
    assert data == before


def test_missing_rollback_and_role():
    with pytest.raises(ValueError):
        roster.plan_rollback(pair(), "draft")
    with pytest.raises(ValueError):
        roster.active(pair(), "unknown")
    assert roster.active({"entries": [pair()["entries"][1]]}, "draft")["id"] == "B"


def test_multiple_switches_rollback_latest_hold():
    data = pair()
    data["entries"].append(dict(id="C", role="draft", state="trial"))
    first = roster.plan_switch(data, "draft", "B")
    second = roster.plan_switch(first, "draft", "C")
    back = roster.plan_rollback(second, "draft")
    assert roster.active(back, "draft")["id"] == "B"
    assert roster.active(roster.plan_rollback(back, "draft"), "draft")["id"] == "A"


@pytest.mark.parametrize("state", ["retired", "trial", "stopped"])
def test_rollback_requires_held_target(state):
    data = roster.plan_switch(pair(), "draft", "B")
    data["entries"][0]["state"] = state
    with pytest.raises(ValueError):
        roster.plan_rollback(data, "draft")


def test_ambiguous_active_is_refused():
    data = pair()
    data["entries"][1]["state"] = "adopted"
    with pytest.raises(ValueError, match="ambiguous"):
        roster.active(data, "draft")


def test_role_key_and_legacy_role():
    data = pair()
    data['entries'][0]['role_key'] = 'drafter'
    assert roster.active(data, 'drafter')['id'] == 'A'
    assert roster.active(data, 'draft')['id'] == 'A'


def test_candidate_order_and_stop_reasons():
    data = {'entries': [
        dict(id='trial', role='draft', state='trial'),
        dict(id='first', role='draft', state='adopted'),
        dict(id='second', role='draft', state='adopted'),
        dict(id='stop', role='draft', state='trial', stopped=True),
        dict(id='country', role='draft', state='trial', jurisdiction='CN'),
        dict(id='vendor', role='draft', state='trial', provider='xxx'),
    ], 'stops': {'jurisdictions': ['CN'], 'providers': ['xxx']}}
    candidates, skips = roster.candidates_with_skips(data, 'draft')
    assert [e['id'] for e in candidates] == ['first', 'second', 'trial']
    assert [e['why'] for e in skips] == ['stopped', 'jurisdiction_stopped', 'provider_stopped']
    assert roster.candidates(data, 'draft') == candidates


def test_switch_rollback_with_role_key():
    data = pair()
    for entry in data['entries']:
        entry['role_key'] = 'drafter'
    switched = roster.plan_switch(data, 'drafter', 'B')
    assert roster.active(switched, 'drafter')['id'] == 'B'
    assert roster.active(roster.plan_rollback(switched, 'drafter'), 'drafter')['id'] == 'A'


@pytest.mark.parametrize('module,key', [('gemini', 'drafter'), ('jev', 'signal')])
def test_japanese_roles_with_key(adapter_roster, module, key):
    from orch import gemini, jev
    role = {'gemini': gemini, 'jev': jev}[module].ROLE
    data = json.loads(adapter_roster.read_text())
    entry = next(e for e in data['entries'] if e['role'] == role)
    entry['role_key'] = key
    assert roster.active(data, role) is entry
    assert roster.active(data, key) is entry
    assert roster.candidates(data, key) == [entry]
    assert roster.candidates(data, role) == [entry]
    with pytest.raises(ValueError, match='role_unavailable'):
        roster.active(data, 'other')


@pytest.mark.parametrize('value,stopped', [
    (True, True), (False, False), (None, False),
])
def test_stopped_fails_closed(value, stopped):
    data = pair()
    data['entries'][0]['stopped'] = value
    candidates, skips = roster.candidates_with_skips(data, 'draft')
    assert [e['id'] for e in candidates] == (['B'] if stopped else ['A', 'B'])
    assert skips == ([{'id': 'A', 'why': 'stopped'}] if stopped else [])


@pytest.mark.parametrize('field,value', [
    ('jurisdiction', ['US']), ('provider', ['example']), ('stopped', 'true'),
    ('stopped', 1),
])
def test_invalid_stop_field_types_fail_closed(field, value):
    data = pair()
    data['entries'][0][field] = value
    with pytest.raises(ValueError, match='^invalid_roster$'):
        roster.stop_reason(data, data['entries'][0])
    with pytest.raises(ValueError, match='^invalid_roster$'):
        roster.candidates(data, 'draft')


@pytest.mark.parametrize('stops', [None, [], 'stop', 1,
    {'jurisdictions': 'CN'}, {'providers': 'google'},
    {'jurisdictions': None}, {'providers': {}},
    {'jurisdictions': [1]}, {'providers': ['google', None]},
])
@pytest.mark.parametrize('select', [roster.candidates_with_skips, roster.active])
def test_invalid_stops_fail_closed(stops, select):
    data = pair()
    data['stops'] = stops
    with pytest.raises(ValueError, match='^invalid_roster$'):
        select(data, 'draft')


@pytest.mark.parametrize('field,value,stop,reason', [
    ('provider', 'google', ' Google ', 'provider_stopped'),
    ('provider', ' Google ', 'google', 'provider_stopped'),
    ('jurisdiction', 'US', ' us ', 'jurisdiction_stopped'),
    ('jurisdiction', ' us ', 'US', 'jurisdiction_stopped'),
])
def test_stop_names_are_normalized(field, value, stop, reason):
    data = pair()
    data['entries'][0][field] = value
    data['stops'] = {'providers' if field == 'provider' else 'jurisdictions': [stop]}
    candidates, skipped = roster.candidates_with_skips(data, 'draft')
    assert [entry['id'] for entry in candidates] == ['B']
    assert skipped == [{'id': 'A', 'why': reason}]


@pytest.mark.parametrize("kind,reason", [("row", "stopped"),
    ("jurisdictions", "jurisdiction_stopped"), ("providers", "provider_stopped")])
def test_active_excludes_stops_and_switch_refuses_them(kind, reason):
    data = pair()
    first, second = data["entries"]
    first.update(jurisdiction="US", provider="google")
    if kind == "row":
        first["stopped"] = True
    else:
        data["stops"] = {kind: ["us" if kind == "jurisdictions" else "google"]}
    assert roster.stop_reason(data, first) == reason
    assert roster.stop_reason(data, second) is None
    assert roster.active(data, "draft") is second
    second["state"] = "adopted"
    assert roster.active(data, "draft") is second  # Filter before ambiguity checks.
    second["state"] = "trial"
    second["stopped"] = True
    with pytest.raises(ValueError, match="^role_unavailable$"):
        roster.active(data, "draft")
    with pytest.raises(ValueError, match="^invalid_switch$"):
        roster.plan_switch(data, "draft", "B")
    first["state"], second["state"] = "trial", "adopted"
    second["stopped"] = False
    before = deepcopy(data)
    with pytest.raises(ValueError, match="^invalid_switch$"):
        roster.plan_switch(data, "draft", "A")
    assert data == before


def test_switch_uses_stopped_current_and_rollback_uses_stopped_current():
    data = pair()
    data['entries'][0]['stopped'] = True
    switched = roster.plan_switch(data, 'draft', 'B')
    assert switched['entries'][1]['state'] == 'adopted'

    data = pair()
    switched = roster.plan_switch(data, 'draft', 'B')
    switched['entries'][1]['stopped'] = True
    reverted = roster.plan_rollback(switched, 'draft')
    assert reverted['entries'][0]['state'] == 'adopted'


def test_rollback_rejects_stopped_previous():
    data = pair()
    switched = roster.plan_switch(data, 'draft', 'B')
    switched['entries'][0]['stopped'] = True
    with pytest.raises(ValueError, match='^rollback_unavailable$'):
        roster.plan_rollback(switched, 'draft')


def test_stop_reason_priority():
    data = pair()
    first = data["entries"][0]
    first.update(stopped=True, jurisdiction="US", provider="google")
    data["stops"] = {"jurisdictions": ["us"], "providers": ["google"]}
    assert roster.stop_reason(data, first) == "stopped"
    first["stopped"] = False
    assert roster.stop_reason(data, first) == "jurisdiction_stopped"
    data["stops"]["jurisdictions"] = []
    assert roster.stop_reason(data, first) == "provider_stopped"
