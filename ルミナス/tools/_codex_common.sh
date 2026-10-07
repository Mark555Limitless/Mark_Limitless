# Codex ラッパー共通（source して使う）。PROJ はこのフォルダ（ルミナス）の絶対パスを実行時に求める（公開リポジトリにローカルパスを書かないため）。
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$PROJ/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
# 本体: CODEX_BIN → ChatGPT アプリ同梱（2026-10-06 以降の場所）→ 古い場所（CODEX_OLD_BIN）→ PATH
find_codex() {
  local c
  for c in "${CODEX_BIN:-}" "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex" "${CODEX_OLD_BIN:-}"; do
    [ -n "$c" ] && [ -x "$c" ] && { printf '%s\n' "$c"; return 0; }
  done
  command -v codex 2>/dev/null
}
codex_disabled() {
  case "${ORCH_CODEX:-1}" in 0|false|off|no) return 0;; esac
  [ -e "$PROJ/data/.codex_disabled" ]
}
# 同時に2本以上走らせない（ディレクトリ作成は原子的）
acquire_lock() {
  mkdir -p "$PROJ/data/codex_runs"
  if mkdir "$PROJ/data/codex_runs/.lock" 2>/dev/null; then
    printf '%s %s\n' "$$" "$(date +%s)" > "$PROJ/data/codex_runs/.lock/owner"; return 0
  fi
  return 1
}
release_lock() { rm -rf "$PROJ/data/codex_runs/.lock"; }
ledger() { # $1=status $2=ms $3=model $4=purpose
  (cd "$PROJ" && "$PY" -m orch.usage record --vendor codex --status "$1" --ms "$2" --model "$3" --purpose "$4") >/dev/null 2>&1 || true
}
now_ms() { "$PY" -c 'import time; print(int(time.time()*1000))'; }
