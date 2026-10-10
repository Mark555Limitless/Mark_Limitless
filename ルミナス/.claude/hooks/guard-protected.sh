#!/usr/bin/env bash
# PreToolUse(Bash) hook: 保護ファイル（憲章・権限・hooks・最終プロンプト・hooks が呼ぶ scripts など）への Bash 経由の書き込みと、
# 鍵ファイルの Bash 経由の読み取り、git フックの迂回を止める（憲章 §4・I-4）。
# 理由: permissions の Edit(...) ルールは Edit ツールとリダイレクト(>, >>, tee)には効くが、sed -i・mv・cp・python 等の書き込みには効かない。
# 保護ファイルを変えたいときは Edit ツールを使う（確認ダイアログが出て Mark が見られる）。パターン判定なので回避は可能。事後検知は SessionStart の差分警告。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
INPUT="$(cat)"
# CMD は必ず先に空で定義する（set -u のもとで未定義のまま使うと exit 1 になり、止める扱いにならず素通りする）
CMD=""; PARSED=0
if command -v jq >/dev/null 2>&1; then
  TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
  [ -n "$TOOL" ] && [ "$TOOL" != "Bash" ] && exit 0
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" && PARSED=1
elif hook_py_ok; then   # python3 の起動は 1 回にまとめる（tool_name が無い・空なら Bash とみなす。名前は NFC にそろえる）
  CMD="$(printf '%s' "$INPUT" | PYTHONIOENCODING=utf-8 python3 -c 'import json,sys,unicodedata
d=json.load(sys.stdin); t=d.get("tool_name") or "Bash"; c=d.get("tool_input",{}).get("command","") if t=="Bash" else ""
print(unicodedata.normalize("NFC", c) if isinstance(c,str) else c)' 2>/dev/null)" && PARSED=1
fi
# jq も動く python3 も無い（Mac で CLT が無いと /usr/bin/python3 は exit 1 で終わる）か、JSON を読めないときは、
# 素通しにせず生の JSON 全体を検査する（広く当たる＝止める側）。文字列の区切りの " は空白に、エスケープの \t は語の区切り（空白）に、
# \n \r は命令の区切り「; 」にして、語の境目と 2 行目以降の命令も拾う（\t を「; 」にすると rm<TAB>CLAUDE.md が rm[[:space:]] に当たらず素通りする）（先頭が { なので、全体停止の on・status の素通し HALT_OK にも乗らない）。
# ただし会話記録の場所（transcript_path は ~/.claude/projects/… で .claude/ を含む）と cwd は命令ではないので外す
# （命令の文字列の中の " は \" に逃がされているので、命令の中に同じ形を書いても外れない）
if [ "$PARSED" = 0 ]; then CMD="$(printf '%s' "$INPUT" | tr '\n\r' '  ' | sed -E 's/"(transcript_path|cwd)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"//g' | sed -e 's/\\t/ /g' -e 's/\\[nr]/; /g' -e 's/"/ /g')"; fi
[ -z "$CMD" ] && exit 0
# Mac（APFS）では名前の「プ」が NFD（フ＋U+309A）のこともあり、どちらの形でも同じファイルを開く。
# 動く python3 があれば NFC にそろえてから調べる（python3 で読んだときは読むときにそろえ済み）。無くても合うよう PROT に NFD の形も入れる
case "$CMD" in *[![:ascii:]]*)
  if [ "$PARSED" = 1 ] && command -v jq >/dev/null 2>&1 && hook_py_ok; then
    N_="$(printf '%s' "$CMD" | python3 -c 'import sys,unicodedata; sys.stdout.buffer.write(unicodedata.normalize("NFC", sys.stdin.buffer.read().decode("utf-8","surrogateescape")).encode("utf-8","surrogateescape"))' 2>/dev/null)" && [ -n "$N_" ] && CMD="$N_"
  fi ;;
esac
deny() { echo "ブロック（guard-protected）: $1" >&2; exit 2; }

NFD_PU="$(printf '\343\203\225\343\202\232')"   # 「プ」の NFD（フ＋U+309A）。バイト列で組み立てる
PROT='(CHARTER\.md|\.env\.example|VIRTUAL_MARK\.md|ROUTINE\.md|CLAUDE\.md|AGENTS\.md|最終(プ|'"$NFD_PU"')ロン(プ|'"$NFD_PU"')ト|\.claude/|\.codex/|\.githooks/|\.mcp\.json|secret-scan\.sh|sync-obsidian\.sh|build-final-prompt-docx\.mjs|package(-lock)?\.json|luminous_halt)'
WRITE='(sed[^|;&]*[[:space:]]-i|perl[^|;&]*[[:space:]]-i|>>?|[[:space:]]tee[[:space:]]|(^|[[:space:];&|(`])(mv|cp|rm|truncate|chmod|chown|ln|install|rsync|dd|unlink|patch)[[:space:]]|git[[:space:]]+(checkout|restore|reset|mv|rm|apply|am|stash)[[:space:]]|(python3?|node|ruby|perl|php)[[:space:]]+-([^m]|$)|write_text|writeFile|open\([^)]*["'"'"'][wa])'
SECRET='((^|[^A-Za-z0-9_])\.env(rc)?(\.[A-Za-z0-9_.-]+)?([^A-Za-z0-9_.-]|$)|settings\.local\.json|_非公開|env_backups|\.pem([[:space:]"'"'"']|$)|\.p8([[:space:]"'"'"']|$)|\.p12([[:space:]"'"'"']|$)|id_rsa|id_ed25519|\.netrc|credentials\.json)'
READ='(^|[[:space:];&|(`])(cat|less|more|head|tail|grep|rg|awk|sed|cp|scp|curl|base64|xxd|od|strings|source|python3?|node|jq|bat|nl|diff|pbcopy|open|hexdump|ditto|cut|sort|tr|perl)[[:space:]]'
# 名前の一致は大文字小文字を区別しない（Mac の APFS は既定で区別せず、.ENV・claude.md・.Claude/ も同じファイルを開く。git の設定のキーも区別しない）。
# 緩める側（.env.example の除去・HALT_OK）は区別したまま。WRITE は -([^m]|$) が -i で -M も外すので、区別あり・なしのどちらかに当たれば止める

# 1) git フックの迂回（--no-verify、core.hooksPath の変更）
printf '%s' "$CMD" | grep -qiE '(^|[[:space:]])--no-verify([[:space:]]|$)|git[[:space:]]+commit[^|;&]*[[:space:]]-[A-Za-z]*n[A-Za-z]*([[:space:]]|$)|core\.hooksPath' \
  && deny "git フックの迂回（--no-verify / core.hooksPath の変更）は Mark 本人が行う操作です（憲章 §4）。"
# 2) 鍵ファイルの Bash 経由の読み取り（permissions の Read 拒否は Bash に効かないため）
# .env.example だけは読んでよい（変数名だけで値が無い）。それ以外の .env 系・非公開フォルダ・鍵ファイルは Bash で読ませない
CMD_S="$(printf '%s' "$CMD" | sed 's/\.env\.example//g')"
printf '%s' "$CMD_S" | grep -qiE "$SECRET" && printf '%s' "$CMD_S" | grep -qiE "$READ" \
  && deny "鍵・資格情報らしきファイルを Bash で読もうとしています（憲章 I-4）。必要なら Mark 本人が扱います。"
# 3) 保護ファイルへの Bash 経由の書き込み（heredoc 本文の誤検知を避けるため、先頭行と各区切りの後だけを見る）
# 全体停止の on・status は誰でも打ってよい（印そのものは保護するが、付ける・見る操作は止めない。docs/specs/20261008_global_halt.md）。
# 1 行だけで、先頭が（cd … && ）bash tools/luminous_halt.sh on|status で、後ろに ; | & がつながっていなければ通す（fd の複製 2>&1 は無視）
HALT_OK='^[[:space:]]*(cd[[:space:]]+[^;|&<>$`]+&&[[:space:]]*)?(bash[[:space:]]+)?(\./)?tools/luminous_halt\.sh[[:space:]]+(on|status)([[:space:]][^;|&<>$`]*)?$'   # 理由に $( ) ` < > は不可（シェルが実行・リダイレクトするため）
case "$CMD" in *$'\n'*) ;; *) printf '%s' "$CMD" | sed -E 's/[0-9]*>&[0-9]+//g' | grep -qE "$HALT_OK" && exit 0 ;; esac   # 複数行なら素通しにしない（2 行目に別の命令が書ける）
HEAD_PART="$(printf '%s' "$CMD" | awk 'NR==1{print; next} tolower($0) ~ /^[[:space:]]*(cd|git|sed|perl|mv|cp|rm|tee|cat|python3?|node|echo|printf|chmod|ln|truncate)[[:space:]]/{print}' | sed -E 's/[0-9]*>&[0-9]+//g')"
if printf '%s' "$HEAD_PART" | grep -qiE "$PROT" && { printf '%s' "$HEAD_PART" | grep -qE "$WRITE" || printf '%s' "$HEAD_PART" | grep -qiE "$WRITE"; }; then
  deny "保護ファイル（憲章・権限・hooks・最終プロンプト・hooks が呼ぶ scripts）を Bash で書き換えようとしています。Edit ツールを使い、Mark の確認を通してください（憲章 §4）。"
fi
exit 0
