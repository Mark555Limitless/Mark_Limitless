"""全ベンダー共通の費用台帳（data/usage.jsonl）。1回の呼び出しにつき1行。本文・鍵・生のエラーは書かない。

集計: python3 -m orch.usage --days 7
記録（シェルから）: python3 -m orch.usage record --vendor codex --model gpt-6-astra --purpose spec名 --status ok --ms 1234
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from . import config

VENDORS = ("gemini", "jev", "codex", "anthropic")
STATUSES = ("ok", "warn", "skip", "error")


def ledger_path() -> Path:
    return config.data_dir() / "usage.jsonl"


def record(
    vendor: str,
    *,
    model: str = "",
    purpose: str = "",
    calls: int = 1,
    in_tokens: int = 0,
    out_tokens: int = 0,
    usd: float = 0.0,
    status: str = "ok",
    ms: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if vendor not in VENDORS:
        raise ValueError(f"unknown vendor: {vendor}")
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    row: Dict[str, Any] = {
        "ts": config.ts(),
        "vendor": vendor,
        "model": config.redact(model or ""),
        "purpose": config.redact(purpose or "")[:120],
        "calls": int(calls),
        "in_tokens": int(in_tokens or 0),
        "out_tokens": int(out_tokens or 0),
        "usd": round(float(usd or 0.0), 6),
        "status": status,
        "ms": int(ms or 0),
    }
    if extra:
        for k, v in extra.items():
            row[k] = config.redact(v) if isinstance(v, str) else v
    path = ledger_path()
    with config.file_lock(path.with_suffix(".lock")):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def iter_rows() -> Iterator[Dict[str, Any]]:
    path = ledger_path()
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and "ts" in row:
                yield row


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.JST)
    return dt.astimezone(config.JST)


def _sum(vendor: str, since: datetime, field: str) -> float:
    total = 0.0
    for row in iter_rows():
        if row.get("vendor") != vendor:
            continue
        dt = _parse_ts(row.get("ts", ""))
        if dt is None or dt < since:
            continue
        total += _amount(row.get(field))
    return total


def _amount(v: Any) -> float:
    """台帳の数値。数値でない・負・無限大・NaN は 0 として扱う（壊れた行や細工した行で合計を減らさせない）。"""
    if isinstance(v, bool):
        return 0.0
    if not isinstance(v, (int, float)):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.0
    v = float(v)
    if not math.isfinite(v) or v < 0:
        return 0.0
    return v


def _start_of_today() -> datetime:
    n = config.now_jst()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def today_usd(vendor: str) -> float:
    return _sum(vendor, _start_of_today(), "usd")


def today_calls(vendor: str) -> int:
    return int(_sum(vendor, _start_of_today(), "calls"))


def month_usd(vendor: str) -> float:
    start = _start_of_today().replace(day=1)
    return _sum(vendor, start, "usd")


def summarize(days: int = 7) -> Dict[str, Dict[str, Dict[str, float]]]:
    """{日付: {ベンダー: {calls, usd, ms}}}（日本時間）"""
    since = _start_of_today() - timedelta(days=max(days, 1) - 1)
    out: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"calls": 0, "usd": 0.0, "ms": 0}))
    for row in iter_rows():
        dt = _parse_ts(row.get("ts", ""))
        if dt is None or dt < since:
            continue
        cell = out[dt.date().isoformat()][row.get("vendor", "?")]
        cell["calls"] += int(_amount(row.get("calls")))
        cell["usd"] += _amount(row.get("usd"))
        cell["ms"] += int(_amount(row.get("ms")))
    return {d: dict(v) for d, v in sorted(out.items())}


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "record":
        ap = argparse.ArgumentParser(prog="orch.usage record")
        ap.add_argument("--vendor", required=True, choices=VENDORS)
        ap.add_argument("--model", default="")
        ap.add_argument("--purpose", default="")
        ap.add_argument("--status", default="ok", choices=STATUSES)
        ap.add_argument("--ms", type=int, default=0)
        ap.add_argument("--usd", type=float, default=0.0)
        a = ap.parse_args(argv[1:])
        record(a.vendor, model=a.model, purpose=a.purpose, status=a.status, ms=a.ms, usd=a.usd)
        return 0
    ap = argparse.ArgumentParser(prog="orch.usage")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    summary = summarize(a.days)
    if not summary:
        print(f"usage: 直近 {a.days} 日の記録はありません")
        return 0
    print("日付\tベンダー\t回数\tUSD\t秒")
    for day, vendors in summary.items():
        for vendor, c in sorted(vendors.items()):
            print(f"{day}\t{vendor}\t{int(c['calls'])}\t{c['usd']:.4f}\t{c['ms'] / 1000:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
