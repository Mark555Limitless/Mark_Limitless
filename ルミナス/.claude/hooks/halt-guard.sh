#!/usr/bin/env bash
# PreToolUse（すべての道具）: 全体停止の印（data/.luminous_halt）があれば、読むだけの道具と「止める・質問」以外を止める。
# JSON を読む前にまず印を見る。印があれば、その後のどの失敗（jq なし・壊れた入力・未定義変数）でも終了 2（止める）。
# 無人実行（FABLE5_HEADLESS=1）でも素通しにしない。timeout は止める側の仕組みとして扱わない（印の確認は settings.json のコマンドの先頭にもある）。
# canary: 印が無くても、先頭が `true luminous-hook-canary` の Bash のコマンドだけは常に断る（hooks が効いているかを司令塔が確かめるため。docs/proposals/20261008-autonomy-grants.md §3.1）
# 仕様: docs/specs/20261008_global_halt.md（B）。差分の案: docs/proposals/20261010-global-halt-part-b.md（Mark 承認 2026-10-10）
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
HALT="$ROOT/data/.luminous_halt"
if [ -e "$HALT" ] || [ -L "$HALT" ]; then
  set +e
  INPUT="$(cat 2>/dev/null)"
  TOOL=""
  if command -v jq >/dev/null 2>&1; then TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
  elif command -v python3 >/dev/null 2>&1; then TOOL="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))' 2>/dev/null)"; fi
  case "$TOOL" in Read|Grep|Glob|TaskStop|KillShell|KillBash|AskUserQuestion) exit 0 ;; esac   # KillShell・KillBash は古い版の「裏の Bash を止める」道具名
  REASON="$(head -n 1 "$HALT" 2>/dev/null | tr -d '\000-\037\177' | cut -c1-600)"
  echo "全体停止中（data/.luminous_halt）: ${REASON:-（理由なし）}。読むだけの道具と TaskStop・AskUserQuestion 以外は使えません。解除は Mark が端末で: bash tools/luminous_halt.sh off" >&2
  exit 2
fi
# 印が無いとき: canary だけ断る
set -u
INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then CMD="$(printf '%s' "$INPUT" | jq -r 'select(.tool_name=="Bash") | .tool_input.command // empty' 2>/dev/null)"
else CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command","") if d.get("tool_name")=="Bash" else "")' 2>/dev/null)"; fi
case "$(printf '%s' "$CMD" | sed -E 's/^[[:space:]]+//')" in "true luminous-hook-canary"*) echo "canary: hooks は効いています（このコマンドは常に断ります）" >&2; exit 2 ;; esac   # 先頭が canary のコマンドだけ（grep などで文字列を含むだけなら通す）
exit 0
