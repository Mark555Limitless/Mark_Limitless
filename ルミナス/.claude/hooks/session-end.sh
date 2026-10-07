#!/usr/bin/env bash
# SessionEnd hook: Obsidian 同期と最終プロンプト docx の再生成（毎回）。失敗は state/.session-end.log に残し、次回 SessionStart で警告する。
# Codex の実行中（data/codex_runs/.lock の持ち主が生きている）は、作業フォルダ内を書き換える処理（docx 再生成・記録の切り詰め）を見送り、
# 記録への追記だけを行う（実行中の書き換えは範囲検査で違反になるため。Obsidian 同期は作業フォルダの外へ書くので行う）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
LOG="$ROOT/state/.session-end.log"
RUNNING=0; hook_codex_running && RUNNING=1
{
  echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) SessionEnd"
  bash "$ROOT/scripts/sync-obsidian.sh" 2>&1 || echo "sync-obsidian 失敗"
  if [ "$RUNNING" = 1 ]; then
    echo "Codex 実行中のため docx 再生成を見送り（次回の SessionEnd で行う）"
  elif command -v node >/dev/null 2>&1; then
    (cd "$ROOT" && node scripts/build-final-prompt-docx.mjs 2>&1) || echo "docx 再生成 失敗（scripts/setup.sh を実行して docx 依存を入れる）"
  else
    echo "docx 再生成 失敗: node が無い"
  fi
} >> "$LOG" 2>&1
if [ "$RUNNING" = 0 ]; then
  tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  hook_flush_escalations >> "$LOG" 2>&1   # Codex の実行中に保留したモデル切替の記録を移す
fi
exit 0
