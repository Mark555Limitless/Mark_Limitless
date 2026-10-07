"""判断層（特定のベンダーに依存しない）。分譲指示書 §5.3。

decisions.ask(state, questions, budget=, backend=, fallback=) で、型のある問いに答える。
問い合わせる順番: jev（JEV_ENABLED=1・DECISION_BACKEND=jev・鍵あり）→ anthropic（claude -p を Haiku→Sonnet）→ rules（既定値）
fallback=False なら、Jev が失敗した時点で既定値を返す。失敗しても本流は止めず、理由を影ログに残す。

注意: この層は助言であり、取り消せない操作（公開・送信・削除・支払い）の承認に使わない。
新しい問いを Jev に任せる前に、正解つきの例を100問以上集めてオフラインで比べる（docs/eval-design.md）。

固定コマンド:
  python3 -m orch.decisions --check            鍵の有無だけを表示（値は出さない）
  python3 -m orch.decisions --demo [--backend jev|anthropic|rules]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from . import config, jev, usage

MAX_OPTIONS = 120
SHADOW_MAX_BYTES = 5 * 1024 * 1024


@dataclass
class Choice:
    prompt: str
    options: Dict[str, str]
    default: str

    def validate(self) -> None:
        if not 1 <= len(self.options) <= MAX_OPTIONS:
            raise ValueError(f"選択肢は1〜{MAX_OPTIONS}個にする")
        if self.default not in self.options:
            raise ValueError("既定値が選択肢にない")

    def wire(self) -> Dict[str, Any]:
        return {"type": "choice", "instructions": self.prompt, "criteria": dict(self.options)}

    def coerce(self, raw: Any) -> Optional[str]:
        if isinstance(raw, dict):
            for k in ("choice", "selected", "answer", "value"):
                if raw.get(k) in self.options:
                    return raw[k]
            return None
        return raw if raw in self.options else None


@dataclass
class Score:
    prompt: str
    levels: List[str]
    default: int

    def validate(self) -> None:
        if not 2 <= len(self.levels) <= 10:
            raise ValueError("段階は2〜10にする")
        if not 0 <= self.default < len(self.levels):
            raise ValueError("既定値が段階の範囲外")

    def wire(self) -> Dict[str, Any]:
        return {"type": "score", "instructions": self.prompt, "criteria": list(self.levels)}

    def coerce(self, raw: Any) -> Optional[int]:
        if isinstance(raw, dict):
            for k in ("score", "level", "answer", "value"):
                if k in raw:
                    return self.coerce(raw[k])
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)) and float(raw).is_integer() and 0 <= int(raw) < len(self.levels):
            return int(raw)
        return None


@dataclass
class Noul:
    prompt: str
    default: float

    def validate(self) -> None:
        if not 0.0 <= self.default <= 1.0:
            raise ValueError("既定値は 0〜1")

    def wire(self) -> Dict[str, Any]:
        return {"type": "noul", "instructions": self.prompt}

    def coerce(self, raw: Any) -> Optional[float]:
        if isinstance(raw, dict):
            for k in ("noul", "probability", "answer", "value"):
                if k in raw:
                    return self.coerce(raw[k])
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)) and 0.0 <= float(raw) <= 1.0:
            return float(raw)
        return None


Question = Union[Choice, Score, Noul]


@dataclass
class DecisionBudget:
    """時間の予算（ミリ秒）。CYCLE_START_EPOCH があれば、便の残り時間（CYCLE_LIMIT_S、既定2100秒）でも打ち切る。"""
    total_ms: int = 8000
    started: float = field(default_factory=time.monotonic)

    def remaining_ms(self) -> int:
        left = self.total_ms - int((time.monotonic() - self.started) * 1000)
        start = config.env("CYCLE_START_EPOCH")
        if start:
            try:
                cycle_left = config.env_int("CYCLE_LIMIT_S", 2100) - (time.time() - float(start))
                left = min(left, int(cycle_left * 1000))
            except ValueError:
                pass
        return max(left, 0)


@dataclass
class Decision:
    answers: Dict[str, Any]
    backend: str
    reason: str
    ms: int
    raw: Dict[str, Any] = field(default_factory=dict)


def _shadow(entry: Dict[str, Any]) -> None:
    path = config.env("DECISION_SHADOW_LOG") or str(config.data_dir() / "decisions_shadow.jsonl")
    try:
        if os.path.exists(path) and os.path.getsize(path) >= SHADOW_MAX_BYTES:
            return  # 5MB で打ち切り
        line = config.redact(json.dumps(entry, ensure_ascii=False))
        with config.file_lock(config.data_dir() / "decisions_shadow.lock"):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass  # 影ログの失敗で本流を止めない


def _defaults(questions: Dict[str, Question]) -> Dict[str, Any]:
    return {k: q.default for k, q in questions.items()}


def _from_jev(state: str, questions: Dict[str, Question], timeout_s: float, purpose: str) -> Dict[str, Any]:
    raw = jev.call(state, {k: q.wire() for k, q in questions.items()}, timeout_s=timeout_s, purpose=purpose)
    out: Dict[str, Any] = {}
    for k, q in questions.items():
        v = q.coerce(raw.get(k))
        if v is None:
            raise jev.JevUnavailable(f"答えの形式が不正: {k}")
        out[k] = v
    return out


def _anthropic_prompt(state: str, questions: Dict[str, Question]) -> str:
    spec = []
    for k, q in questions.items():
        if isinstance(q, Choice):
            spec.append({"id": k, "type": "choice", "question": q.prompt, "options": q.options})
        elif isinstance(q, Score):
            spec.append({"id": k, "type": "score", "question": q.prompt, "levels": {i: s for i, s in enumerate(q.levels)}})
        else:
            spec.append({"id": k, "type": "noul", "question": q.prompt, "answer": "0〜1 の確率"})
    return (
        "次の問いに、JSON オブジェクト1つだけで答えてください。説明文は書かないでください。\n"
        "choice は選択肢のキー、score は段階の番号（整数）、noul は 0〜1 の数を値にします。\n"
        f"問い: {json.dumps(spec, ensure_ascii=False)}\n\n" + config.as_data(state, "判断対象")
    )


def _from_anthropic(state: str, questions: Dict[str, Question], timeout_s: float, purpose: str) -> Dict[str, Any]:
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude CLI なし")
    prompt = _anthropic_prompt(state, questions)
    env = dict(os.environ, FABLE5_HEADLESS="1")  # 無人実行の印（グローバルの SessionStart フックを止める）
    last = "失敗"
    for model in config.MODEL_LADDER:
        t0 = time.monotonic()
        try:
            proc = subprocess.run([claude, "-p", prompt, "--model", model, "--tools", ""],
                                  capture_output=True, text=True, timeout=timeout_s, env=env)
        except subprocess.TimeoutExpired:
            usage.record("anthropic", model=model, purpose=purpose, status="error", ms=int((time.monotonic() - t0) * 1000))
            last = "タイムアウト"
            continue
        ms = int((time.monotonic() - t0) * 1000)
        m = re.search(r"\{.*\}", proc.stdout or "", re.S)
        try:
            raw = json.loads(m.group(0)) if (proc.returncode == 0 and m) else None
        except json.JSONDecodeError:
            raw = None
        out = {}
        if isinstance(raw, dict):
            for k, q in questions.items():
                v = q.coerce(raw.get(k))
                if v is None:
                    break
                out[k] = v
        if len(out) == len(questions):
            usage.record("anthropic", model=model, purpose=purpose, status="ok", ms=ms)
            return out
        usage.record("anthropic", model=model, purpose=purpose, status="error", ms=ms)
        last = "形式不正"
    raise RuntimeError(last)


def ask(
    state: str,
    questions: Dict[str, Question],
    *,
    budget: Optional[DecisionBudget] = None,
    backend: Optional[str] = None,
    fallback: bool = True,
    purpose: str = "",
) -> Decision:
    for q in questions.values():
        q.validate()
    budget = budget or DecisionBudget(total_ms=config.env_int("DECISION_TIMEOUT_MS", 8000))
    backend = backend or config.env("DECISION_BACKEND", "jev") or "jev"
    order = {"jev": ["jev", "anthropic"], "anthropic": ["anthropic"], "rules": []}.get(backend, [])
    if not fallback:
        order = order[:1]
    t0 = time.monotonic()
    reasons: List[str] = []
    answers: Optional[Dict[str, Any]] = None
    used = "rules"
    for step in order:
        left = budget.remaining_ms()
        if left < 500:
            reasons.append(f"{step}: 時間切れ")
            break
        try:
            if step == "jev":
                if not jev.enabled():
                    raise jev.JevUnavailable("無効か鍵なし")
                answers = _from_jev(state, questions, left / 1000, purpose)
            else:
                answers = _from_anthropic(state, questions, max(left / 1000, 1), purpose)
            used = step
            break
        except (jev.JevUnavailable, RuntimeError, OSError) as e:
            reasons.append(f"{step}: {e.args[0] if e.args else type(e).__name__}")
    if answers is None:
        answers = _defaults(questions)
        used = "rules"
    ms = int((time.monotonic() - t0) * 1000)
    reason = "; ".join(reasons) if reasons else "ok"
    _shadow({
        "ts": config.ts(), "purpose": purpose[:80], "backend": used, "reason": reason, "ms": ms,
        "state_chars": len(state),  # 判断対象の本文は書かない
        "questions": {k: {"type": type(q).__name__.lower(), "prompt": q.prompt} for k, q in questions.items()},
        "answers": answers,
    })
    return Decision(answers=answers, backend=used, reason=reason, ms=ms)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="orch.decisions")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--backend", choices=("jev", "anthropic", "rules"), default=None)
    a = ap.parse_args(argv)
    if a.check:
        print(f"decisions: JEV_ENABLED={config.env('JEV_ENABLED', '0')} DECISION_BACKEND={config.env('DECISION_BACKEND', 'jev')} "
              f"TYPESAFE_API_KEY={'あり' if config.env('TYPESAFE_API_KEY') else 'なし'} claude={'あり' if shutil.which('claude') else 'なし'}")
        print(jev.status_line())
        return 0
    if a.demo:
        qs: Dict[str, Question] = {
            "topic": Choice("この文章の主題はどれか", {"weather": "天気", "food": "食べ物", "other": "その他"}, "other"),
            "polite": Score("この文章の丁寧さ", ["くだけている", "普通", "丁寧"], 1),
            "question": Noul("この文章は質問か", 0.5),
        }
        d = ask("明日の東京は晴れるでしょうか。", qs, backend=a.backend, purpose="demo")
        print(json.dumps({"backend": d.backend, "answers": d.answers, "reason": d.reason, "ms": d.ms}, ensure_ascii=False))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
