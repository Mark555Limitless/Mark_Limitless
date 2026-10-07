#!/usr/bin/env bash
# PreToolUse(Bash) hook: 鍵・トークンらしき文字列を含むコミットを止める（憲章 I-4）。
# 対象: コマンドに `git commit` を含むとき、ステージ済み差分の追加行を検査する。
# 見つかれば exit 2（ブロック）。それ以外は exit 0（通常の許可フローへ）。
set -u
INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -z "$CMD" ] && exit 0
case "$CMD" in
  *"git commit"*|*"git -C "*"commit"*) ;;
  *) exit 0 ;;
esac

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
DIFF="$(git -C "$ROOT" diff --cached -U0 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+' || true)"
[ -z "$DIFF" ] && exit 0

# 代表的な鍵の形式（接頭辞）と、「API Key=」「password=」のような明示的な代入
PATTERN='(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{10,}|xai-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_ -]?key|secret|token|password|passwd)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_\-]{12,})'
HITS="$(printf '%s\n' "$DIFF" | grep -nEi "$PATTERN" | head -5 || true)"
if [ -n "$HITS" ]; then
  {
    echo "ブロック: ステージ済み差分に鍵・トークンらしき文字列があります（憲章 I-4）。該当行を除去してから再度コミットしてください。"
    # 値そのものを再出力しないため、該当部分を [REDACTED] に置き換えて示す
    printf '%s\n' "$HITS" | sed -E "s#$PATTERN#[REDACTED]#Ig" | cut -c1-120 | sed 's/^/  /'
  } >&2
  exit 2
fi
exit 0
