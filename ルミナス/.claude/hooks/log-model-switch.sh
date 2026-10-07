#!/usr/bin/env bash
# PostModelSwitch: モデル切替を機械記入で escalations.log に追記（理由欄は司令塔が後から書く）。憲章 I-3・I-8
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
FROM="$(hook_json_get "$INPUT" from_model)"; TO="$(hook_json_get "$INPUT" to_model)"
printf '%s | (作業名を追記) | %s | %s | (理由を追記) | (結果を追記)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${FROM:-?}" "${TO:-?}" >> "$ROOT/state/escalations.log"
echo "escalations.log にモデル切替を記録しました（${FROM:-?} → ${TO:-?}）。作業名・理由を追記してください。"
exit 0
