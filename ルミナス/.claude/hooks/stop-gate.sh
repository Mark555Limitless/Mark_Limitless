#!/usr/bin/env bash
# Stop hook: 「毎回書く」の強制。このセッションの開始後に 今日の digest・HANDOVER.md・obsidian/ルミナス.md が更新されていなければ終了をブロック。
# - 無人実行（FABLE5_HEADLESS=1）では止めない（無人の便は自分の記録手順で書く）
# - stop_hook_active=true（既に続行中）なら必ず許可（ループ防止。Claude Code 側にも連続上限あり）
# - 開始時刻はセッション別（state/.sessions/<id>.start）。日付は LUMINOUS_TZ（既定 Asia/Tokyo）
# - LUMINOUS_GATE_MODE=edits なら、このセッションでファイル編集が無かった場合は許可（既定 always）
# - LUMINOUS_STOP_GATE=off は、今日の digest に「STOP_GATE=off」と理由が書かれている場合だけ有効
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
command -v jq >/dev/null 2>&1 || hook_py_ok || true   # jq が無いときは python3 が動くかを親で 1 回だけ確かめる（$( ) の中の解析に引き継ぐ）
INPUT="$(cat)"
[ "$(hook_json_get "$INPUT" stop_hook_active)" = "true" ] && exit 0
# jq も動く python3 も無くてもループ防止を効かせる（文字列の値の中では " が \" に逃がされるので、本文に同じ文字を書かれても一致しない）
case "$INPUT" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0 ;; esac
[ "${FABLE5_HEADLESS:-0}" = "1" ] && exit 0
# 止める JSON を出す（jq → 動く python3 → printf の順。printf では \ と " を逃がし、制御文字は空白にする。どれでも stdout の JSON で止める）
block_json() {
  if command -v jq >/dev/null 2>&1 && jq -n --arg r "$1" '{decision:"block", reason:$r}' 2>/dev/null; then return 0; fi
  if hook_py_ok && printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.stdin.buffer.read().decode("utf-8","replace")}))' 2>/dev/null; then return 0; fi
  printf '{"decision":"block","reason":"%s"}\n' "$(printf '%s' "$1" | tr '\000-\037' ' ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
}
{ [ -e "$ROOT/data/.luminous_halt" ] || [ -L "$ROOT/data/.luminous_halt" ]; } && exit 0   # 全体停止中は終了を止めない（閉じ込めない。docs/specs/20261008_global_halt.md）
SID="$(hook_session_id "$INPUT")"
MARK="$ROOT/state/.sessions/$SID.start"
[ -f "$MARK" ] || exit 0
START="$(cat "$MARK" 2>/dev/null)"
# 開始時刻は数字で、未来でないこと。そうでなければ印のファイル自体の更新時刻を使う（書き換えでゲートを外させない）
case "$START" in ''|*[!0-9]*) START="$(hook_mtime "$MARK")" ;; esac
[ "$START" -gt "$(date +%s)" ] 2>/dev/null && START="$(hook_mtime "$MARK")"
TODAY="$(TZ="${LUMINOUS_TZ:-Asia/Tokyo}" date +%Y-%m-%d)"
DIGEST="$ROOT/digest/$TODAY.md"

if [ "${LUMINOUS_STOP_GATE:-on}" = "off" ]; then
  if [ -f "$DIGEST" ] && grep -q 'STOP_GATE=off' "$DIGEST"; then exit 0; fi
  block_json "Stop ゲートを解除するには、digest/$TODAY.md に「STOP_GATE=off: 理由」を書いてください（ROUTINE §5）。"
  exit 0
fi
if [ "${LUMINOUS_GATE_MODE:-always}" = "edits" ] && [ ! -f "$ROOT/state/.sessions/$SID.edited" ]; then exit 0; fi

MISSING=""
check() { # $1=相対パス $2=最低行数
  local f="$ROOT/$1"
  if [ ! -f "$f" ] || [ "$(hook_mtime "$f")" -lt "$START" ] || [ "$(wc -l < "$f")" -lt "$2" ]; then MISSING="$MISSING $1"; fi
}
check "digest/$TODAY.md" 5
check "HANDOVER.md" 5
check "obsidian/ルミナス.md" 5
[ -z "$MISSING" ] && exit 0
REASON="ルミナス ROUTINE §3: 終了前に次を今日の内容で更新してください →$MISSING 。digest には やったこと・判断・数値（実測）・未解決・次の一手、HANDOVER.md には先頭に新しい節（状態・決定・未解決・次の一手）、obsidian/ルミナス.md には「最新」節の 1 行。書き終えたら停止してよい。"
block_json "$REASON"
exit 0
