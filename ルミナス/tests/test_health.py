from orch import health


def test_lines_without_network(monkeypatch):
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    lines = health.lines(net=False)
    assert len(lines) == 3
    assert lines[0].startswith("codex: 本体=なし") and lines[1].startswith("gemini: 鍵なし") and lines[2].startswith("jev: 鍵=なし")


def test_codex_disabled(monkeypatch):
    monkeypatch.setenv("ORCH_CODEX", "0")
    assert "停止中" in health.codex_line()
