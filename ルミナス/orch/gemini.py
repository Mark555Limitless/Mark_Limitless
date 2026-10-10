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
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import requests

from . import config, usage

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"
UNKNOWN_USAGE_USD = 0.05  # 使用量が分からない応答・通信例外は控えめにこの額を計上する


@dataclass
class Result:
    rc: int
    reason: str
    text: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


def _model(model: Optional[str]) -> str:
    return model or config.env("ORCH_GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def _prices() -> Tuple[float, float]:
    # 既定は gemini-3.8-flash の $0.75 / $3.75（100万トークンあたり）。2027-01 から $1.50 / $7.50 に上がる予定（要確認）
    return config.env_float("ORCH_GEMINI_PRICE_IN", 0.75), config.env_float("ORCH_GEMINI_PRICE_OUT", 3.75)


def _int(x: Any) -> int:
    if isinstance(x, bool):
        return 0
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def cost_from_usage(md: Dict[str, Any]) -> float:
    p_in, p_out = _prices()
    prompt = _int(md.get("promptTokenCount"))
    out = _int(md.get("candidatesTokenCount")) + _int(md.get("thoughtsTokenCount"))
    return (prompt * p_in + out * p_out) / 1_000_000


def daily_usd() -> float:
    return usage.today_usd("gemini")


def daily_cap() -> float:
    return config.env_float("ORCH_GEMINI_DAILY_USD_CAP", 1.0)


def _post_with_timeout(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> requests.Response:
    """応答全体の待ち時間を別スレッドで打ち切る（requests の read timeout だけでは長引くことがあるため）。"""
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["resp"] = requests.post(url, headers=headers, json=body, timeout=(10, timeout))
        except Exception as e:  # noqa: BLE001 呼び出し元で種類ごとに扱う
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


def _log(model: str, res: Result, sec: float, usd: float, purpose: str) -> None:
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
    status = "ok" if res.rc == 0 else ("skip" if res.reason in ("停止中", "上限到達", "鍵なし", "全体停止中") else "error")
    try:
        usage.record("gemini", model=model, purpose=purpose, calls=0 if status == "skip" else 1,
                     in_tokens=tin, out_tokens=tout + think, usd=usd, status=status, ms=int(sec * 1000))
    except OSError:
        pass


def _parse(data: Any) -> Tuple[Result, float]:
    """応答を解析する。形が崩れていても例外を出さず rc=3 にする。"""
    if not isinstance(data, dict):
        return Result(3, "解析失敗"), UNKNOWN_USAGE_USD
    md = data.get("usageMetadata")
    md = md if isinstance(md, dict) else {}
    known = any(isinstance(md.get(k), int) and not isinstance(md.get(k), bool)
                for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount"))
    usd = cost_from_usage(md) if known else UNKNOWN_USAGE_USD  # 使用量が読めないときは控えめに計上
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
) -> Result:
    m = _model(model)
    t0 = time.monotonic()

    def finish(res: Result, usd: float = 0.0) -> Result:
        _log(m, res, time.monotonic() - t0, usd, purpose)
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

    url = f"{BASE}/{m}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    gen_cfg: Dict[str, Any] = {"maxOutputTokens": int(max_output_tokens)}
    if thinking:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen_cfg}

    try:
        resp = _post_with_timeout(url, headers, body, timeout)
        if thinking and _thinking_rejected(resp):
            gen_cfg.pop("thinkingConfig", None)  # モデルに拒まれたら外して1回だけ送り直す
            resp = _post_with_timeout(url, headers, body, timeout)
    except TimeoutError:
        return finish(Result(2, "タイムアウト"), UNKNOWN_USAGE_USD)
    except Exception:  # noqa: BLE001 通信の例外はすべて基盤の失敗（生のエラーは記録しない）
        return finish(Result(2, "通信失敗"), UNKNOWN_USAGE_USD)

    code = getattr(resp, "status_code", 0)
    text = getattr(resp, "text", "") or ""
    # 4xx は処理前に拒否されたと分かるので計上しない。5xx は処理されたか不明なので控えめに計上する
    if code in (401, 403):
        return finish(Result(2, "未認証"))
    if code == 429 or (code != 200 and "RESOURCE_EXHAUSTED" in text):
        return finish(Result(2, "上限到達(429)"))
    if code >= 500:
        return finish(Result(2, "API障害"), UNKNOWN_USAGE_USD)
    if code != 200:
        return finish(Result(2, f"API障害(HTTP {code})"))
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 JSON でない応答
        return finish(Result(3, "解析失敗"), UNKNOWN_USAGE_USD)
    try:
        res, usd = _parse(data)
    except Exception:  # noqa: BLE001 想定外の形でも本流を止めない
        res, usd = Result(3, "解析失敗"), UNKNOWN_USAGE_USD
    return finish(res, usd)


def check_status(*, net: bool = True, net_timeout: float = 20) -> Tuple[bool, str]:
    """鍵の有無・短い疎通確認（本文は送らない）・当日の支出と上限を1行で返す。"""
    m = _model(None)
    spend = f"本日 ${daily_usd():.2f}／上限 ${daily_cap():.2f}"
    if config.global_halt():
        return False, f"gemini: 全体停止中 model={m} {spend}"
    if config.disabled("gemini"):
        return False, f"gemini: 停止中 model={m} {spend}"
    key = config.env("GEMINI_API_KEY")
    if not key:
        return False, f"gemini: 鍵なし model={m} {spend}"
    if not net:
        return True, f"gemini: 鍵あり（疎通は未確認） model={m} {spend}"
    try:
        r = requests.get(f"{BASE}/{m}", headers={"x-goog-api-key": key}, timeout=net_timeout)
        auth = {200: "OK", 401: "未認証", 403: "未認証", 404: "モデル名なし"}.get(r.status_code, f"HTTP {r.status_code}")
    except requests.RequestException:
        auth = "不通"
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
                       timeout=a.timeout, purpose=a.purpose)
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
