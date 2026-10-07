# Codex ラッパー共通（source して使う）。PROJ はこのフォルダ（ルミナス）の絶対パスを実行時に求める（公開リポジトリにローカルパスを書かないため）。
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJ_REAL="$(cd "$PROJ" && pwd -P)"

# .env から CODEX_* と ORCH_CODEX だけを読む（source しない。鍵の行は読まない）。環境に既にあればそちらを優先する
_dotenv_var() {
  local name="$1" line v
  [ -n "${!name+x}" ] && return 0
  [ -f "$PROJ/.env" ] || return 0
  line="$(grep -E "^[[:space:]]*${name}[[:space:]]*=" "$PROJ/.env" 2>/dev/null | tail -n 1)"
  [ -n "$line" ] || return 0
  v="${line#*=}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf -v "$name" '%s' "$v"; export "$name"
}
for _n in CODEX_BIN CODEX_OLD_BIN CODEX_MODEL CODEX_FALLBACK_MODEL CODEX_DISABLE_FEATURES ORCH_CODEX; do _dotenv_var "$_n"; done
unset _n
: "${CODEX_FALLBACK_MODEL=gpt-5.6-sol}"   # 分譲指示書の既定（空文字を明示すればやり直しをしない）
: "${CODEX_DISABLE_FEATURES=memories multi_agent}"

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
# 作業領域の外にある python3（Codex が書き換えられない）。-I -S で実行する
safe_python() {
  local c r
  for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    r="$(cd "$(dirname "$c")" && pwd -P)/$(basename "$c")"
    case "$r/" in "$PROJ_REAL"/*) continue;; esac
    printf '%s\n' "$c"; return 0
  done
  return 1
}
# Codex が書けない場所（作業フォルダ・/tmp・$TMPDIR の外）に、実行ごとの安全な置き場を作る
make_safe_dir() {
  local base="${LUMINOUS_SAFE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/luminous-codex}" real t tr
  mkdir -p "$base" 2>/dev/null && chmod 700 "$base" || return 1
  real="$(cd "$base" && pwd -P)"
  for t in "$PROJ_REAL" /tmp /private/tmp /var/tmp "${TMPDIR:-/tmp}"; do
    tr="$(cd "$t" 2>/dev/null && pwd -P)" || continue
    case "$real/" in "$tr"/*) echo "安全な置き場 $real が Codex の書ける場所の中です（LUMINOUS_SAFE_DIR で変える）" >&2; return 1;; esac
  done
  mktemp -d "$real/run.XXXXXX"
}
remove_safe_dir() { case "$1" in */luminous-codex*/run.*|*/run.??????) rm -rf -- "$1";; esac; }

# 同時に2本以上走らせない（ディレクトリ作成は原子的）。持ち主のプロセスが死んでいれば回収する
LOCK_DIR="$PROJ/data/codex_runs/.lock"
acquire_lock() {
  mkdir -p "$PROJ/data/codex_runs"
  if mkdir "$LOCK_DIR" 2>/dev/null; then printf '%s %s\n' "$$" "$(date +%s)" > "$LOCK_DIR/owner"; return 0; fi
  local pid; pid="$(cut -d' ' -f1 "$LOCK_DIR/owner" 2>/dev/null)"
  if { [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; } || [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    echo "古いロックを回収します（持ち主 ${pid:-不明} は動いていません）" >&2
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" 2>/dev/null && { printf '%s %s\n' "$$" "$(date +%s)" > "$LOCK_DIR/owner"; return 0; }
  fi
  return 1
}
release_lock() { [ "$(cut -d' ' -f1 "$LOCK_DIR/owner" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK_DIR"; return 0; }
now_ms() { local s; s="$(date +%s%N 2>/dev/null)"; case "$s" in *N|'') echo $(( $(date +%s) * 1000 ));; *) echo $(( s / 1000000 ));; esac; }
