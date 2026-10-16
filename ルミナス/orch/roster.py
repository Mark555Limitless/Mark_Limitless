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


def _matches_role(entry, role) -> bool:
    """role_key（機械用の英小文字のキー）があればそれで、無ければ従来の日本語の role で照合する（後方互換）。"""
    key = entry.get("role_key")
    if isinstance(key, str) and key:
        return key == role
    return entry["role"] == role


def _stops(roster) -> dict:
    stops = roster.get("stops") if isinstance(roster, dict) else None
    stops = stops if isinstance(stops, dict) else {}
    return {
        "jurisdictions": {str(x).upper() for x in stops.get("jurisdictions", []) if isinstance(x, str)},
        "providers": {str(x) for x in stops.get("providers", []) if isinstance(x, str)},
    }


def candidates_with_skips(roster, role):
    """役割に合う行を adopted → trial → 名簿の順で返す。停止中の行（stopped・法域・提供元の一括停止）は除いて理由を返す。"""
    stops = _stops(roster)
    cands, skipped = [], []
    for state in ("adopted", "trial"):
        for entry in _entries(roster):
            if not _matches_role(entry, role) or entry.get("state") != state:
                continue
            if entry.get("stopped") is True:
                skipped.append({"id": entry["id"], "why": "stopped"})
            elif str(entry.get("jurisdiction", "")).upper() in stops["jurisdictions"]:
                skipped.append({"id": entry["id"], "why": "jurisdiction_stopped"})
            elif str(entry.get("provider", "")) in stops["providers"]:
                skipped.append({"id": entry["id"], "why": "provider_stopped"})
            else:
                cands.append(entry)
    return cands, skipped


def candidates(roster, role) -> list:
    return candidates_with_skips(roster, role)[0]


def active(roster, role) -> dict:
    """Select adopted before trial; refuse absent or ambiguous assignments."""
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
    old = active(plan, role)
    new = next((entry for entry in _entries(plan) if entry["id"] == new_id), None)
    if (new is None or new is old or not _matches_role(new, role)
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
            or not _matches_role(previous, role) or previous.get("state") != "hold"
            or current.get("state") != "adopted"):
        raise ValueError("rollback_unavailable")
    current["state"], previous["state"] = "trial", "adopted"
    del history[index]
    return plan
