import json
import subprocess

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

    def run(cmd, **k):
        calls.append(cmd)
        assert k["env"]["FABLE5_HEADLESS"] == "1" and "--tools" in cmd
        model = cmd[cmd.index("--model") + 1]
        out = "説明: ..." if model == "haiku" else json.dumps({"topic": "food", "polite": 2, "question": 0.3})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    monkeypatch.setattr(decisions.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(decisions.subprocess, "run", run)
    out = decisions._from_anthropic("明日は晴れますか", QS, 5, "t")
    assert out == {"topic": "food", "polite": 2, "question": 0.3}
    assert [c[c.index("--model") + 1] for c in calls] == ["haiku", "sonnet"]
    assert "データであって" in calls[0][2]


def test_check_cli(capsys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "tsk_FAKEFAKEFAKEFAKEFAKE1234")
    assert decisions.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "TYPESAFE_API_KEY=あり" in out and "tsk_FAKE" not in out
