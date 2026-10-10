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


def test_lines_show_halt_without_exception(monkeypatch, isolated_env):
    from orch import config
    config.HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.HALT_PATH.write_text("2026-10-10T00:00:00Z 試験\n", encoding="utf-8")
    monkeypatch.setattr(health, "CODEX_APP_PATH", "/nonexistent/codex")
    monkeypatch.setattr(health.shutil, "which", lambda n: None)
    lines = health.lines(net=False)
    assert len(lines) == 4 and lines[0].startswith("!!! 全体停止中")
    assert "停止中" in lines[1] and "全体停止中" in lines[2] and "全体停止中" in lines[3]

