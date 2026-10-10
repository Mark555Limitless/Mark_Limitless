#!/usr/bin/env bash
# hooks 共通: stdin の JSON から項目を取り出す（jq → python3 の順。どちらも無ければ空）
hook_json_get() {  # $1=JSON文字列 $2=キー（トップレベル）
  if command -v jq >/dev/null 2>&1; then printf '%s' "$1" | jq -r --arg k "$2" '.[$k] // empty' 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then printf '%s' "$1" | python3 -c 'import json,sys; d=json.load(sys.stdin); v=d.get(sys.argv[1],""); print("" if v is None else (str(v).lower() if isinstance(v,bool) else v))' "$2" 2>/dev/null
  fi
}
hook_session_id() {  # 無ければ "nosession"
  local id; id="$(hook_json_get "$1" session_id)"; [ -n "$id" ] && printf '%s' "$id" | tr -c 'A-Za-z0-9_-' '_' || printf 'nosession'
}
hook_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }
# Codex の実行状態（tools/_codex_common.sh と同じロック）。持ち主の PID が生きていれば実行中
hook_codex_owner() { cut -d' ' -f1 "$ROOT/data/codex_runs/.lock/owner" 2>/dev/null; }
hook_codex_running() { local pid; pid="$(hook_codex_owner)"; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }
# 作業フォルダ内の .git を git を使わずに探す（入れ子の .git の設定に仕込まれたコマンドを走らせないため）。
# ROOT/.git は、上位に .git が無い（ROOT がリポジトリの根）ときだけ正当とみなす。見つかったら1件目のパスを出す
hook_nested_git() {
  local d top_ok=1
  d="$(dirname "$ROOT")"
  while :; do
    if [ -e "$d/.git" ] || [ -L "$d/.git" ]; then top_ok=0; break; fi
    [ "$d" = "/" ] && break
    d="$(dirname "$d")"
  done
  # 大文字小文字を区別しない（Mac の既定のファイルシステムでは .GIT も git が .git として読む）
  if [ "$top_ok" = 1 ]; then find "$ROOT" -mindepth 1 -path "$ROOT/.git" -prune -o -iname .git -print 2>/dev/null | head -n 1
  else find "$ROOT" -mindepth 1 -iname .git -print 2>/dev/null | head -n 1; fi
}
# Codex の違反の印かロック（実行中・中断）があるか。あるあいだ hooks は git を使わない
hook_codex_unsettled() { [ -e "$ROOT/data/.codex_violation" ] || [ -d "$ROOT/data/codex_runs/.lock" ]; }
# hooks が使う git。裸のリポジトリとしての発見と fsmonitor を止める（safe.bareRepository は git 2.38 以降。古い git は無視する）
hook_git() { git -c safe.bareRepository=explicit -c core.fsmonitor=false "$@"; }
# Codex が書けない置き場（tools/_codex_common.sh の安全な置き場と同じ。作業フォルダ・/tmp・$TMPDIR の外であることを確かめる）
hook_cache_dir() {
  local base="${LUMINOUS_SAFE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/luminous-codex}" real t tr
  mkdir -p "$base" 2>/dev/null && chmod 700 "$base" 2>/dev/null || return 1
  real="$(cd "$base" 2>/dev/null && pwd -P)" || return 1
  for t in "$ROOT" /tmp /private/tmp /var/tmp "${TMPDIR:-/tmp}"; do
    tr="$(cd "$t" 2>/dev/null && pwd -P)" || continue
    case "$real/" in "$tr"/*) return 1 ;; esac
  done
  printf '%s' "$real"
}
# モデル名は英数字と ._:@?- だけにする（記録は公開されるので、パスや任意の文字列を入れない）
hook_model_name() { printf '%s' "${1:-?}" | tr -c 'A-Za-z0-9._:@?-' '_' | cut -c1-80; }
# log-model-switch.sh が作る機械的な書式の行だけを公開の記録へ移す
ESC_LINE_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z \| \(作業名を追記\) \| [A-Za-z0-9._:@?_-]{1,80} \| [A-Za-z0-9._:@?_-]{1,80} \| \(理由を追記\) \| \(結果を追記\)$'
# Codex の実行中に保留したモデル切替の記録（Codex が書けない置き場）を state/escalations.log へ移す。書式に合わない行は捨てる
hook_flush_escalations() {
  local dir pend total good
  dir="$(hook_cache_dir)" || return 0   # 置き場が安全でなければ、そこにある保留は信用せず移さない
  pend="$dir/escalations.pending"
  [ -s "$pend" ] || return 0
  hook_codex_running && return 0
  total="$(grep -c '' "$pend" 2>/dev/null)"; good="$(grep -cE "$ESC_LINE_RE" "$pend" 2>/dev/null)"   # 一致 0 件でも 0 を出す（終了コードは 1）
  total="${total:-0}"; good="${good:-0}"
  grep -E "$ESC_LINE_RE" "$pend" >> "$ROOT/state/escalations.log"
  rm -f "$pend"
  [ "$total" -gt "$good" ] 2>/dev/null && echo "保留していたモデル切替の記録のうち、書式に合わない $((total - good)) 行を捨てました（中身は表示しない）"
  return 0
}
# 1 行の「データ」の表示用: 表示できる文字（isprintable）だけを残し N 文字で切る（C1 の制御文字・双方向の上書き U+202E も落とす）。python3 が無ければ C0 だけ落とす近似
hook_sanitize_line() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHONIOENCODING=utf-8 python3 -c 'import sys; n=int(sys.argv[1]); s=sys.stdin.buffer.read().decode("utf-8","replace").replace("\n"," "); print("".join(c for c in s if c.isprintable())[:n])' "$1"
  else tr -d '\000-\037\177' | tr '\n' ' ' | head -c $(( $1 * 3 )); echo; fi
}
# 文字単位で各行を N 文字に切る（cut -c は C ロケールでバイト単位になり、日本語を壊すため使わない）
hook_trunc() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHONIOENCODING=utf-8 python3 -c 'import sys
n=int(sys.argv[1])
for l in sys.stdin.buffer:
    t=l.decode("utf-8","replace").rstrip("\n")
    print(t[:n])' "$1"
  else
    cat
  fi
}
