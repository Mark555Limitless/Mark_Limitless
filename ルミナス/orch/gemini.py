"""Gemini API クライアント（下書き・要約・別の視点）。分譲指示書 §5.2 の仕様。

固定コマンド:
  python3 -m orch.gemini check [--quiet] [--no-net]   鍵の有無・疎通・当日の支出と上限を1行で出す
  python3 -m orch.gemini gen [--purpose 用途] < prompt.txt   生成して本文を標準出力へ（終了コード = rc）

rc: 0=成功 / 2=基盤の失敗（タイムアウト・未認証・上限到達・API 障害・停止中・鍵なし。呼び出し元は Claude に戻す）
    3=中身の失敗（安全フィルタ・解析失敗・空応答。書き直すか Claude に戻す）
記録: logs/gemini.log と data/usage.jsonl に1回1行。本文・生のエラー・鍵は書かない。
禁止: Antigravity（agy）を Claude Code から呼ばない（Google の規約違反）。この API クライアントだけを使う。
"""
from __future__ import annotations

import argparse
import json
import uuid
import sys
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# requests が無い python3（.venv が未作成・壊れている）でも、点検（orch.health）と判断層の既定値の経路は動かす。
# 呼ぶ直前に None なら「requests 未導入」として呼ばずに返す。試験は gemini.requests を差し替えるので、モジュールの属性として持つ
# Mac の Apple 製 python3（3.9）は LibreSSL と結び付いていて、urllib3 v2 が import のたびに NotOpenSSLWarning を出す。
# 表示だけの警告（TLS 1.2 で通信でき、証明書の検証も変わらない）なので、この文面だけを伏せる。ほかの警告は伏せない
warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+")
try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from . import config, gate, roster, usage

ROLE = "下書き・別の視点"
UNKNOWN_USAGE_USD = 0.05  # 使用量が分からない応答・通信例外は控えめにこの額を計上する
REQUESTS_MISSING = "requests 未導入"  # 呼ばなかった（回数・費用に数えない）


@dataclass
class Result:
    rc: int
    reason: str
    text: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


def _roster():
    path = config.env("ORCH_ROSTER") or config.ROOT / "config" / "roster.json"
    try:
        entry = roster.active(gate.load_roster(path), ROLE)
    except ValueError:
        raise gate.GateDenied("roster_selection") from None
    if not isinstance(entry["hosts"], list) or not entry["hosts"]:
        raise gate.GateDenied("no_hosts")
    return path, entry


def _model(model: Optional[str], entry=None) -> str:
    return model or config.env("ORCH_GEMINI_MODEL") or (entry or _roster()[1])["model"]


def _prices(entry=None) -> Tuple[float, float]:
    price = (entry or _roster()[1])["price"]
    return price["input"], price["output"]


def _int(x: Any) -> int:
    if isinstance(x, bool):
        return 0
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def cost_from_usage(md: Dict[str, Any], entry=None) -> float:
    p_in, p_out = _prices(entry)
    prompt = _int(md.get("promptTokenCount"))
    out = _int(md.get("candidatesTokenCount")) + _int(md.get("thoughtsTokenCount"))
    return (prompt * p_in + out * p_out) / 1_000_000


def daily_usd() -> float:
    return usage.today_usd("gemini")


def daily_cap() -> float:
    return config.env_float("ORCH_GEMINI_DAILY_USD_CAP", 0.25)  # 1 日 $0.25 目安（Mark の決定 2026-10-11）


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
        raise TimeoutError("gemini request timed out")
    if "err" in box:
        raise box["err"]
    return box["resp"]


def _thinking_rejected(resp: requests.Response) -> bool:
    if resp.status_code != 400:
        return False
    try:
        return "thinking" in resp.text.lower()
    except Exception:  # noqa: BLE001
        return False


def _log(model: str, res: Result, sec: float, usd: float, purpose: str, *, skipped: bool = False) -> None:
    """1回1行。本文・生のエラー・鍵は書かない。記録の失敗で本流を止めない。"""
    md = res.usage if isinstance(res.usage, dict) else {}
    tin = _int(md.get("promptTokenCount"))
    tout = _int(md.get("candidatesTokenCount"))
    think = _int(md.get("thoughtsTokenCount"))
    try:
        line = (
            f"{config.ts()}\tmodel={model}\trc={res.rc}\tsec={sec:.1f}\tchars={len(res.text)}"
            f"\tin={tin}\tout={tout}\tthink={think}\tusd={usd:.6f}\treason={res.reason}"
        )
        path = config.log_dir() / "gemini.log"
        with config.file_lock(path.with_suffix(".lock")):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(config.redact(line) + "\n")
    except OSError:
        pass
    status = "ok" if res.rc == 0 else ("skip" if skipped or res.reason in ("停止中", "上限到達", "鍵なし", "全体停止中", REQUESTS_MISSING) else "error")
    try:
        usage.record("gemini", model=model, purpose=purpose, calls=0 if status == "skip" else 1,
                     in_tokens=tin, out_tokens=tout + think, usd=usd, status=status, ms=int(sec * 1000))
    except OSError:
        pass


def _parse(data: Any, entry=None) -> Tuple[Result, float]:
    """応答を解析する。形が崩れていても例外を出さず rc=3 にする。"""
    if not isinstance(data, dict):
        return Result(3, "解析失敗"), UNKNOWN_USAGE_USD
    md = data.get("usageMetadata")
    md = md if isinstance(md, dict) else {}
    known = any(isinstance(md.get(k), int) and not isinstance(md.get(k), bool)
                for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount"))
    usd = cost_from_usage(md, entry) if known else UNKNOWN_USAGE_USD  # 使用量が読めないときは控えめに計上
    pf = data.get("promptFeedback")
    if isinstance(pf, dict) and pf.get("blockReason"):
        return Result(3, "安全フィルタ", usage=md), usd
    cands = data.get("candidates")
    if not isinstance(cands, list) or not cands:
        return Result(3, "空応答", usage=md), usd
    cand = cands[0]
    if not isinstance(cand, dict):
        return Result(3, "解析失敗", usage=md), usd
    content = cand.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    parts = parts if isinstance(parts, list) else []
    text = "".join(p["text"] for p in parts
                   if isinstance(p, dict) and not p.get("thought") and isinstance(p.get("text"), str))
    if not text.strip():
        reason = "安全フィルタ" if cand.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST") else "空応答"
        return Result(3, reason, usage=md), usd
    return Result(0, "ok", text=text, usage=md), usd


def generate(
    prompt: str,
    *,
    model: Optional[str] = None,
    max_output_tokens: int = 8192,
    thinking: Optional[str] = "high",
    timeout: float = 240,
    purpose: str = "",
    data_class: Optional[str] = None,
) -> Result:
    m = model or config.env("ORCH_GEMINI_MODEL") or ""
    t0 = time.monotonic()

    def finish(res: Result, usd: float = 0.0, *, skipped: bool = False) -> Result:
        _log(m, res, time.monotonic() - t0, usd, purpose, skipped=skipped)
        return res

    if config.global_halt():   # 全体停止は失敗ではなく本流も止める（docs/specs/20261008_global_halt.md）
        finish(Result(config.HALT_EXIT_CODE, "全体停止中"))
        raise config.GlobalHalt()
    if config.disabled("gemini"):
        return finish(Result(2, "停止中"))
    key = config.env("GEMINI_API_KEY")
    if not key:
        return finish(Result(2, "鍵なし"))
    if daily_usd() >= daily_cap():
        return finish(Result(2, "上限到達"))
    if requests is None:
        return finish(Result(2, REQUESTS_MISSING))

    try:
        roster_path, entry = _roster()
        m = _model(model, entry)
        url = f"https://{entry['hosts'][0]}/v1beta/models/{m}:generateContent"
        budget = gate.Budget(config.data_dir() / "gate_ledger.jsonl", {})
    except gate.GateDenied as error:
        return finish(Result(2, error.reason), skipped=True)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    gen_cfg: Dict[str, Any] = {"maxOutputTokens": int(max_output_tokens)}
    if thinking:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
    task = uuid.uuid4().hex

    for attempt in range(2):
        if config.global_halt():
            finish(Result(config.HALT_EXIT_CODE, "全体停止中"))
            raise config.GlobalHalt()
        # No separate input-length limit exists in this adapter. Reserve from
        # the complete wire body (UTF-8 bytes conservatively bound text tokens).
        wire = json.dumps(body, ensure_ascii=False)
        try:
            reservation = gate.gate(roster_path, entry["id"], [url], [(wire, data_class)],
                                    len(wire), budget, 1, len(wire.encode("utf-8")),
                                    gen_cfg["maxOutputTokens"], task)
        except gate.GateDenied as error:
            return finish(Result(2, error.reason), skipped=True)
        usd, tokens = UNKNOWN_USAGE_USD, reservation["reserved_tokens"]
        retry = False
        try:
            wait = float(timeout)
            if reservation["deadline"] is not None:
                wait = min(wait, reservation["deadline"] - time.time())
            if wait <= 0:
                raise TimeoutError()
            resp = _post_with_timeout(url, headers, body, wait)
            retry = attempt == 0 and bool(thinking) and _thinking_rejected(resp)
            res, usd = _response(resp, entry)
            md = res.usage
            if any(type(md.get(k)) is int and md[k] >= 0 for k in
                   ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount")):
                tokens = sum(max(0, _int(md.get(k))) for k in
                             ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount"))
            elif usd == 0:
                tokens = 0
        except TimeoutError:
            res = Result(2, "タイムアウト")
        except Exception:
            res = Result(2, "通信失敗")
        finally:
            try:
                budget.settle(task, usd, tokens, reservation["epoch"])
            except gate.GateDenied as error:
                # Keep the reservation charged if settlement cannot be recorded.
                try:
                    budget.stop(reservation["epoch"])
                except gate.GateDenied:
                    pass  # An unreadable ledger itself blocks subsequent calls.
                res, retry = Result(2, error.reason), False
        if retry:
            gen_cfg.pop("thinkingConfig", None)
            continue
        return finish(res, usd)


def _response(resp, entry) -> Tuple[Result, float]:
    code = getattr(resp, "status_code", 0)
    text = getattr(resp, "text", "") or ""
    if code in (401, 403):
        return Result(2, "未認証"), 0.0
    if code == 429 or (code != 200 and "RESOURCE_EXHAUSTED" in text):
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
        return False, "gemini: 全体停止中"
    try:
        roster_path, entry = _roster()
        m = _model(None, entry)
    except gate.GateDenied as error:
        return False, f"gemini: {error.reason}"
    spend = f"本日 ${daily_usd():.2f}／上限 ${daily_cap():.2f}"
    if config.global_halt():
        return False, f"gemini: 全体停止中 model={m} {spend}"
    if config.disabled("gemini"):
        return False, f"gemini: 停止中 model={m} {spend}"
    key = config.env("GEMINI_API_KEY")
    if not key:
        return False, f"gemini: 鍵なし model={m} {spend}"
    if requests is None:
        return False, f"gemini: {REQUESTS_MISSING}（bash scripts/setup.sh） model={m} {spend}"
    if not net:
        return True, f"gemini: 鍵あり（疎通は未確認） model={m} {spend}"
    task = uuid.uuid4().hex
    budget = gate.Budget(config.data_dir() / "gate_ledger.jsonl", {})
    url = f"https://{entry['hosts'][0]}/v1beta/models/{m}"
    try:
        reservation = gate.gate(roster_path, entry["id"], [url], [(m, "A")], len(m),
                                budget, 1, 0, 0, task)
    except gate.GateDenied as error:
        _log(m, Result(2, error.reason), 0, 0, "check", skipped=True)
        return False, f"gemini: {error.reason}"
    try:
        wait = net_timeout
        if reservation["deadline"] is not None:
            wait = min(wait, reservation["deadline"] - time.time())
        if wait <= 0:
            raise TimeoutError()
        r = requests.get(url, headers={"x-goog-api-key": key}, timeout=wait, allow_redirects=False)
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
    return auth == "OK", f"gemini: 認証={auth} model={m} {spend}"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="orch.gemini")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--quiet", action="store_true")
    c.add_argument("--no-net", action="store_true")
    g = sub.add_parser("gen")
    g.add_argument("--purpose", default="")
    g.add_argument("--model", default=None)
    g.add_argument("--data-class", choices=("A", "B", "C"), default=None)
    g.add_argument("--thinking", default=None)
    g.add_argument("--timeout", type=float, default=240)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        ok, line = check_status(net=not a.no_net, net_timeout=20)
        print(line)
        return 0 if ok or a.quiet else 2
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("gemini: 標準入力にプロンプトがありません", file=sys.stderr)
        return 2
    try:
        res = generate(prompt, model=a.model, thinking=a.thinking or config.env("ORCH_GEMINI_THINKING", "high"),
                       timeout=a.timeout, purpose=a.purpose, data_class=a.data_class)
    except config.GlobalHalt as e:
        print(f"gemini: {e}", file=sys.stderr)
        return config.HALT_EXIT_CODE
    if res.rc == 0:
        sys.stdout.write(res.text)
    else:
        print(f"gemini: rc={res.rc} {res.reason}", file=sys.stderr)
    return res.rc


if __name__ == "__main__":
    sys.exit(main())
