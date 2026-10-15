"""Offline, fail-closed send gate. No adapter or environment imports.

Budget uses a dedicated regular JSONL file, locked on that file (POSIX). Its
parent must already exist and its fixed path must not be replaced or truncated.
Days and calendar months use JST. Limits and accounting are per roster entry.
Roster and caller caps are combined using the smaller limit for each key.
Settlements replace estimates; outstanding reservations from earlier days consume
today's budget. Cross-day settlements charge actual usage on settlement day.
Task identifiers are ledger-wide (including duplicate/stop checks) and hashed
before persistence. Each reservation has a unique epoch; stop(epoch) invalidates
that epoch and all earlier ones, durably.
Late replies close reservations for accounting only, once, on receipt day.
Stopped tasks require an explicit human release; the gate never releases them.
The ledger must be retained: after deletion/truncation, a new process cannot
distinguish lost accounting history from a first run. A random initial epoch
prevents an old response from settling a new reservation in a recreated ledger.
Money is calculated exactly; JSON numbers that would lose decimal precision
are refused. Integral amounts remain integers in the ledger.
seconds_per_task measures wall time since the task's first reservation for that
entry, across restarts. Returned deadlines must also be enforced by the adapter;
this offline module cannot interrupt a running request.
この変更より前のゲートの台帳は作り直す（entry_id の無い行は ledger_entry）。
失われた使用履歴をゼロと扱わず、人が未精算額・上限を確認してから移行する。
"""

import fcntl
import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit


_REQUIRED = set("id role provider model version_kind state max_data_class hosts "
                "price evidence rollback_to review_by".split())
_CLASSES = ("A", "B", "C")
_CAPS = {"usd_per_day", "usd_per_month", "calls_per_day", "tokens_per_day", "seconds_per_task"}
_GENERIC_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}|AQ\.[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,})"
)
_PRIVATE = ("/Us" + "ers/", "_" + "非公開")
_JST = timezone(timedelta(hours=9))


class GateDenied(Exception):
    """Only fixed reason codes belong here, never payloads or raw exceptions."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateDenied("duplicate_json_key")
        result[key] = value
    return result


def _json_float(raw):
    # Reject overflow, underflow and lost digits at the JSON boundary too.
    value = float(raw)
    if not math.isfinite(value) or Fraction(str(value)) != Fraction(raw):
        raise GateDenied("inexact_json_number")
    return value


def _entries(roster):
    if not isinstance(roster, dict) or not isinstance(roster.get("entries"), list):
        raise GateDenied("invalid_roster")
    seen = set()
    for entry in roster["entries"]:
        if not isinstance(entry, dict) or not _REQUIRED <= entry.keys():
            raise GateDenied("invalid_roster_entry")
        name = entry["id"]
        if not isinstance(name, str) or not name or name in seen:
            raise GateDenied("invalid_roster_id")
        seen.add(name)
    return roster["entries"]


def load_roster(path) -> dict:
    try:
        with open(path, encoding="utf-8") as stream:
            roster = json.load(stream, object_pairs_hook=_object, parse_float=_json_float)
    except (OSError, ValueError, TypeError, RecursionError):
        raise GateDenied("roster_unreadable") from None
    _entries(roster)
    return roster


def _entry(roster, entry_id):
    for entry in _entries(roster):
        if entry["id"] == entry_id:
            if entry["state"] not in ("adopted", "trial"):
                raise GateDenied("entry_inactive")
            return entry
    raise GateDenied("unknown_entry")


def _parts(parts):
    try:
        items = list(parts)
    except Exception:
        raise GateDenied("invalid_parts") from None
    for item in items:
        if (not isinstance(item, (list, tuple)) or len(item) != 2
                or not isinstance(item[0], str)):
            raise GateDenied("invalid_parts")
    return items


def classify(parts) -> str:
    items = _parts(parts)
    result = "A"
    for text, label in items:
        if (label not in _CLASSES or any(word.casefold() in text.casefold() for word in _PRIVATE)
                or _GENERIC_SECRET.search(text)):
            return "C"
        result = max(result, label)
    combined = "".join(text for text, _ in items)
    if any(word.casefold() in combined.casefold() for word in _PRIVATE) or _GENERIC_SECRET.search(combined):
        return "C"
    return result


def _host(host):
    if not isinstance(host, str) or not host or len(host) > 253 or not host.isascii():
        raise GateDenied("invalid_host")
    host = host.lower()
    if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
               for part in host.split(".")):
        raise GateDenied("invalid_host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Also refuse numeric/legacy forms which clients may interpret as IPs.
        if all(re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", p) for p in host.split(".")):
            raise GateDenied("ip_host")
        return host
    raise GateDenied("ip_host")


def check_destination(roster, entry_id, hops) -> dict:
    """Check supplied URLs only. Adapters must disable automatic redirects and
    check every newly discovered Location before sending the next request.
    """
    entry = _entry(roster, entry_id)
    if not isinstance(entry["hosts"], list) or not entry["hosts"]:
        raise GateDenied("no_hosts")
    allowed = {_host(host) for host in entry["hosts"]}
    if isinstance(hops, (str, bytes)):
        raise GateDenied("invalid_hops")
    try:
        hops = list(hops)
    except Exception:
        raise GateDenied("invalid_hops") from None
    if not hops:
        raise GateDenied("no_hops")
    for hop in hops:
        if (not isinstance(hop, str) or not hop
                or any(ord(c) <= 32 or ord(c) == 127 for c in hop) or "\\" in hop):
            raise GateDenied("invalid_url")
        try:
            url = urlsplit(hop)
            if url.scheme.lower() != "https" or not url.netloc:
                raise GateDenied("https_required")
            if ":" in url.netloc or "@" in url.netloc:
                raise GateDenied("url_authority")
            host = _host(url.netloc)
        except ValueError:
            raise GateDenied("invalid_url") from None
        if host not in allowed:
            raise GateDenied("host_not_allowed")
    return entry


def _number(value, reason="invalid_number"):
    if (type(value) not in (int, float) or value < 0
            or (isinstance(value, float) and not math.isfinite(value))):
        raise GateDenied(reason)
    try:
        return Fraction(str(value))
    except ValueError:
        raise GateDenied(reason) from None


def _integer(value, reason="invalid_count", minimum=0):
    if type(value) is not int or value < minimum:
        raise GateDenied(reason)
    return value


def _json_number(value):
    if value.denominator == 1:
        return value.numerator
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise GateDenied("amount_out_of_range") from None
    if not math.isfinite(result) or Fraction(str(result)) != value:
        raise GateDenied("amount_out_of_range")
    return result


def check_send(roster, entry_id, parts, max_chars) -> str:
    entry = _entry(roster, entry_id)
    items = _parts(parts)
    label = classify(items)
    limit = entry["max_data_class"]
    if limit not in ("A", "B") or label == "C" or label > limit:
        raise GateDenied("data_class_denied")
    _integer(max_chars, "invalid_char_limit")
    if sum(len(text) for text, _ in items) > max_chars:
        raise GateDenied("too_many_chars")
    return label


def _task(task_id):
    if not isinstance(task_id, str) or not task_id:
        raise GateDenied("invalid_task")
    try:
        return hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise GateDenied("invalid_task") from None


def _day(at):
    _number(at, "invalid_timestamp")
    try:
        return datetime.fromtimestamp(at, _JST).date()
    except (ValueError, OverflowError, OSError):
        raise GateDenied("invalid_timestamp") from None


def _caps(caps):
    if not isinstance(caps, dict) or not caps.keys() <= _CAPS:
        raise GateDenied("invalid_caps")
    return {key: _number(value, "invalid_caps") for key, value in caps.items()}


class Budget:
    def __init__(self, ledger_path, caps):
        self.caps = _caps(caps)
        try:
            self.ledger_path = Path(ledger_path)
        except (ValueError, TypeError):
            raise GateDenied("invalid_ledger_path") from None

    @contextmanager
    def _locked(self):
        descriptor = None
        try:
            descriptor = os.open(self.ledger_path, os.O_RDWR | os.O_CREAT | os.O_APPEND
                                 | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise GateDenied("ledger_not_regular")
            with os.fdopen(descriptor, "a+", encoding="utf-8") as stream:
                descriptor = None  # stream now owns the descriptor.
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    stream.seek(0)
                    yield stream
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except (OSError, UnicodeError, ValueError):
            raise GateDenied("ledger_io") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _read(self, stream):
        """Replay strictly: corruption, including old/undatable rows, blocks use."""
        reservations, settled, pending, stopped, first = {}, {}, {}, set(), {}
        cutoff = last_epoch = 0
        last_at = 0
        try:
            for line in stream:
                if not line.endswith("\n"):
                    raise GateDenied("ledger_truncated")
                row = json.loads(line, object_pairs_hook=_object, parse_float=_json_float)
                if not isinstance(row, dict):
                    raise GateDenied("ledger_row")
                kind, at, epoch = row["kind"], row["at"], row["epoch"]
                _day(at)
                _integer(epoch, "ledger_epoch")
                if at < last_at:
                    raise GateDenied("ledger_time")
                last_at = at
                if kind == "stop":
                    if (epoch < cutoff or (epoch not in reservations
                                           and not (epoch == 0 and last_epoch == 0))):
                        raise GateDenied("ledger_stop")
                    cutoff = epoch
                    continue
                task = row["task_id"]
                if not isinstance(task, str) or not re.fullmatch(r"[0-9a-f]{64}", task):
                    raise GateDenied("ledger_task")
                entry_id = row.get("entry_id")
                if not isinstance(entry_id, str) or not entry_id:
                    raise GateDenied("ledger_entry")
                if kind == "reserve":
                    if ((last_epoch and epoch != last_epoch + 1) or epoch == 0
                            or task in pending or task in stopped):
                        raise GateDenied("ledger_reservation")
                    _number(row["estimated_usd"])
                    _integer(row["reserved_tokens"])
                    _integer(row["calls"], minimum=1)
                    if row["deadline"] is not None:
                        _day(row["deadline"])
                        if row["deadline"] < at:
                            raise GateDenied("ledger_deadline")
                    reservations[epoch] = row
                    pending[task] = epoch
                    first.setdefault((entry_id, task), at)
                    last_epoch = epoch
                elif kind in ("settle", "late"):
                    reservation = reservations[epoch]
                    if reservation["task_id"] != task or reservation["entry_id"] != entry_id:
                        raise GateDenied("ledger_task")
                    _number(row["actual_usd"])
                    _integer(row["actual_tokens"])
                    if (kind == "late") != (epoch <= cutoff):
                        raise GateDenied("ledger_late")
                    if pending.get(task) != epoch:
                        raise GateDenied("ledger_settlement")
                    warning, stop = self._flags(reservation, row["actual_usd"], at)
                    if row["warning"] is not warning or row["stopped"] is not stop:
                        raise GateDenied("ledger_flags")
                    settled[epoch] = row
                    del pending[task]
                    if stop:
                        stopped.add(task)
                elif kind == "release":
                    reservation = reservations[epoch]
                    if (task not in stopped or task in pending
                            or reservation["task_id"] != task
                            or reservation["entry_id"] != entry_id
                            or not settled[epoch]["stopped"]
                            or epoch != max(e for e, s in settled.items() if s["task_id"] == task)):
                        raise GateDenied("ledger_release")
                    reason_hash = row["reason_hash"]
                    if not isinstance(reason_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", reason_hash):
                        raise GateDenied("ledger_release")
                    stopped.remove(task)
                    first.pop((entry_id, task), None)
                else:
                    raise GateDenied("ledger_kind")
        except (KeyError, ValueError, TypeError, RecursionError):
            raise GateDenied("ledger_corrupt") from None
        return reservations, settled, pending, stopped, first, cutoff, last_epoch, last_at

    @staticmethod
    def _flags(reservation, actual_usd, at):
        actual, estimate = _number(actual_usd), _number(reservation["estimated_usd"])
        # A genuinely free call (0 -> 0) is not a cost overrun.
        warning = actual > 0 and actual >= estimate * Fraction("1.5")
        stopped = actual > 0 and actual >= estimate * 2
        deadline = reservation["deadline"]
        return warning, stopped or (deadline is not None and at > deadline)

    @staticmethod
    def _append(stream, row):
        try:
            encoded = json.dumps(row, allow_nan=False, sort_keys=True) + "\n"
        except (ValueError, TypeError, OverflowError):
            raise GateDenied("ledger_encoding") from None
        stream.seek(0, os.SEEK_END)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
        return row

    def _reserve(self, entry, calls, max_in_tokens, max_out_tokens, task_id) -> dict:
        """Internal: gate() supplies the checked roster entry, including caps."""
        task = _task(task_id)
        _integer(calls, minimum=1)
        _integer(max_in_tokens)
        _integer(max_out_tokens)
        price = entry.get("price") if isinstance(entry, dict) else None
        if not isinstance(price, dict):
            raise GateDenied("unknown_price")
        price_in = _number(price.get("input"), "invalid_price")
        price_out = _number(price.get("output"), "invalid_price")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise GateDenied("invalid_roster_id")
        caps = dict(self.caps)
        for key, value in _caps(entry.get("caps", {})).items():
            caps[key] = min(caps.get(key, value), value)
        if not caps:
            raise GateDenied("missing_caps")
        estimate = _json_number(calls * (max_in_tokens * price_in + max_out_tokens * price_out)
                                / 1000000)
        tokens = calls * (max_in_tokens + max_out_tokens)
        with self._locked() as stream:
            reservations, settled, pending, stopped, first, _, epoch, last_at = self._read(stream)
            now = time.time()
            today = _day(now)
            if now < last_at:
                raise GateDenied("clock_rewound")
            if task in pending or task in stopped:
                raise GateDenied("task_unavailable")
            deadline = None
            if "seconds_per_task" in caps:
                deadline = _json_number(_number(first.get((entry_id, task), now)) + caps["seconds_per_task"])
                _day(deadline)
                if now > deadline:
                    raise GateDenied("task_timeout")
            totals = {"usd_per_day": _number(estimate), "usd_per_month": _number(estimate),
                      "calls_per_day": Fraction(calls),
                      "tokens_per_day": Fraction(tokens)}
            for old_epoch, reservation in reservations.items():
                if reservation["entry_id"] != entry_id:
                    continue
                settlement = settled.get(old_epoch)
                if settlement is None or _day(reservation["at"]) == today:
                    totals["calls_per_day"] += reservation["calls"]
                if settlement is None:
                    totals["usd_per_day"] += _number(reservation["estimated_usd"])
                    totals["usd_per_month"] += _number(reservation["estimated_usd"])
                    totals["tokens_per_day"] += reservation["reserved_tokens"]
                else:
                    settled_day = _day(settlement["at"])
                    if (settled_day.year, settled_day.month) == (today.year, today.month):
                        totals["usd_per_month"] += _number(settlement["actual_usd"])
                    if settled_day == today:
                        totals["usd_per_day"] += _number(settlement["actual_usd"])
                        totals["tokens_per_day"] += settlement["actual_tokens"]
            if any(value > caps[key] for key, value in totals.items() if key in caps):
                raise GateDenied("budget_exceeded")
            next_epoch = epoch + 1 if epoch else uuid.uuid4().int
            return self._append(stream, {"kind": "reserve", "task_id": task, "epoch": next_epoch,
                                        "entry_id": entry_id,
                                        "at": now, "deadline": deadline, "calls": calls,
                                        "estimated_usd": estimate, "reserved_tokens": tokens})

    def settle(self, task_id, actual_usd, actual_tokens, epoch):
        task = _task(task_id)
        if actual_usd is not None:
            _number(actual_usd)
        if actual_tokens is not None:
            _integer(actual_tokens)
        _integer(epoch, minimum=1)
        with self._locked() as stream:
            reservations, _, pending, _, _, cutoff, _, last_at = self._read(stream)
            now = time.time()
            _day(now)
            if now < last_at:
                raise GateDenied("clock_rewound")
            reservation = reservations.get(epoch)
            if reservation is None or reservation["task_id"] != task:
                raise GateDenied("unknown_reservation")
            if pending.get(task) != epoch:
                raise GateDenied("already_settled")
            if epoch <= cutoff:
                if actual_usd is None:
                    actual_usd = reservation["estimated_usd"]
                if actual_tokens is None:
                    actual_tokens = reservation["reserved_tokens"]
            _number(actual_usd)
            _integer(actual_tokens)
            row = {"kind": "late" if epoch <= cutoff else "settle", "task_id": task,
                   "entry_id": reservation["entry_id"],
                   "epoch": epoch, "at": now, "actual_usd": actual_usd,
                   "actual_tokens": actual_tokens}
            row["warning"], row["stopped"] = self._flags(reservation, actual_usd, now)
            return self._append(stream, row)

    def release(self, task_id, reason):
        """Human-only reset of a stopped task, including its time window.

        Persist only a digest of the supplied reason, never arbitrary text that
        could contain payloads or credentials. Historical charges are retained.
        """
        task = _task(task_id)
        if not isinstance(reason, str) or not reason.strip():
            raise GateDenied("invalid_release_reason")
        reason_hash = _task(reason)
        with self._locked() as stream:
            reservations, settled, _, stopped, _, _, _, last_at = self._read(stream)
            if task not in stopped:
                raise GateDenied("task_not_stopped")
            now = time.time()
            _day(now)
            if now < last_at:
                raise GateDenied("clock_rewound")
            epoch = max(e for e, row in settled.items() if row["task_id"] == task)
            return self._append(stream, {"kind": "release", "task_id": task, "epoch": epoch,
                                        "entry_id": reservations[epoch]["entry_id"],
                                        "at": now, "reason_hash": reason_hash})

    def stop(self, epoch=None):
        """Stop through a known epoch, or all existing reservations if omitted.
        With an empty ledger, stop() records an epoch-zero no-op.

        If no reply will arrive, a human can close an outstanding reservation:
        stop(), then settle(task, None, None, epoch). This records the reserved
        estimates as a late settlement; it does not refund unknown usage.
        If the task is stopped, release(task, reason) is a separate human step.
        """
        with self._locked() as stream:
            reservations, _, _, _, _, cutoff, latest, last_at = self._read(stream)
            if epoch is None:
                epoch = latest
            else:
                _integer(epoch, minimum=1)
                if epoch not in reservations:
                    raise GateDenied("unknown_epoch")
            now = time.time()
            _day(now)
            if now < last_at:
                raise GateDenied("clock_rewound")
            return self._append(stream, {"kind": "stop", "epoch": max(epoch, cutoff), "at": now})


def gate(roster_path, entry_id, hops, parts, max_chars, budget, calls,
         max_in_tokens, max_out_tokens, task_id, detector=None) -> dict:
    roster = load_roster(roster_path)
    entry = check_destination(roster, entry_id, hops)
    items = _parts(parts)
    check_send(roster, entry_id, items, max_chars)
    if detector is not None:
        # Check parts and their actual concatenation to catch split patterns.
        for text in [part[0] for part in items] + ["".join(part[0] for part in items)]:
            try:
                denied = detector(text)
            except Exception:
                raise GateDenied("detector_error") from None
            if denied is not False:
                raise GateDenied("detector_denied")
    if type(budget) is not Budget:
        raise GateDenied("invalid_budget")
    return budget._reserve(entry, calls, max_in_tokens, max_out_tokens, task_id)
