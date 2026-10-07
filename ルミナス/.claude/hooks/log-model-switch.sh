#!/usr/bin/env bash
# PostModelSwitch: モデル切替を機械記入で escalations.log に追記（理由欄は司令塔が後から書く）。憲章 I-3・I-8
# Codex の実行中は、追跡中（公開）のファイルを書き換えないよう、Codex が書けない置き場（~/.cache/luminous-codex/escalations.pending）に
# 保留し、次の切替か SessionEnd で移す。移すのは機械的な書式の行だけ（モデル名は英数字と記号の一部に限る）
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
FROM="$(hook_model_name "$(hook_json_get "$INPUT" from_model)")"; TO="$(hook_model_name "$(hook_json_get "$INPUT" to_model)")"
LINE="$(printf '%s | (作業名を追記) | %s | %s | (理由を追記) | (結果を追記)' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FROM" "$TO")"
if hook_codex_running; then
  if DIR="$(hook_cache_dir)"; then
    printf '%s\n' "$LINE" >> "$DIR/escalations.pending"
    echo "Codex の実行中のため、モデル切替の記録を保留しました（$FROM → $TO）。終了後に escalations.log へ移ります。"
  else
    echo "警告: 保留の置き場（LUMINOUS_SAFE_DIR）が作業フォルダか /tmp の中にあるため保留できませんでした。Codex の終了後に、次の行を state/escalations.log へ手で追記してください: $LINE"
  fi
  exit 0
fi
hook_flush_escalations
printf '%s\n' "$LINE" >> "$ROOT/state/escalations.log"
echo "escalations.log にモデル切替を記録しました（$FROM → $TO）。作業名・理由を追記してください。"
exit 0
