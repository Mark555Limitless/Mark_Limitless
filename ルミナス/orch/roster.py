"""Pure roster plans. A human reviews and applies the returned dictionary.

switch_history records only the IDs needed to undo switches, per role. It is
part of the proposed roster, so rollback also works after saving and reloading.
No files are read or written here; rollback_to's human prose is left intact.
"""

from copy import deepcopy


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


def active(roster, role) -> dict:
    """Select adopted before trial; refuse absent or ambiguous assignments."""
    entries = [entry for entry in _entries(roster) if entry["role"] == role]
    for state in ("adopted", "trial"):
        matches = [entry for entry in entries if entry.get("state") == state]
        if len(matches) > 1:
            raise ValueError("ambiguous_role")
        if matches:
            return matches[0]
    raise ValueError("role_unavailable")


def plan_switch(roster, role, new_id) -> dict:
    plan = deepcopy(roster)
    old = active(plan, role)
    new = next((entry for entry in _entries(plan) if entry["id"] == new_id), None)
    if (new is None or new is old or new["role"] != role
            or new.get("state") != "trial"):
        raise ValueError("invalid_switch")
    history = plan.setdefault("switch_history", [])
    if not isinstance(history, list):
        raise ValueError("invalid_switch_history")
    history.append({"role": role, "from": old["id"], "to": new_id})
    old["state"], new["state"] = "hold", "adopted"
    return plan


def plan_rollback(roster, role) -> dict:
    plan = deepcopy(roster)
    current = active(plan, role)
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
            or previous["role"] != role or previous.get("state") != "hold"
            or current.get("state") != "adopted"):
        raise ValueError("rollback_unavailable")
    current["state"], previous["state"] = "trial", "adopted"
    del history[index]
    return plan
