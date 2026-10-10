#!/usr/bin/env bash
# PreToolUse(Edit|Write|NotebookEdit): Codex（tools/codex_impl.sh・codex_opinion.sh）の実行中は、このフォルダ内のファイル編集を止める。
# 理由: 実行中の編集は Codex の差分と混ざり、範囲検査（scope_check）が違反（3）と判定する。HANDOVER・digest などの記録も Codex の終了後に書く。
# ロック（data/codex_runs/.lock）の持ち主が生きているときだけ止める。フォルダの外（scratchpad 等）への書き込みは止めない。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
hook_codex_running || exit 0
FP=""; PARSED=0
if command -v jq >/dev/null 2>&1; then
  FP="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)" && PARSED=1
elif hook_py_ok; then   # Mac の /usr/bin/python3 は「有るが動かない」ことがある（CLT が無い・壊れている）
  FP="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
d=json.load(sys.stdin).get("tool_input") or {}
print(d.get("file_path") or d.get("notebook_path") or "")' 2>/dev/null)" && PARSED=1
fi
if [ "$PARSED" = 0 ]; then   # 編集先を確かめられないときは止める側に倒す（ここに来るのは Codex の実行中だけ）
  echo "ブロック（codex-lock-guard）: Codex が実行中（PID $(hook_codex_owner)）で、jq も動く python3 も無い（または入力を読めない）ため編集先を確かめられません。Codex の終了後に編集してください。" >&2
  exit 2
fi
[ -n "$FP" ] || exit 0
case "$FP" in /*) ;; *) FP="$PWD/$FP" ;; esac
# まだ無いファイルもあるので、存在する親ディレクトリまでさかのぼって実体パスにする
D="$(dirname "$FP")"
while [ ! -d "$D" ] && [ "$D" != "/" ]; do D="$(dirname "$D")"; done
RD="$(cd "$D" 2>/dev/null && pwd -P)" || exit 0
RR="$(cd "$ROOT" && pwd -P)"
case "$RD/" in
  "$RR"/*)
    echo "ブロック（codex-lock-guard）: Codex が実行中です（PID $(hook_codex_owner)）。終わるまでこのフォルダのファイルを編集しないでください（実行中の編集は範囲検査で違反になります）。記録は終了後に書く。" >&2
    exit 2 ;;
esac
exit 0
