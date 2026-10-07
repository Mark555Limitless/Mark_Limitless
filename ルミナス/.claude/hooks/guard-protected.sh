#!/usr/bin/env bash
# PreToolUse(Bash) hook: 保護ファイル（憲章・権限・hooks・最終プロンプト・hooks が呼ぶ scripts など）への Bash 経由の書き込みと、
# 鍵ファイルの Bash 経由の読み取り、git フックの迂回を止める（憲章 §4・I-4）。
# 理由: permissions の Edit(...) ルールは Edit ツールとリダイレクト(>, >>, tee)には効くが、sed -i・mv・cp・python 等の書き込みには効かない。
# 保護ファイルを変えたいときは Edit ツールを使う（確認ダイアログが出て Mark が見られる）。パターン判定なので回避は可能。事後検知は SessionStart の差分警告。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
TOOL="$(hook_json_get "$INPUT" tool_name)"
[ -n "$TOOL" ] && [ "$TOOL" != "Bash" ] && exit 0
if command -v jq >/dev/null 2>&1; then CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
else CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"; fi
[ -z "$CMD" ] && exit 0
deny() { echo "ブロック（guard-protected）: $1" >&2; exit 2; }

PROT='(CHARTER\.md|\.env\.example|VIRTUAL_MARK\.md|ROUTINE\.md|CLAUDE\.md|AGENTS\.md|最終プロンプト|\.claude/|\.codex/|\.githooks/|\.mcp\.json|secret-scan\.sh|sync-obsidian\.sh|build-final-prompt-docx\.mjs|package(-lock)?\.json)'
WRITE='(sed[^|;&]*[[:space:]]-i|perl[^|;&]*[[:space:]]-i|>>?|[[:space:]]tee[[:space:]]|(^|[[:space:];&|(])(mv|cp|rm|truncate|chmod|chown|ln|install|rsync|dd|unlink|patch)[[:space:]]|git[[:space:]]+(checkout|restore|reset|mv|rm|apply|am|stash)[[:space:]]|(python3?|node|ruby|perl|php)[[:space:]]+(-c|-e|-)|write_text|writeFile|open\([^)]*["'"'"'][wa])'
SECRET='(\.env([[:space:]"'"'"';|&)]|$)|\.env\.(local|prod|production|dev|bak)|settings\.local\.json|\.pem([[:space:]"'"'"']|$)|\.p8([[:space:]"'"'"']|$)|\.p12([[:space:]"'"'"']|$)|id_rsa|id_ed25519|\.netrc|credentials\.json)'
READ='(^|[[:space:];&|(])(cat|less|more|head|tail|grep|rg|awk|sed|cp|scp|curl|base64|xxd|od|strings|source|python3?|node|jq|bat|nl|diff)[[:space:]]'

# 1) git フックの迂回（--no-verify、core.hooksPath の変更）
printf '%s' "$CMD" | grep -qE '(^|[[:space:]])--no-verify([[:space:]]|$)|git[[:space:]]+commit[^|;&]*[[:space:]]-[A-Za-z]*n[A-Za-z]*([[:space:]]|$)|core\.hooksPath' \
  && deny "git フックの迂回（--no-verify / core.hooksPath の変更）は Mark 本人が行う操作です（憲章 §4）。"
# 2) 鍵ファイルの Bash 経由の読み取り（permissions の Read 拒否は Bash に効かないため）
printf '%s' "$CMD" | grep -qE "$SECRET" && printf '%s' "$CMD" | grep -qE "$READ" \
  && deny "鍵・資格情報らしきファイルを Bash で読もうとしています（憲章 I-4）。必要なら Mark 本人が扱います。"
# 3) 保護ファイルへの Bash 経由の書き込み（heredoc 本文の誤検知を避けるため、先頭行と各区切りの後だけを見る）
HEAD_PART="$(printf '%s' "$CMD" | awk 'NR==1{print; next} /^[[:space:]]*(cd|git|sed|perl|mv|cp|rm|tee|cat|python3?|node|echo|printf|chmod|ln|truncate)[[:space:]]/{print}')"
if printf '%s' "$HEAD_PART" | grep -qE "$PROT" && printf '%s' "$HEAD_PART" | grep -qE "$WRITE"; then
  deny "保護ファイル（憲章・権限・hooks・最終プロンプト・hooks が呼ぶ scripts）を Bash で書き換えようとしています。Edit ツールを使い、Mark の確認を通してください（憲章 §4）。"
fi
exit 0
