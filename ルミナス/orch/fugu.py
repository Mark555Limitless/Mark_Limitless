"""Mark の指示による実測専用の Fugu アダプター。
Fugu に自身の構成・振り分け方を尋ねる用途に使わない（規約）。
"""
from __future__ import annotations

import argparse
import json
import math
import uuid
import sys
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# requests が無い python3（.venv が未作成・壊れている）でも、点検（orch.health）と判断層の既定値の経路は動かす。
# 呼ぶ直前に None なら「requests 未導入」として呼ばずに返す。試験は fugu.requests を差し替えるので、モジュールの属性として持つ
# Mac の Apple 製 python3（3.9）は LibreSSL と結び付いていて、urllib3 v2 が import のたびに NotOpenSSLWarning を出す。
# 表示だけの警告（TLS 1.2 で通信でき、証明書の検証も変わらない）なので、この文面だけを伏せる。ほかの警告は伏せない
warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+")
try:
    import requests
    from requests.exceptions import Timeout as RequestsTimeout
except ImportError:
    requests = None  # type: ignore[assignment]
    RequestsTimeout = TimeoutError

from . import config, gate, usage

ROLE = "外部オーケストレーターの実測"
UNKNOWN_USAGE_USD = 0.05  # 使用量が分からない応答・通信例外は控えめにこの額を計上する
REQUESTS_MISSING = "requests 未導入"  # 呼ばなかった（回数・費用に数えない）


@dataclass
class Result:
    rc: int
    reason: str
    text: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    sec: float = 0.0
    usd: float = 0.0


def _roster(entry_id="sakana-fugu-max"):
    path = config.env("ORCH_ROSTER") or config.ROOT / "config" / "roster.json"
    data = gate.load_roster(path)
    entry = next((e for e in data["entries"] if e["id"] == entry_id), None)
    if entry is None or entry.get("provider") != "sakana" or entry.get("state") not in ("adopted", "trial"):
        raise gate.GateDenied("roster_selection")
    if not isinstance(entry["hosts"], list) or not entry["hosts"]:
        raise gate.GateDenied("no_hosts")
    return path, entry


def _url(entry, resource):
    return f"https://{entry['hosts'][0]}/v1/{resource}"


def _int(value):
    return value if type(value) is int and value >= 0 else 0


def _counts(md):
    prompt, completion = md.get("prompt_tokens"), md.get("completion_tokens")
    if any(type(v) is not int or v < 0 for v in (prompt, completion)):
        raise ValueError("invalid_usage")
    # reasoning_tokens は completion_tokens の内数。調整用トークンだけ加算する。
    details = md.get("token_details", {})
    if not isinstance(details, dict):
        raise ValueError("invalid_usage")
    adjustment = 0
    for name, value in details.items():
        if name not in ("adjustment_tokens", "adjusted_tokens", "orchestration_tokens"):
            raise ValueError("unknown_token_details")
        if type(value) is not int or value < 0:
            raise ValueError("invalid_usage")
        adjustment += value
    return prompt, completion + adjustment


def cost_from_usage(md, entry=None):
    entry = entry or _roster()[1]
    tin, tout = _counts(md)
    return (tin * entry["price"]["input"] + tout * entry["price"]["output"]) / 1_000_000


def daily_usd() -> float:
    return usage.today_usd("fugu")


def daily_cap() -> float:
    cap = config.env_float("ORCH_FUGU_DAILY_USD_CAP", 0.25)
    return cap if math.isfinite(cap) and cap >= 0 else 0.0


def _post_with_timeout(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> requests.Response:
    """応答全体の待ち時間を別スレッドで打ち切る（requests の read timeout だけでは長引くことがあるため）。"""
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["resp"] = requests.post(url, headers=headers, json=body, timeout=(min(10, timeout), timeout), allow_redirects=False)
        except BaseException as e:  # 中断も呼び出し元へ戻して予約を閉じる
            box["err"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError("fugu request timed out")
    if "err" in box:
        raise box["err"]
    return box["resp"]


def _log(model: str, res: Result, sec: float, usd: float, purpose: str, *, skipped: bool = False) -> None:
    """1回1行。本文・生のエラー・鍵は書かない。記録の失敗で本流を止めない。"""
    md = res.usage if isinstance(res.usage, dict) else {}
    tin = _int(md.get("prompt_tokens"))
    tout = _int(md.get("completion_tokens"))
    try:
        tin, tout = _counts(md)
    except ValueError:
        pass
    try:
        line = (
            f"{config.ts()}\tmodel={model}\trc={res.rc}\tsec={sec:.1f}\tchars={len(res.text)}"
            f"\tin={tin}\tout={tout}\tusd={usd:.6f}\treason={res.reason}"
        )
        path = config.log_dir() / "fugu.log"
        with config.file_lock(path.with_suffix(".lock")):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(config.redact(line) + "\n")
    except Exception:
        pass
    status = "ok" if res.rc == 0 else ("skip" if skipped or res.reason in ("停止中", "上限到達", "鍵なし", "全体停止中", REQUESTS_MISSING) else "error")
    try:
        usage.record("fugu", model=model, purpose=purpose, calls=0 if status == "skip" else 1,
                     in_tokens=tin, out_tokens=tout, usd=usd, status=status, ms=int(sec * 1000),
                     extra={"rc": res.rc, "sec": sec, "chars": len(res.text), "reason": res.reason})
    except Exception:
        pass


def _parse(data, entry=None):
    if not isinstance(data, dict):
        return Result(3, "解析失敗"), UNKNOWN_USAGE_USD
    md = data.get("usage")
    md = md if isinstance(md, dict) else {}
    try:
        usd = cost_from_usage(md, entry)
    except (ValueError, TypeError, KeyError):
        usd = UNKNOWN_USAGE_USD
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return Result(3, "空応答", usage=md), usd
    choice = choices[0]
    if not isinstance(choice, dict):
        return Result(3, "解析失敗", usage=md), usd
    if choice.get("finish_reason") == "content_filter":
        return Result(3, "安全フィルタ", usage=md), usd
    message = choice.get("message")
    if not isinstance(message, dict):
        return Result(3, "解析失敗", usage=md), usd
    text = message.get("content")
    if text is None or isinstance(text, str) and not text.strip():
        return Result(3, "空応答", usage=md), usd
    if not isinstance(text, str):
        return Result(3, "解析失敗", usage=md), usd
    return Result(0, "ok", text=text, usage=md), usd


def generate(prompt: str, *, entry_id: str = "sakana-fugu-max",
             model: Optional[str] = None, max_output_tokens: int = 2048,
             timeout: float = 180, purpose: str = "",
             data_class: Optional[str] = None) -> Result:
    m = model or ""
    t0 = time.monotonic()

    def finish(res, usd=0.0, *, skipped=False):
        res.sec, res.usd = time.monotonic() - t0, usd
        _log(m, res, res.sec, usd, purpose, skipped=skipped)
        return res

    if config.global_halt():
        finish(Result(config.HALT_EXIT_CODE, "全体停止中"))
        raise config.GlobalHalt()
    if config.disabled("fugu"):
        return finish(Result(2, "停止中"))
    key = config.env("SAKANA_API_KEY")
    if not key:
        return finish(Result(2, "鍵なし"))
    try:
        roster_path, entry = _roster(entry_id)
        if model is not None and model != entry["model"]:
            raise gate.GateDenied("model_mismatch")
        m = entry["model"]
        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise gate.GateDenied("invalid_output_tokens")
        price = entry["price"]
        if (not isinstance(price, dict) or any(
                type(price.get(k)) not in (int, float) or
                not math.isfinite(price[k]) or price[k] < 0 for k in ("input", "output"))):
            raise gate.GateDenied("invalid_price")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise gate.GateDenied("invalid_timeout")
        estimate = (len(prompt.encode("utf-8")) * price["input"] +
                    max_output_tokens * price["output"]) / 1_000_000 + 0.007 * 3
        if daily_usd() + estimate > daily_cap():
            return finish(Result(2, "上限到達"))
        if requests is None:
            return finish(Result(2, REQUESTS_MISSING))
        url = _url(entry, "chat/completions")
        budget = gate.Budget(config.data_dir() / "gate_ledger.jsonl", {})
        body = {"model": m, "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": max_output_tokens}
        wire = json.dumps(body, ensure_ascii=False)
        task = uuid.uuid4().hex
        if config.global_halt():
            finish(Result(config.HALT_EXIT_CODE, "全体停止中"))
            raise config.GlobalHalt()
        reservation = gate.gate(roster_path, entry["id"], [url], [(wire, data_class)],
                                len(wire), budget, 1, len(wire.encode("utf-8")),
                                max_output_tokens, task)
    except gate.GateDenied as error:
        return finish(Result(2, error.reason), skipped=True)
    usd, tokens = UNKNOWN_USAGE_USD, reservation["reserved_tokens"]
    res = Result(2, "通信失敗")
    try:
        wait = float(timeout)
        if reservation["deadline"] is not None:
            wait = min(wait, reservation["deadline"] - time.time())
        if wait <= 0:
            raise TimeoutError()
        resp = _post_with_timeout(url, {"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"}, body, wait)
        res, usd = _response(resp, entry)
        try:
            tokens = sum(_counts(res.usage))
        except ValueError:
            if usd == 0:
                tokens = 0
    except (TimeoutError, RequestsTimeout):
        res = Result(2, "タイムアウト")
    except Exception:
        res = Result(2, "通信失敗")
    finally:
        try:
            budget.settle(task, usd, tokens, reservation["epoch"])
        except gate.GateDenied as error:
            try:
                budget.stop(reservation["epoch"])
            except gate.GateDenied:
                pass
            res = Result(2, error.reason)
    return finish(res, usd)


def _response(resp, entry) -> Tuple[Result, float]:
    code = getattr(resp, "status_code", 0)
    if code in (401, 403):
        return Result(2, "未認証"), 0.0
    if code == 429:
        return Result(2, "上限到達(429)"), 0.0
    if code >= 500:
        return Result(2, "API障害"), UNKNOWN_USAGE_USD
    if code != 200:
        return Result(2, f"API障害(HTTP {code})"), 0.0
    try:
        return _parse(resp.json(), entry)
    except Exception:
        return Result(3, "解析失敗"), UNKNOWN_USAGE_USD


def check_status(*, net: bool = True, net_timeout: float = 20) -> Tuple[bool, str]:
    """鍵の有無・短い疎通確認（本文は送らない）・当日の支出と上限を1行で返す。"""
    if config.global_halt():   # 名簿が壊れていても全体停止を先に表示する
        return False, "fugu: 全体停止中"
    try:
        roster_path, entry = _roster()
        m = entry["model"]
    except gate.GateDenied as error:
        return False, f"fugu: {error.reason}"
    spend = f"entry={entry['id']} 本日 ${daily_usd():.2f}／上限 ${daily_cap():.2f}"
    if config.global_halt():
        return False, f"fugu: 全体停止中 model={m} {spend}"
    if config.disabled("fugu"):
        return False, f"fugu: 停止中 model={m} {spend}"
    key = config.env("SAKANA_API_KEY")
    if not key:
        return False, f"fugu: 鍵なし model={m} {spend}"
    if requests is None:
        return False, f"fugu: {REQUESTS_MISSING}（bash scripts/setup.sh） model={m} {spend}"
    if not net:
        return True, f"fugu: 鍵あり（疎通は未確認） model={m} {spend}"
    t0 = time.monotonic()
    task = uuid.uuid4().hex
    budget = gate.Budget(config.data_dir() / "gate_ledger.jsonl", {})
    url = _url(entry, "models")
    try:
        reservation = gate.gate(roster_path, entry["id"], [url], [(m, "A")], len(m),
                                budget, 1, 0, 0, task)
    except gate.GateDenied as error:
        _log(m, Result(2, error.reason), 0, 0, "check", skipped=True)
        return False, f"fugu: {error.reason}"
    try:
        wait = net_timeout
        if reservation["deadline"] is not None:
            wait = min(wait, reservation["deadline"] - time.time())
        if wait <= 0:
            raise TimeoutError()
        r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=wait, allow_redirects=False)
        auth = {200: "OK", 401: "未認証", 403: "未認証", 404: "モデル名なし"}.get(r.status_code, f"HTTP {r.status_code}")
    except Exception:
        auth = "不通"
    finally:
        try:
            budget.settle(task, 0, 0, reservation["epoch"])
        except gate.GateDenied as error:
            try:
                budget.stop(reservation["epoch"])
            except gate.GateDenied:
                pass
            auth = error.reason
    _log(m, Result(0 if auth == "OK" else 2, auth), time.monotonic() - t0, 0, "check")
    return auth == "OK", f"fugu: 認証={auth} model={m} {spend}"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="orch.fugu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--quiet", action="store_true")
    c.add_argument("--no-net", action="store_true")
    g = sub.add_parser("gen")
    g.add_argument("--purpose", default="")
    g.add_argument("--model", default=None)
    g.add_argument("--entry", default="sakana-fugu-max", help="名簿の行の id（その行のモデル・単価・上限で呼ぶ）")
    g.add_argument("--data-class", choices=("A", "B", "C"), default=None)
    g.add_argument("--max-output", type=int, default=2048)
    g.add_argument("--timeout", type=float, default=180)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        ok, line = check_status(net=not a.no_net, net_timeout=20)
        print(line)
        if config.global_halt():
            return config.HALT_EXIT_CODE
        return 0 if ok or a.quiet else 2
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("fugu: 標準入力にプロンプトがありません", file=sys.stderr)
        return 2
    try:
        res = generate(prompt, model=a.model, max_output_tokens=a.max_output,
                       timeout=a.timeout, purpose=a.purpose, data_class=a.data_class, entry_id=a.entry)
    except config.GlobalHalt as e:
        print(f"fugu: {e}", file=sys.stderr)
        return config.HALT_EXIT_CODE
    if res.rc == 0:
        sys.stdout.write(res.text)
        print(f"fugu: sec={res.sec:.3f} usd={res.usd:.6f}", file=sys.stderr)
    else:
        print(f"fugu: rc={res.rc} {res.reason}", file=sys.stderr)
    return res.rc


if __name__ == "__main__":
    sys.exit(main())
