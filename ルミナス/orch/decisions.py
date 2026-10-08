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
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from . import config, jev, usage

MAX_OPTIONS = 120
SHADOW_MAX_BYTES = 5 * 1024 * 1024
META_TOP_K = 5  # 影ログに残す Choice の確率は上位 5 件と残りの合計だけ（120 択を全部書くと 5MB にすぐ届く）


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
                v = raw.get(k)
                if isinstance(v, str) and v in self.options:
                    return v
            return None
        return raw if isinstance(raw, str) and raw in self.options else None


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
            # Jev の score は段階を確率で重み付けした値（例 1.43）で、段階の番号ではない。
            # probabilities があれば、確率が最大の段階を答えにする（同点は小さい番号）
            if "probabilities" in raw:
                return _top_level(raw["probabilities"], len(self.levels))
            for k in ("score", "level", "answer", "value"):
                if k in raw:
                    return self.coerce(raw[k])
            return None
        if isinstance(raw, bool):
            return None
        # 範囲を先に比べる（桁の大きい整数を float に直すと OverflowError になるため。NaN は比較が偽）
        if isinstance(raw, (int, float)) and 0 <= raw < len(self.levels) and float(raw).is_integer():
            return int(raw)
        return None


def _prob(x: Any) -> bool:
    # 0〜1 の数か。float に直さずに比べる（桁の大きい整数でも OverflowError にならない。NaN・無限大は偽）
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= x <= 1.0


def _top_level(probs: Any, n: int) -> Optional[int]:
    """{"0": 0.0, "1": 0.57, "2": 0.43} → 1。キーが段階の番号でない・確率でない値がある、
    全部 0、合計が 1 から外れているときは壊れた答えとして None（判断層は次の手段へ落ちる）。
    合計の許容幅は、確率が小数第 2 位に丸められていても通るよう、段階ごとの丸めの誤差 0.005 × 個数（最小 0.01）に
    浮動小数の余裕を足したもの（例: 0.34+0.34+0.33=1.01 は通す）。"""
    if not isinstance(probs, dict) or not probs:
        return None
    best: Optional[int] = None
    best_p = -1.0
    total = 0.0
    for k, p in probs.items():
        if not (isinstance(k, str) and k.isascii() and k.isdigit() and str(int(k)) == k and int(k) < n and _prob(p)):
            return None
        lv = int(k)
        total += float(p)
        if p > best_p or (p == best_p and best is not None and lv < best):
            best, best_p = lv, float(p)
    if best_p <= 0.0 or abs(total - 1.0) > max(0.01, 0.005 * len(probs)) + 1e-9:
        return None
    return best


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
        if isinstance(raw, (int, float)) and 0.0 <= raw <= 1.0:  # 範囲を先に比べる（Score.coerce と同じ理由）
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
    raw: Dict[str, Any] = field(default_factory=dict)  # Jev のときだけ: 問いごとの confidence・probabilities・score


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


def _jev_meta(q: Question, raw: Any) -> Dict[str, Any]:
    """Jev の答えから、確信度（Jev が返した値だけ）・確率分布・score（確率で重み付けした値）を取り出す。
    確率のキーは問いの選択肢・段階の番号に限る（応答の任意の文字列を影ログに書かない）。値は小数第 4 位に丸め、
    Choice は確率の上位 META_TOP_K 件と残りの合計（rest）に縮める。
    Noul は answers の値がそのまま確率で、確信度は返らない（必要なら呼び手が |2p-1| を計算する）ので何も足さない。"""
    meta: Dict[str, Any] = {}
    if not isinstance(raw, dict) or isinstance(q, Noul):
        return meta
    if _prob(raw.get("confidence")):
        meta["confidence"] = round(float(raw["confidence"]), 4)
    valid = set(q.options) if isinstance(q, Choice) else {str(i) for i in range(len(q.levels))}
    probs = raw.get("probabilities")
    if isinstance(probs, dict) and probs and all(k in valid and _prob(v) for k, v in probs.items()):
        if isinstance(q, Choice):
            items = sorted(((k, float(v)) for k, v in probs.items()), key=lambda kv: -kv[1])
            if len(items) > META_TOP_K:
                meta["rest"] = round(sum(v for _, v in items[META_TOP_K:]), 4)
                items = items[:META_TOP_K]
        else:
            items = sorted(((k, float(v)) for k, v in probs.items()), key=lambda kv: int(kv[0]))
        meta["probabilities"] = {k: round(v, 4) for k, v in items}
    s = raw.get("score")
    if isinstance(q, Score) and isinstance(s, (int, float)) and not isinstance(s, bool) and 0 <= s <= len(q.levels) - 1:
        meta["score"] = round(float(s), 4)
    return meta


def _from_jev(state: str, questions: Dict[str, Question], timeout_s: float, purpose: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    raw = jev.call(state, {k: q.wire() for k, q in questions.items()}, timeout_s=timeout_s, purpose=purpose)
    out: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    for k, q in questions.items():
        v = q.coerce(raw.get(k))
        if v is None:
            raise jev.JevUnavailable(f"答えの形式が不正: {k}")
        out[k] = v
        meta[k] = _jev_meta(q, raw.get(k))
    return out, meta


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


def _child_env() -> Dict[str, str]:
    """claude -p に渡す環境: 鍵を外し（ANTHROPIC_API_KEY があると API 課金に切り替わり台帳とずれる）、無人実行の印を付ける。"""
    env = {k: v for k, v in os.environ.items() if k not in config.SECRET_ENV_NAMES}
    env["FABLE5_HEADLESS"] = "1"  # グローバルの SessionStart フックを止める
    return env


def _from_anthropic(state: str, questions: Dict[str, Question], budget: "DecisionBudget", purpose: str) -> Dict[str, Any]:
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude CLI なし")
    prompt = _anthropic_prompt(state, questions)
    env = _child_env()
    last = "失敗"
    workdir = tempfile.mkdtemp(prefix="luminous-decide-")  # プロジェクトの外で起動する（project hooks を走らせない）
    try:
        for model in config.MODEL_LADDER:
            left = budget.remaining_ms()
            if left < 500:
                last = "時間切れ"
                break
            t0 = time.monotonic()
            try:
                # 判断対象の本文は argv ではなく標準入力で渡す（ps に見せない・長さの上限を避ける）
                proc = subprocess.run([claude, "-p", "標準入力の指示に従い、JSON オブジェクト1つだけを返してください。",
                                       "--model", model, "--tools", ""],
                                      input=prompt, capture_output=True, text=True, timeout=left / 1000,
                                      env=env, cwd=workdir)
            except subprocess.TimeoutExpired:
                usage.record("anthropic", model=model, purpose=purpose, status="error", ms=int((time.monotonic() - t0) * 1000))
                last = "タイムアウト"
                continue
            except OSError:
                usage.record("anthropic", model=model, purpose=purpose, status="error", ms=int((time.monotonic() - t0) * 1000))
                last = "起動失敗"
                continue
            ms = int((time.monotonic() - t0) * 1000)
            m = re.search(r"\{.*\}", proc.stdout or "", re.S)
            try:
                raw = json.loads(m.group(0)) if (proc.returncode == 0 and m) else None
            except json.JSONDecodeError:
                raw = None
            out: Dict[str, Any] = {}
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
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
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
    meta: Dict[str, Any] = {}
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
                answers, meta = _from_jev(state, questions, left / 1000, purpose)
            else:
                answers = _from_anthropic(state, questions, budget, purpose)
            used = step
            break
        except (jev.JevUnavailable, RuntimeError) as e:
            reasons.append(f"{step}: {e.args[0] if e.args else type(e).__name__}")
        except Exception as e:  # noqa: BLE001 想定外の失敗でも本流を止めず既定値へ（生のメッセージは書かない）
            reasons.append(f"{step}: 想定外の失敗（{type(e).__name__}）")
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
        "jev": meta,  # 確信度・確率分布（評価の校正指標に使う。docs/eval-design.md §3）
    })
    return Decision(answers=answers, backend=used, reason=reason, ms=ms, raw=meta)


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
        print(json.dumps({"backend": d.backend, "answers": d.answers, "reason": d.reason, "ms": d.ms, "jev": d.raw}, ensure_ascii=False))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
