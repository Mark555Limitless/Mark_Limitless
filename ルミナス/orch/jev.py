"""Jev（TypeSafe AI の System One）の呼び出しと上限。分譲指示書 §5.3 の作法（原本 dup_check の作法）。

- 送り先: POST https://api.typesafe.ai/v1/systemone（Authorization: Bearer <TYPESAFE_API_KEY>）
- 本文: {"state": 文字列, "model": "jev-latest", "questions": {...}}。応答の answers.<問いID> に答え・確率・確信度
- 上限: 呼ぶ前に当日の回数（ORCH_JEV_DAILY_MAX、既定60）と当月の金額（ORCH_JEV_MONTHLY_USD、既定1.0）を台帳から数える。
  通信に失敗した呼び出しも1回に数える
- 停止スイッチ: ORCH_JEV=0 または data/.jev_disabled
- 記録: data/usage.jsonl（vendor=jev）と logs/jev.log に1行。鍵は伏せ字にする
- 注意: 速さは第三者（Vals AI）も確認、費用の差は比べる相手で変わる。英語が主で CJK は精度が下がる（公式）。wire 形式は公式の API リファレンスと一致（docs/jev-value-study.md）
"""
from __future__ import annotations

import json
import math
import threading
import uuid
import time
import warnings
from typing import Any, Dict, Optional, Tuple

# requests が無い python3（.venv が未作成・壊れている）でも、点検と判断層の既定値の経路は動かす（orch/gemini.py と同じ）。
# 呼ぶ直前に None なら JevUnavailable（判断層は次の手段へ落ちる）。試験は jev.requests を差し替えるので、モジュールの属性として持つ
warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+")  # 理由は orch/gemini.py
try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from . import config, gate, roster, usage

ROLE = "構造化判断の信号（止める側だけ）"
FALLBACK_USD_PER_QUESTION = 0.0003


class JevUnavailable(Exception):
    """呼ばなかった／呼べなかった（理由は args[0]）。判断層は次の手段に落ちる。"""


def enabled() -> bool:
    return config.env("JEV_ENABLED", "0") == "1" and bool(config.env("TYPESAFE_API_KEY"))


def limits_ok() -> Tuple[bool, str]:
    if config.disabled("jev"):
        return False, "停止中"
    if usage.today_calls("jev") >= config.env_int("ORCH_JEV_DAILY_MAX", 60):
        return False, "上限到達(回数)"
    if usage.month_usd("jev") >= config.env_float("ORCH_JEV_MONTHLY_USD", 1.0):
        return False, "上限到達(月額)"
    return True, ""


def _log(status: str, http: Any, model: str, ms: int, usd: float, purpose: str, reason: str) -> None:
    line = {
        "ts": config.ts(), "status": status, "calls": 1, "usd": round(usd, 6), "http": http,
        "model": model, "ms": ms, "purpose": purpose[:80], "reason": reason,
    }
    try:
        path = config.log_dir() / "jev.log"
        with config.file_lock(path.with_suffix(".lock")):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(config.redact(json.dumps(line, ensure_ascii=False)) + "\n")
    except OSError:
        pass
    try:
        usage.record("jev", model=model, purpose=purpose, usd=usd, status=status, ms=ms,
                     extra={"http": http, "reason": reason})
    except OSError:
        pass


def _num(x: Any) -> bool:
    return type(x) in (int, float) and 0 <= x < float("inf")


def _usd(resp_json: Any, n_questions: int, entry=None) -> float:
    u = resp_json.get("usage") if isinstance(resp_json, dict) else None
    u = u if isinstance(u, dict) else {}
    if _num(u.get("cost")):
        return float(u["cost"])
    if _num(u.get("input_tokens")):
        entry = entry or _roster()[1]
        return float(u["input_tokens"]) * entry["price"]["input"] / 1_000_000
    return FALLBACK_USD_PER_QUESTION * max(n_questions, 1)


def _log_skip(model: str, purpose: str, reason: str) -> None:
    """呼ばなかったことを記録する（回数には数えない）。"""
    line = {"ts": config.ts(), "status": "skip", "calls": 0, "usd": 0.0, "http": None, "model": model, "ms": 0,
            "purpose": purpose[:80], "reason": reason}
    try:
        path = config.log_dir() / "jev.log"
        with config.file_lock(path.with_suffix(".lock")):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(config.redact(json.dumps(line, ensure_ascii=False)) + "\n")
    except OSError:
        pass
    try:
        usage.record("jev", model=model, purpose=purpose, calls=0, usd=0.0, status="skip", ms=0, extra={"reason": reason})
    except OSError:
        pass


def _roster():
    path = config.env("ORCH_ROSTER") or config.ROOT / "config" / "roster.json"
    try:
        entry = roster.active(gate.load_roster(path), ROLE)
    except ValueError:
        raise gate.GateDenied("roster_selection") from None
    if not isinstance(entry["hosts"], list) or not entry["hosts"]:
        raise gate.GateDenied("no_hosts")
    return path, entry


def _post(url, headers, body, timeout):
    """Bound the whole response wait, including a peer that trickles bytes."""
    box = {}

    def run():
        try:
            box["response"] = requests.post(url, headers=headers, json=body,
                                             timeout=(min(5.0, timeout), timeout),
                                             allow_redirects=False)
        except BaseException as error:
            box["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError()
    if "error" in box:
        raise box["error"]
    return box["response"]


def call(state: str, questions: Dict[str, Dict[str, Any]], *, timeout_s: float = 8.0,
         purpose: str = "", data_class: Optional[str] = None) -> Dict[str, Any]:
    """Public-only callers must explicitly label data; unlabeled sends fail closed.
    Failure raises JevUnavailable; global halt still propagates as GlobalHalt.
    """
    if config.global_halt():
        _log_skip(config.env("JEV_MODEL", "") or "", purpose, "全体停止中")
        raise config.GlobalHalt()
    key = config.env("TYPESAFE_API_KEY")
    if config.env("JEV_ENABLED", "0") != "1":
        raise JevUnavailable("無効（JEV_ENABLED!=1）")
    if not key:
        raise JevUnavailable("鍵なし")
    ok, why = limits_ok()
    if not ok:
        raise JevUnavailable(why)
    if requests is None:
        raise JevUnavailable("requests 未導入")
    model = config.env("JEV_MODEL") or ""
    try:
        roster_path, entry = _roster()
        model = model or entry["model"]
        url = config.env("JEV_ENDPOINT") or f"https://{entry['hosts'][0]}/v1/systemone"
        body = {"state": state, "model": model, "questions": questions}
        # Include question instructions/options and model, not just state.
        wire = json.dumps(body, ensure_ascii=False)
        budget = gate.Budget(config.data_dir() / "gate_ledger.jsonl", {})
        task = uuid.uuid4().hex
        # Jev returns structured signals, not a generated token stream.
        reservation = gate.gate(roster_path, entry["id"], [url], [(wire, data_class)],
                                len(wire), budget, 1, len(wire.encode("utf-8")), 0, task)
    except gate.GateDenied as error:
        _log_skip(model, purpose, error.reason)
        raise JevUnavailable(error.reason) from None

    t0 = time.monotonic()
    usd, tokens = 0.0, reservation["reserved_tokens"]
    http, reason, answers = None, "通信失敗", None
    try:
        t = max(float(timeout_s), 0.1)
        if reservation["deadline"] is not None:
            t = min(t, reservation["deadline"] - time.time())
        if t <= 0 or not math.isfinite(t):
            raise TimeoutError()
        resp = _post(url, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, body, t)
        http = getattr(resp, "status_code", None)
        if http != 200:
            reason = f"HTTP {http}"
        else:
            usd = FALLBACK_USD_PER_QUESTION * max(len(questions), 1)
            reason = "解析失敗"
            data = resp.json()
            usd = _usd(data, len(questions), entry)
            md = data.get("usage") if isinstance(data, dict) else None
            if isinstance(md, dict) and type(md.get("input_tokens")) is int and md["input_tokens"] >= 0:
                tokens = md["input_tokens"]
            answers = data.get("answers") if isinstance(data, dict) else None
            reason = "ok" if isinstance(answers, dict) else "answers なし"
    except Exception:
        answers = None  # Keep only the fixed reason, never raw exception text.
    finally:
        try:
            budget.settle(task, usd, tokens, reservation["epoch"])
        except gate.GateDenied as error:
            try:
                budget.stop(reservation["epoch"])
            except gate.GateDenied:
                pass  # A corrupt/unwritable ledger blocks later reservations.
            reason, answers = error.reason, None
        _log("ok" if reason == "ok" else "error", http, model,
             int((time.monotonic() - t0) * 1000), usd, purpose, reason)
    if reason != "ok":
        raise JevUnavailable(reason)
    return answers


def status_line() -> str:
    key = "あり" if config.env("TYPESAFE_API_KEY") else "なし"
    on = "有効" if config.env("JEV_ENABLED", "0") == "1" else "無効"
    stop = "全体停止中" if config.global_halt() else ("停止中" if config.disabled("jev") else "稼働")
    missing = "（requests 未導入: bash scripts/setup.sh）" if requests is None else ""
    return (f"jev: 鍵={key} {on} {stop} 本日 {usage.today_calls('jev')}/{config.env_int('ORCH_JEV_DAILY_MAX', 60)}回 "
            f"今月 ${usage.month_usd('jev'):.4f}／上限 ${config.env_float('ORCH_JEV_MONTHLY_USD', 1.0):.2f}{missing}")
