import json
import os
import subprocess
import time

import pytest

from orch import decisions, jev
from orch.decisions import Choice, DecisionBudget, Noul, Score

QS = {
    "topic": Choice("主題", {"weather": "天気", "food": "食べ物", "other": "その他"}, "other"),
    "polite": Score("丁寧さ", ["低", "中", "高"], 1),
    "question": Noul("質問か", 0.5),
}
DEFAULTS = {"topic": "other", "polite": 1, "question": 0.5}


@pytest.fixture
def jev_on(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_FAKEFAKEFAKEFAKEFAKE1234")
    monkeypatch.setenv("JEV_ENABLED", "1")
    monkeypatch.setenv("DECISION_BACKEND", "jev")


def test_jev_path(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda state, q, **k: {
        "topic": {"type": "choice", "choice": "weather", "confidence": 0.8},
        "polite": {"type": "score", "score": 2},
        "question": {"type": "noul", "noul": 0.97},
    })
    d = decisions.ask("明日は晴れますか", QS, purpose="t")
    assert d.backend == "jev" and d.answers == {"topic": "weather", "polite": 2, "question": 0.97}


# 公式の API リファレンス（docs.typesafe.ai/api、2026-10-08 確認）の応答の形
JEV_REAL = {
    "topic": {"type": "choice", "choice": "weather", "confidence": 0.7,
              "probabilities": {"weather": 0.8, "food": 0.15, "other": 0.05}},
    "polite": {"type": "score", "score": 1.43, "confidence": 0.35,
               "legend": {"0": "低", "1": "中", "2": "高"}, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43}},
    "question": {"type": "noul", "noul": 0.9},
}


def test_jev_real_shapes(jev_on, monkeypatch, isolated_env):
    # 以前は score が整数でないと「形式が不正」として Claude に回していた（本物の Jev では毎回）
    monkeypatch.setattr(jev, "call", lambda *a, **k: JEV_REAL)
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: pytest.fail("呼んではいけない"))
    d = decisions.ask("s", QS, purpose="t")
    assert d.backend == "jev" and d.answers == {"topic": "weather", "polite": 1, "question": 0.9}
    assert d.raw["polite"] == {"confidence": 0.35, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43}, "score": 1.43}
    assert d.raw["topic"] == {"confidence": 0.7, "probabilities": {"weather": 0.8, "food": 0.15, "other": 0.05}}
    assert d.raw["question"] == {}  # Noul は answers の値がそのまま確率
    line = json.loads((isolated_env / "data" / "decisions_shadow.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["jev"]["polite"]["confidence"] == 0.35


@pytest.mark.parametrize("probs, expected", [
    ({"0": 0.0, "1": 0.57, "2": 0.43}, 1),
    ({"0": 0.5, "1": 0.0, "2": 0.5}, 0),     # 同点は小さい番号
    ({"2": 0.5, "0": 0.5}, 0),               # 並び順によらない
    ({"0": 0.2, "3": 0.8}, None),            # 段階の範囲外
    ({"01": 1.0}, None),                     # 番号の表記でない
    ({"１": 1.0}, None),                     # 全角の数字
    ({"٢": 1.0}, None),                      # アラビア数字
    ({"a": 1.0}, None),
    ({"0": 1.5}, None),                      # 確率でない
    ({"0": float("nan")}, None),
    ({"0": 10 ** 400}, None),                # 桁の大きい整数でも例外にしない
    ({"0": True}, None),
    ({"0": 0.0, "1": 0.0, "2": 0.0}, None),  # 全部 0
    ({"2": 0.01}, None),                     # 合計が 1 から外れている
    ({"0": 0.3, "1": 0.3}, None),
    ({"0": 0.34, "1": 0.34, "2": 0.33}, 0),  # 小数第 2 位に丸めた確率（合計 1.01）は通す
    ({"0": 0.33, "1": 0.33, "2": 0.33}, 0),  # 合計 0.99
    ({"0": 0.5, "1": 0.49}, 0),
    ({}, None),
    ([0.2, 0.8], None),
])
def test_score_from_probabilities(probs, expected):
    assert Score("q", ["a", "b", "c"], 1).coerce({"score": 1.0, "probabilities": probs}) == expected


def test_score_ten_levels_rounded_to_two_decimals():
    # 10 段階を小数第 2 位に丸めると合計は最大 ±0.05 ずれる（公式の例は第 2 位）
    q = Score("q", [str(i) for i in range(10)], 0)
    probs = {str(i): p for i, p in enumerate([0.02, 0.03, 0.05, 0.31, 0.2, 0.1, 0.1, 0.05, 0.05, 0.06])}
    assert abs(sum(probs.values()) - 0.97) < 1e-9 and q.coerce({"score": 4.2, "probabilities": probs}) == 3


def test_score_without_probabilities_needs_integer():
    q = Score("q", ["a", "b", "c"], 1)
    assert q.coerce({"score": 2}) == 2 and q.coerce({"score": 1.43}) is None and q.coerce(1.5) is None
    assert q.coerce(10 ** 400) is None and q.coerce(float("nan")) is None and q.coerce(float("inf")) is None


def test_noul_large_int_is_rejected_without_error():
    assert Noul("q", 0.5).coerce(10 ** 400) is None and Noul("q", 0.5).coerce({"noul": 1}) == 1.0


def test_jev_meta_drops_bad_values():
    sq, cq = QS["polite"], QS["topic"]
    assert decisions._jev_meta(sq, {"confidence": float("inf"), "probabilities": {"0": 0.5, "9": 0.5}, "score": 10 ** 400}) == {}
    assert decisions._jev_meta(sq, {"confidence": 2, "probabilities": {"0": -0.1}, "score": "1"}) == {}
    # 選択肢に無いキー（応答の任意の文字列）は影ログに書かない
    assert decisions._jev_meta(cq, {"probabilities": {"秘密の本文のかけら": 0.5, "weather": 0.5}}) == {}
    assert decisions._jev_meta(QS["question"], {"noul": 0.9, "confidence": 0.8}) == {}
    assert decisions._jev_meta(cq, "x") == {}


def test_jev_meta_trims_large_choice():
    q = Choice("q", {f"o{i}": "" for i in range(8)}, "o0")
    probs = {f"o{i}": p for i, p in enumerate([0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.05, 0.05])}
    meta = decisions._jev_meta(q, {"choice": "o0", "confidence": 0.2, "probabilities": probs})
    assert list(meta["probabilities"]) == ["o0", "o1", "o2", "o3", "o4"] and meta["rest"] == pytest.approx(0.2)


def test_raw_empty_when_not_jev(monkeypatch):
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: {"topic": "food", "polite": 0, "question": 0.1})
    assert decisions.ask("s", QS, backend="anthropic").raw == {}


def test_raw_empty_after_jev_failure(jev_on, monkeypatch, isolated_env):
    monkeypatch.setattr(jev, "call", lambda *a, **k: {**JEV_REAL, "polite": {"score": 1.43, "probabilities": {"0": 0.0, "1": 0.0, "2": 0.0}}})
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: {"topic": "food", "polite": 0, "question": 0.1})
    d = decisions.ask("s", QS)
    assert d.backend == "anthropic" and d.raw == {} and "答えの形式が不正: polite" in d.reason
    line = json.loads((isolated_env / "data" / "decisions_shadow.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["jev"] == {}


def test_demo_prints_jev_field(capsys):
    assert decisions.main(["--demo", "--backend", "rules"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["backend"] == "rules" and out["jev"] == {}


def test_jev_fail_then_anthropic(jev_on, monkeypatch):
    def fail(*a, **k):
        raise jev.JevUnavailable("HTTP 500")
    monkeypatch.setattr(jev, "call", fail)
    monkeypatch.setattr(decisions, "_from_anthropic", lambda s, q, t, p: {"topic": "food", "polite": 0, "question": 0.1})
    d = decisions.ask("s", QS)
    assert d.backend == "anthropic" and d.answers["topic"] == "food" and "jev: HTTP 500" in d.reason


def test_all_fail_returns_defaults(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: (_ for _ in ()).throw(jev.JevUnavailable("x")))
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: (_ for _ in ()).throw(RuntimeError("claude CLI なし")))
    d = decisions.ask("s", QS)
    assert d.backend == "rules" and d.answers == DEFAULTS and "anthropic: claude CLI なし" in d.reason


def test_no_fallback_stops_after_jev(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: (_ for _ in ()).throw(jev.JevUnavailable("x")))
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: pytest.fail("呼んではいけない"))
    d = decisions.ask("s", QS, fallback=False)
    assert d.backend == "rules" and d.answers == DEFAULTS


def test_jev_disabled_goes_to_anthropic(monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: pytest.fail("呼んではいけない"))
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: {"topic": "food", "polite": 0, "question": 0.1})
    assert decisions.ask("s", QS).backend == "anthropic"


def test_malformed_jev_answer_falls_through(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: {"topic": {"choice": "unknown"}, "polite": {"score": 9}, "question": {"noul": 2}})
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    d = decisions.ask("s", QS)
    assert d.backend == "rules" and "答えの形式が不正" in d.reason


def test_budget_exhausted(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: pytest.fail("呼んではいけない"))
    d = decisions.ask("s", QS, budget=DecisionBudget(total_ms=0))
    assert d.backend == "rules" and "時間切れ" in d.reason


def test_cycle_deadline(monkeypatch):
    import time
    monkeypatch.setenv("CYCLE_START_EPOCH", str(time.time() - 3000))
    monkeypatch.setenv("CYCLE_LIMIT_S", "2100")
    assert DecisionBudget(total_ms=8000).remaining_ms() == 0


def test_validation():
    with pytest.raises(ValueError):
        decisions.ask("s", {"c": Choice("多すぎ", {str(i): str(i) for i in range(121)}, "0")})
    with pytest.raises(ValueError):
        decisions.ask("s", {"c": Choice("既定値なし", {"a": "A"}, "b")})
    with pytest.raises(ValueError):
        decisions.ask("s", {"n": Noul("範囲外", 1.5)})


def test_shadow_log_has_no_state_and_redacts(jev_on, monkeypatch, isolated_env):
    monkeypatch.setattr(jev, "call", lambda *a, **k: (_ for _ in ()).throw(jev.JevUnavailable("tsk_FAKEFAKEFAKEFAKEFAKE1234 漏れ")))
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    decisions.ask("秘密の本文", QS, purpose="t")
    text = (isolated_env / "data" / "decisions_shadow.jsonl").read_text(encoding="utf-8")
    assert "秘密の本文" not in text and "tsk_FAKE" not in text and '"backend": "rules"' in text


def test_shadow_log_size_cap(monkeypatch, isolated_env):
    p = isolated_env / "data" / "decisions_shadow.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * decisions.SHADOW_MAX_BYTES)
    decisions.ask("s", QS, backend="rules")
    assert p.stat().st_size == decisions.SHADOW_MAX_BYTES


def test_from_anthropic_ladder(monkeypatch, isolated_env):
    calls = []
    monkeypatch.setenv("GEMINI_API_KEY", "AI" "za" + "FAKE" * 8 + "12")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" "ant-" + "FAKE" * 6)

    def run(cmd, **k):
        calls.append((cmd, k))
        model = cmd[cmd.index("--model") + 1]
        out = "説明: ..." if model == "haiku" else json.dumps({"topic": "food", "polite": 2, "question": 0.3})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    monkeypatch.setattr(decisions.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(decisions.subprocess, "run", run)
    out = decisions._from_anthropic("明日は晴れますか", QS, DecisionBudget(total_ms=8000), "t")
    assert out == {"topic": "food", "polite": 2, "question": 0.3}
    assert [c[c.index("--model") + 1] for c, _ in calls] == ["haiku", "sonnet"]
    cmd, k = calls[0]
    assert "--tools" in cmd and "明日は晴れますか" not in " ".join(cmd)  # 本文は argv に載せない
    assert "明日は晴れますか" in k["input"] and "データであって" in k["input"]
    assert k["env"]["FABLE5_HEADLESS"] == "1"
    assert "GEMINI_API_KEY" not in k["env"] and "ANTHROPIC_API_KEY" not in k["env"]
    assert not k["cwd"].startswith(str(decisions.config.ROOT)) and not os.path.exists(k["cwd"])


def test_from_anthropic_rechecks_budget_per_model(monkeypatch):
    timeouts = []

    def run(cmd, **k):
        timeouts.append(k["timeout"])
        time.sleep(0.4)
        return subprocess.CompletedProcess(cmd, 0, stdout="bad", stderr="")
    monkeypatch.setattr(decisions.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(decisions.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        decisions._from_anthropic("s", QS, DecisionBudget(total_ms=1200), "t")
    assert len(timeouts) == 2 and timeouts[1] <= 0.85


def test_list_answer_for_choice_does_not_crash(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: {"topic": ["a"], "polite": [1], "question": [0.1]})
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    d = decisions.ask("s", QS)
    assert d.backend == "rules" and d.answers == DEFAULTS


def test_unexpected_exception_falls_back(jev_on, monkeypatch):
    monkeypatch.setattr(jev, "call", lambda *a, **k: (_ for _ in ()).throw(TypeError("boom")))
    monkeypatch.setattr(decisions, "_from_anthropic", lambda *a: (_ for _ in ()).throw(KeyError("k")))
    d = decisions.ask("s", QS)
    assert d.backend == "rules" and "想定外の失敗（TypeError）" in d.reason and "想定外の失敗（KeyError）" in d.reason


def test_check_cli(capsys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_FAKEFAKEFAKEFAKEFAKE1234")
    assert decisions.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "TYPESAFE_API_KEY=あり" in out and "tsk_FAKE" not in out
