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
    (True, True), ('true', True), (1, True), ('yes', True),
    (0, True), ('false', True), ('', True), ([], True),
    (False, False), (None, False),
])
def test_stopped_fails_closed(value, stopped):
    data = pair()
    data['entries'][0]['stopped'] = value
    candidates, skips = roster.candidates_with_skips(data, 'draft')
    assert [e['id'] for e in candidates] == (['B'] if stopped else ['A', 'B'])
    assert skips == ([{'id': 'A', 'why': 'stopped'}] if stopped else [])
