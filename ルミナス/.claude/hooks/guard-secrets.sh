#!/usr/bin/env bash
# PreToolUse(Bash) hook: git commit / git push を含むコマンドの前に、作業ツリー＋未追跡ファイル＋HEAD との差分を検査する（憲章 I-4）。
# PreToolUse は `git add` の前に走るので「ステージ済み差分」だけでは不足。ここは早期警告で、本命は .githooks/pre-commit と pre-push（scripts/setup.sh で有効化）。
# 検知したら exit 2（ブロック）。jq が無ければ python3 で解析、両方無ければ git 系コマンドのときだけ安全側（exit 2）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)"
elif command -v python3 >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"
else
  case "$INPUT" in *git*commit*|*git*push*) echo "guard-secrets: jq も python3 も無く検査できないため、git commit/push を止めました。" >&2; exit 2;; esac
  exit 0
fi
[ -z "$CMD" ] && exit 0
# 空白の揺れを畳んでから判定（`git  commit`、`git -c k=v commit`、`git --no-pager commit` も拾う）
NORM="$(printf '%s' "$CMD" | tr -s '[:space:]' ' ')"
printf '%s' "$NORM" | grep -qE '(^|[;&| ])git( -[A-Za-z-]+( [^ ]+)?)* (commit|push)( |$)' || exit 0

SCAN="$ROOT/scripts/secret-scan.sh"
[ -x "$SCAN" ] || { echo "guard-secrets: $SCAN が無いため検査できません。" >&2; exit 2; }
{
  git -C "$ROOT" diff HEAD -U0 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+'
  git -C "$ROOT" diff --cached -U0 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+'
  git -C "$ROOT" ls-files --others --exclude-standard -z 2>/dev/null | while IFS= read -r -d '' f; do
    case "$f" in *.docx|*.png|*.jpg|*.jpeg|*.webp|*.pdf) continue;; esac
    [ -f "$ROOT/$f" ] && [ "$(wc -c < "$ROOT/$f")" -lt 2000000 ] && cat "$ROOT/$f"
  done
} | bash "$SCAN" && exit 0
echo "ブロック: 作業ツリー・ステージ・未追跡ファイルに鍵・トークンらしき文字列があります（憲章 I-4）。上の該当行を除去してから再実行してください。" >&2
exit 2
