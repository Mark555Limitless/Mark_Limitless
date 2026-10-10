# Codex ラッパー共通（source して使う）。PROJ はこのフォルダ（ルミナス）の絶対パスを実行時に求める（公開リポジトリにローカルパスを書かないため）。
unset CDPATH   # 端末で export された CDPATH で、cd が別の場所へ行く・パスを標準出力に出す（PROJ が 2 行になる）のを防ぐ。子プロセスにも渡さない
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

# 本体: CODEX_BIN → ChatGPT アプリ同梱（2026-10-06 以降の場所。/Applications、次に ~/Applications）→ 古い場所（CODEX_OLD_BIN）→ PATH
APP_CODEX_REL="Contents/Resources/codex-cli/bin/codex"
find_codex() {
  local c
  for c in "${CODEX_BIN:-}" "/Applications/ChatGPT.app/$APP_CODEX_REL" "${HOME:+$HOME/Applications/ChatGPT.app/$APP_CODEX_REL}" "${CODEX_OLD_BIN:-}"; do
    [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ] && { printf '%s\n' "$c"; return 0; }
  done
  command -v codex 2>/dev/null
}
# 見つからないときの案内（ホームは展開せず ~ のまま出す。ログにローカルパスを残さないため）
codex_where() { echo "  探した場所: CODEX_BIN（.env）→ /Applications/ChatGPT.app/$APP_CODEX_REL → ~/Applications/ChatGPT.app/… → CODEX_OLD_BIN → PATH。.env に CODEX_BIN=<codex の絶対パス> を書けば指定できます" >&2; }
codex_disabled() {
  case "${ORCH_CODEX:-1}" in 0|false|off|no) return 0;; esac
  if [ -e "$PROJ/data/.luminous_halt" ] || [ -L "$PROJ/data/.luminous_halt" ]; then return 0; fi   # 全体停止（docs/specs/20261008_global_halt.md）
  [ -e "$PROJ/data/.codex_disabled" ]
}
# 作業領域の外にある python3（Codex が書き換えられない）。-I -S で実行する
# 実際に -I -S で起動できるものだけを選ぶ（Mac の /usr/bin/python3 は、コマンドラインツールが無い・壊れていると
# 何もせずに失敗するスタブ）。試しの起動は、作業領域の外と確かめた後に行う（作業領域の中の python3 を動かさないため）
safe_python() {
  local c r
  for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3 2>/dev/null)"; do
    [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ] || continue
    r="$(cd "$(dirname "$c")" && pwd -P)/$(basename "$c")"
    case "$r/" in "$PROJ_REAL"/*) continue;; esac
    "$c" -I -S -c pass </dev/null >/dev/null 2>&1 || continue
    printf '%s\n' "$c"; return 0
  done
  return 1
}
# Codex が書けない場所（作業フォルダ・/tmp・$TMPDIR の外）に、実行ごとの安全な置き場を作る
make_safe_dir() {
  local base="${LUMINOUS_SAFE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/luminous-codex}" real t tr
  mkdir -p "$base" 2>/dev/null && chmod 700 "$base" 2>/dev/null \
    || { echo "安全な置き場 $base を作れません（書き込み権限・同名のファイル・sandbox を確かめる。LUMINOUS_SAFE_DIR で変える）" >&2; return 1; }
  real="$(cd "$base" && pwd -P)"
  for t in "$PROJ_REAL" /tmp /private/tmp /var/tmp "${TMPDIR:-/tmp}"; do
    tr="$(cd "$t" 2>/dev/null && pwd -P)" || continue
    case "$real/" in "$tr"/*) echo "安全な置き場 $real が Codex の書ける場所の中です（LUMINOUS_SAFE_DIR で変える）" >&2; return 1;; esac
  done
  # 強制終了（SIGKILL 等）で残った古い置き場（1日以上前）を片付ける
  find "$real" -maxdepth 1 -name 'run.??????' -type d -mmin +1440 -exec rm -rf {} + 2>/dev/null
  mktemp -d "$real/run.XXXXXX"
}
remove_safe_dir() { case "$1" in */luminous-codex*/run.*|*/run.??????) rm -rf -- "$1";; esac; }

# 同時に2本以上走らせない（ディレクトリ作成は原子的）。持ち主のプロセスが死んでいるか、PID が別のプロセスに使い回されて
# いると確かめられたときだけ回収する（時間では回収しない。長い実行のロックを奪うと2本が同時に走るため）。持ち主の記録が無いロックも回収しない
LOCK_DIR="$PROJ/data/codex_runs/.lock"
_write_owner() { printf '%s %s\n' "$$" "$(date +%s)" > "$LOCK_DIR/owner"; }
lock_owner() { cut -d' ' -f1 "$LOCK_DIR/owner" 2>/dev/null; }
lock_owner_ts() { cut -s -d' ' -f2 "$LOCK_DIR/owner" 2>/dev/null; }   # 区切りの無い行は空（PID を時刻と取り違えない）
# ps の etime（[[dd-]hh:]mm:ss）→ 秒。形が違えば失敗する（0 秒とはみなさない）
_etime_secs() {
  local e="$1" d=0 h=0 m s IFS=:
  case "$e" in *-*) d="${e%%-*}"; e="${e#*-}";; esac
  case "$d" in ''|*[!0-9]*) return 1;; esac
  case "$e" in ''|*[!0-9:]*|:*|*:|*::*) return 1;; esac
  set -- $e
  case $# in 2) m="$1"; s="$2";; 3) h="$1"; m="$2"; s="$3";; *) return 1;; esac
  echo $(( 10#$d * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s ))
}
# 持ち主の PID が今もロックの持ち主か（0=生きている・分からない / 1=死んでいるか、使い回された PID）。
# ラッパーは起動の後に持ち主の記録（PID と時刻）を書くので、その PID のプロセスの開始が記録の時刻より後なら、
# 別のプロセスが PID を使い回している（luminous_halt.sh の term_codex と同じ考え方）。開始が記録より前の側は判定に使わない
# （その PID を記録の時点で持っていたのは書いた本人なので、使い回しではない）。時計のずれに 60 秒の余裕を取る。
# 記録の時刻が無い・2001 年より前・ps の結果を読めないときは、時刻では判定せず「生きている」とみなす（ロックを奪わない側）
lock_owner_alive() {  # $1=PID $2=記録の時刻
  local et secs now
  kill -0 "$1" 2>/dev/null || return 1
  case "${2:-}" in ''|*[!0-9]*) return 0;; esac
  [ "$2" -ge 1000000000 ] 2>/dev/null || return 0
  now="$(date +%s)"   # ps より先に取る: 求めた開始時刻は早い側にしかずれない（生きているロックを奪わない側）
  et="$(ps -o etime= -p "$1" 2>/dev/null | tr -d ' ')"
  secs="$(_etime_secs "$et")" || return 0
  [ $(( now - secs )) -gt $(( 10#$2 + 60 )) ] && return 1   # 10#: 先頭が 0 の記録を 8 進数として読まない
  return 0
}
acquire_lock() {
  mkdir -p "$PROJ/data/codex_runs"
  if mkdir "$LOCK_DIR" 2>/dev/null; then _write_owner; return 0; fi
  local pid stale; pid="$(lock_owner)"
  if [ -z "$pid" ]; then
    echo "ロックに持ち主の記録がありません。実行中でないことを確かめてから data/codex_runs/.lock を削除してください" >&2; return 1
  fi
  if lock_owner_alive "$pid" "$(lock_owner_ts)"; then
    echo "別の Codex が実行中です（PID ${pid}）。動いていないはずなら ps -p $pid で確かめてから data/codex_runs/.lock を削除してください" >&2; return 1
  fi
  # 2本が同時に回収しようとしても、mv は1本だけが成功する。動かした後に持ち主が同じか確かめる
  stale="$LOCK_DIR.stale.$$"; rm -rf "$stale"
  mv "$LOCK_DIR" "$stale" 2>/dev/null || return 1
  if [ "$(cut -d' ' -f1 "$stale/owner" 2>/dev/null)" != "$pid" ]; then
    mv "$stale" "$LOCK_DIR" 2>/dev/null; return 1   # 直前に別の実行が取り直していた
  fi
  rm -rf "$stale"
  echo "古いロックを回収しました（持ち主 PID $pid は動いていないか、別のプロセスに使い回されています。前回の実行は途中で止まった可能性があるので、差分を確認すること）" >&2
  mkdir "$LOCK_DIR" 2>/dev/null && { _write_owner; return 0; }
  return 1
}
release_lock() { [ "$(lock_owner)" = "$$" ] && rm -rf "$LOCK_DIR"; return 0; }

# 実行で生じる __pycache__・.pytest_cache を種類を問わず消す（仕込まれた .pyc を後で読み込まないため。リンクはリンクだけ消える）
clean_artifacts() { find "$PROJ" \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} + 2>/dev/null; return 0; }

# Codex の実行後に使う git。発見（入れ子の .git）を使わず、本物の GITDIR を明示し、設定に仕込めるコマンドを止める
sgit() {
  GIT_DIR="$LUM_GITDIR" GIT_WORK_TREE="$LUM_TOPLEVEL" GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 \
    git --no-pager -c safe.bareRepository=explicit -c core.fsmonitor=false -c core.hooksPath=/dev/null -c core.pager=cat "$@"
}
now_ms() { local s; s="$(date +%s%N 2>/dev/null)"; case "$s" in *N|'') echo $(( $(date +%s) * 1000 ));; *) echo $(( s / 1000000 ));; esac; }
