"""Pure roster plans. A human reviews and applies the returned dictionary.

switch_history records only the IDs needed to undo switches, per role. It is
part of the proposed roster, so rollback also works after saving and reloading.
No files are read or written here; rollback_to's human prose is left intact.
"""

from copy import deepcopy
from typing import Optional


def _entries(roster):
    if not isinstance(roster, dict) or not isinstance(roster.get("entries"), list):
        raise ValueError("invalid_roster")
    entries = roster["entries"]
    ids = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                or not entry["id"] or entry["id"] in ids
                or not isinstance(entry.get("role"), str)):
            raise ValueError("invalid_roster_entry")
        ids.add(entry["id"])
    return entries


def _matches_role(entry, role) -> bool:
    """role_key と従来の日本語の role のどちらでも照合する。"""
    key = entry.get("role_key")
    if isinstance(key, str) and key:
        return key == role or entry["role"] == role
    return entry["role"] == role


def _stops(roster) -> dict:
    if not isinstance(roster, dict):
        raise ValueError("invalid_roster")
    stops = roster.get("stops", {})
    if not isinstance(stops, dict):
        raise ValueError("invalid_roster")
    result = {}
    for name in ("jurisdictions", "providers"):
        values = stops.get(name, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError("invalid_roster")
        result[name] = {x.strip().casefold() for x in values}
    return result


def stop_reason(roster, entry) -> Optional[str]:
    """Return the first stop reason, validating all bulk stops fail-closed."""
    stops = _stops(roster)
    if not isinstance(entry, dict):
        raise ValueError("invalid_roster")
    for field in ("jurisdiction", "provider"):
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError("invalid_roster")
    stopped = entry.get("stopped")
    if stopped is not None and type(stopped) is not bool:
        raise ValueError("invalid_roster")
    if stopped is True:
        return "stopped"
    if (entry.get("jurisdiction") or "").strip().casefold() in stops["jurisdictions"]:
        return "jurisdiction_stopped"
    if (entry.get("provider") or "").strip().casefold() in stops["providers"]:
        return "provider_stopped"
    return None


def candidates_with_skips(roster, role):
    """役割に合う行を adopted → trial → 名簿の順で返す。停止中の行（stopped・法域・提供元の一括停止）は除いて理由を返す。"""
    _stops(roster)
    cands, skipped = [], []
    for state in ("adopted", "trial"):
        for entry in _entries(roster):
            if not _matches_role(entry, role) or entry.get("state") != state:
                continue
            reason = stop_reason(roster, entry)
            if reason is not None:
                skipped.append({"id": entry["id"], "why": reason})
            else:
                cands.append(entry)
    return cands, skipped


def candidates(roster, role) -> list:
    return candidates_with_skips(roster, role)[0]


def active(roster, role) -> dict:
    """Select adopted before trial; refuse absent or ambiguous assignments."""
    entries = candidates(roster, role)
    for state in ("adopted", "trial"):
        matches = [entry for entry in entries if entry.get("state") == state]
        if len(matches) > 1:
            raise ValueError("ambiguous_role")
        if matches:
            return matches[0]
    raise ValueError("role_unavailable")


def _current(roster, role) -> dict:
    """Select the adopted/trial row without applying stop controls."""
    entries = [entry for entry in _entries(roster) if _matches_role(entry, role)]
    for state in ("adopted", "trial"):
        matches = [entry for entry in entries if entry.get("state") == state]
        if len(matches) > 1:
            raise ValueError("ambiguous_role")
        if matches:
            return matches[0]
    raise ValueError("role_unavailable")


def plan_switch(roster, role, new_id) -> dict:
    plan = deepcopy(roster)
    new = next((entry for entry in _entries(plan) if entry["id"] == new_id), None)
    if (new is None or not _matches_role(new, role)
            or new.get("state") != "trial" or stop_reason(plan, new) is not None):
        raise ValueError("invalid_switch")
    old = _current(plan, role)
    if new is old:
        raise ValueError("invalid_switch")
    history = plan.setdefault("switch_history", [])
    if not isinstance(history, list):
        raise ValueError("invalid_switch_history")
    history.append({"role": role, "from": old["id"], "to": new_id})
    old["state"], new["state"] = "hold", "adopted"
    return plan


def plan_rollback(roster, role) -> dict:
    plan = deepcopy(roster)
    current = _current(plan, role)
    history = plan.get("switch_history", [])
    if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
        raise ValueError("invalid_switch_history")
    index = next((i for i in range(len(history) - 1, -1, -1)
                  if history[i].get("role") == role), None)
    if index is None:
        raise ValueError("rollback_unavailable")
    last = history[index]
    previous = next((entry for entry in _entries(plan) if entry["id"] == last.get("from")), None)
    if (last.get("to") != current["id"] or previous is None
            or not _matches_role(previous, role) or previous.get("state") != "hold"
            or current.get("state") != "adopted"
            or stop_reason(plan, previous) is not None):
        raise ValueError("rollback_unavailable")
    current["state"], previous["state"] = "trial", "adopted"
    del history[index]
    return plan
