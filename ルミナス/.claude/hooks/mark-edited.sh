#!/usr/bin/env bash
# PostToolUse(Edit|Write|NotebookEdit): このセッションで編集があったことを記録（Stop ゲートの edits モード用）
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
mkdir -p "$ROOT/state/.sessions" && : > "$ROOT/state/.sessions/$(hook_session_id "$INPUT").edited"
exit 0
