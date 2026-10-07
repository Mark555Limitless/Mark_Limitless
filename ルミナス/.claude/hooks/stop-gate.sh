#!/usr/bin/env bash
# Stop hook: 「毎回書く」の強制。セッション開始後に今日の digest と state/latest.md が更新されていなければ停止をブロックする。
# ループ防止: stop_hook_active=true（既にこの hook で続行中）なら必ず許可。緊急時は LUMINOUS_STOP_GATE=off で無効化。
set -u
INPUT="$(cat)"
[ "${LUMINOUS_STOP_GATE:-on}" = "off" ] && exit 0
ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)"
[ "$ACTIVE" = "true" ] && exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
MARK="$ROOT/state/.session-start"
[ -f "$MARK" ] || exit 0          # 開始時刻が無ければ判定しない
START="$(cat "$MARK" 2>/dev/null || echo 0)"
TODAY="$(date +%Y-%m-%d)"
DIGEST="$ROOT/digest/$TODAY.md"
LATEST="$ROOT/state/latest.md"
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

MISSING=""
if [ ! -f "$DIGEST" ] || [ "$(mtime "$DIGEST")" -lt "$START" ]; then MISSING="$MISSING digest/$TODAY.md"; fi
if [ ! -f "$LATEST" ] || [ "$(mtime "$LATEST")" -lt "$START" ]; then MISSING="$MISSING state/latest.md"; fi
[ -z "$MISSING" ] && exit 0

jq -n --arg m "$MISSING" '{
  decision: "block",
  reason: ("ルミナス ROUTINE §3: 終了前に次のファイルを今日の内容で更新してください →" + $m + "。digest には やったこと・判断・数値・未解決・次の一手 を、latest.md には直近状態を書く。書き終えたら停止してよい。")
}'
exit 0
