#!/usr/bin/env bash
# SessionEnd hook: Obsidian 同期と最終プロンプト docx の再生成（毎回）。失敗は state/.session-end.log に残し、次回 SessionStart で警告する。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="$ROOT/state/.session-end.log"
{
  echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) SessionEnd"
  bash "$ROOT/scripts/sync-obsidian.sh" 2>&1 || echo "sync-obsidian 失敗"
  if command -v node >/dev/null 2>&1; then
    (cd "$ROOT" && node scripts/build-final-prompt-docx.mjs 2>&1) || echo "docx 再生成 失敗（scripts/setup.sh を実行して docx 依存を入れる）"
  else
    echo "docx 再生成 失敗: node が無い"
  fi
} >> "$LOG" 2>&1
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
exit 0
