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
import time
from typing import Any, Dict, Optional, Tuple

import requests

from . import config, usage

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_M_INPUT = 0.042  # 入力 100万トークンあたり（10億あたり $42。自社公表 2026-09）
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
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _usd(resp_json: Any, n_questions: int) -> float:
    u = resp_json.get("usage") if isinstance(resp_json, dict) else None
    u = u if isinstance(u, dict) else {}
    if _num(u.get("cost")):
        return float(u["cost"])
    if _num(u.get("input_tokens")):
        return float(u["input_tokens"]) * PRICE_PER_M_INPUT / 1_000_000
    return FALLBACK_USD_PER_QUESTION * max(n_questions, 1)


def call(state: str, questions: Dict[str, Dict[str, Any]], *, timeout_s: float = 8.0, purpose: str = "") -> Dict[str, Any]:
    """Jev に問い合わせ、answers の辞書を返す。呼ばなかった・失敗したときは JevUnavailable（失敗も1回に数える）。"""
    key = config.env("TYPESAFE_API_KEY")
    if config.env("JEV_ENABLED", "0") != "1":
        raise JevUnavailable("無効（JEV_ENABLED!=1）")
    if not key:
        raise JevUnavailable("鍵なし")
    ok, why = limits_ok()
    if not ok:
        raise JevUnavailable(why)
    model = config.env("JEV_MODEL", "jev-latest") or "jev-latest"
    body = {"state": state, "model": model, "questions": questions}
    t = max(float(timeout_s), 0.1)
    t0 = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - t0) * 1000)

    try:
        resp = requests.post(config.env("JEV_ENDPOINT", DEFAULT_ENDPOINT),  # type: ignore[arg-type]
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                             json=body, timeout=(min(5.0, t), t))
    except Exception:  # noqa: BLE001 通信の例外はすべて「通信失敗」（生のエラーは記録しない）
        _log("error", None, model, elapsed(), 0.0, purpose, "通信失敗")
        raise JevUnavailable("通信失敗")
    http = getattr(resp, "status_code", None)
    if http != 200:
        _log("error", http, model, elapsed(), 0.0, purpose, f"HTTP {http}")
        raise JevUnavailable(f"HTTP {http}")
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 JSON でない応答。処理された可能性があるので控えめに計上
        _log("error", http, model, elapsed(), FALLBACK_USD_PER_QUESTION * max(len(questions), 1), purpose, "解析失敗")
        raise JevUnavailable("解析失敗")
    usd = _usd(data, len(questions))
    answers = data.get("answers") if isinstance(data, dict) else None
    resp_model = str(data.get("model", model)) if isinstance(data, dict) else model
    if not isinstance(answers, dict):
        _log("error", http, resp_model, elapsed(), usd, purpose, "answers なし")
        raise JevUnavailable("answers なし")
    _log("ok", http, resp_model, elapsed(), usd, purpose, "ok")
    return answers


def status_line() -> str:
    key = "あり" if config.env("TYPESAFE_API_KEY") else "なし"
    on = "有効" if config.env("JEV_ENABLED", "0") == "1" else "無効"
    stop = "停止中" if config.disabled("jev") else "稼働"
    return (f"jev: 鍵={key} {on} {stop} 本日 {usage.today_calls('jev')}/{config.env_int('ORCH_JEV_DAILY_MAX', 60)}回 "
            f"今月 ${usage.month_usd('jev'):.4f}／上限 ${config.env_float('ORCH_JEV_MONTHLY_USD', 1.0):.2f}")
