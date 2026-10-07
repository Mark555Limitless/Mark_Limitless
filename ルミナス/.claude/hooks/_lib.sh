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
