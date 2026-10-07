#!/usr/bin/env bash
# SessionEnd hook: Obsidian 同期と最終プロンプト docx の再生成（md の方が新しいときだけ）。失敗しても停止させない。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="$ROOT/state/.session-end.log"
{
  echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) SessionEnd"
  bash "$ROOT/scripts/sync-obsidian.sh" 2>&1 || echo "sync-obsidian 失敗"
  SRC="$ROOT/prompts/ルミナス_最終プロンプト.md"; OUT="$ROOT/☆ルミナス_最終プロンプト.docx"
  if [ -f "$SRC" ] && { [ ! -f "$OUT" ] || [ "$SRC" -nt "$OUT" ]; }; then
    if command -v node >/dev/null 2>&1; then
      (cd "$ROOT" && node scripts/build-final-prompt-docx.mjs 2>&1) || echo "docx 再生成 失敗（npm install が必要かもしれません）"
    else
      echo "node が無いため docx 再生成をスキップ"
    fi
  else
    echo "docx は最新"
  fi
} >> "$LOG" 2>&1
exit 0
