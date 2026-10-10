#!/usr/bin/env bash
# 全体停止の印（docs/specs/20261008_global_halt.md）。この機械の中のルミナスの新しい作業を止める。
#   bash tools/luminous_halt.sh on [理由]   印を作る（誰が実行してもよい。既にあれば成功。Codex の実行中ならラッパーの PID に TERM）
#   bash tools/luminous_halt.sh status      停止中かと理由を表示
#   bash tools/luminous_halt.sh off         印を消す（Mark が端末で。「解除」と入力。うっかり防止であって守りではない）
# 印: <ルミナスの根>/data/.luminous_halt（git 管理外）。ファイルでもリンクでも、名前があれば停止中。場所は環境変数で動かさない。
# 「AI 側から外せない」の根拠は hooks と権限の設定（B の部分）。別の機械（Mac とクラウド）は止まらない。
# on の記録は logs/halt.log と、Codex が書けない置き場（LUMINOUS_SAFE_DIR、既定 ~/.cache/luminous-codex/halt.log）の両方に残す
# （実行中の Codex が印を消しても、ラッパーが後者と突き合わせて違反にできる）。
# 終了コード: 0=成功 / 1=印を作れない・消せない（止まっていない） / 2=使い方・端末でない・中止 / 3=TERM の後に印が消されていたので作り直した（要確認）
set -u
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
PROJ_REAL="$(cd "$PROJ" && pwd -P)"
HALT="$PROJ/data/.luminous_halt"
SAFE_BASE="${LUMINOUS_SAFE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/luminous-codex}"
TERM_PID=""

halted() { [ -e "$HALT" ] || [ -L "$HALT" ]; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
# 理由は「データ」として扱う: 表示できる文字だけを残し、1 行・N 文字で切る（python3 が無ければ C0 制御文字を落としてバイト単位で近似）
trunc() {  # $1=文字数。標準入力 → 標準出力
  if command -v python3 >/dev/null 2>&1; then
    PYTHONIOENCODING=utf-8 python3 -I -S -c 'import sys; n=int(sys.argv[1]); s=sys.stdin.buffer.read().decode("utf-8","replace"); print("".join(c for c in s if c.isprintable())[:n])' "$1"
  else tr -d '\000-\037\177' | head -c $(( $1 * 3 )); echo; fi
}
sanitize() { printf '%s' "${*:-}" | tr '\n' ' ' | trunc 200; }
log_line() {  # $1=on|off $2=理由
  local line; line="$(printf '%s %s %s' "$(now_utc)" "$1" "$(printf '%s' "$2" | trunc 80)")"
  mkdir -p "$PROJ/logs" 2>/dev/null && printf '%s\n' "$line" >> "$PROJ/logs/halt.log" 2>/dev/null
  mkdir -p "$SAFE_BASE" 2>/dev/null && printf '%s\n' "$line" >> "$SAFE_BASE/halt.log" 2>/dev/null
  return 0
}

# ---- 実行中の Codex のラッパーへ TERM（確かめてから。送るのはラッパーの PID だけ。Codex は別のセッションにいて、ラッパーが止める） ----
etime_secs() {  # ps の etime（[[dd-]hh:]mm:ss）→ 秒
  local e="$1" d=0 a="" b="" c="" h=0 m=0 s=0
  case "$e" in *-*) d="${e%%-*}"; e="${e#*-}";; esac
  IFS=: read -r a b c <<EOF
$e
EOF
  if [ -n "$c" ]; then h="$a"; m="$b"; s="$c"; else m="${a:-0}"; s="${b:-0}"; fi
  case "$d$h$m$s" in *[!0-9]*) echo 0; return 0;; esac
  echo $(( 10#$d * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s ))
}
wrapper_alive() {  # PID が動いているか。ゾンビ（終わったが親がまだ刈り取っていない）は「終わった」とみなす
  kill -0 "$1" 2>/dev/null || return 1
  case "$(ps -o stat= -p "$1" 2>/dev/null | tr -d ' ')" in Z*) return 1;; esac
  return 0
}
term_codex() {
  local lock="$PROJ/data/codex_runs/.lock" owner pid ts args a0 a1 real et secs start now
  [ -d "$lock" ] || return 0
  owner="$lock/owner"
  [ -s "$owner" ] || sleep 1   # 取ったばかりで持ち主がまだ書かれていないことがある
  if [ ! -s "$owner" ]; then echo "luminous_halt: Codex のロックに持ち主の記録が無いため TERM は送りません（ラッパーが起動の前に印を見て止まります）"; return 0; fi
  read -r pid ts < "$owner" || true
  case "${pid:-}" in ''|*[!0-9]*) echo "luminous_halt: ロックの持ち主の PID が数字でないため TERM は送りません"; return 0;; esac
  [ "$pid" -ge 2 ] 2>/dev/null || { echo "luminous_halt: ロックの持ち主の PID（$pid）が不正なため TERM は送りません"; return 0; }
  wrapper_alive "$pid" || { echo "luminous_halt: ロックの持ち主（PID $pid）は動いていないため TERM は送りません"; return 0; }
  args="$(ps -o command= -p "$pid" 2>/dev/null)"; [ -n "$args" ] || args="$(ps -o args= -p "$pid" 2>/dev/null)"
  [ -n "$args" ] || { echo "luminous_halt: ロックの持ち主（PID $pid）は動いていないため TERM は送りません"; return 0; }
  set -f; set -- $args; set +f   # 空白で分ける（グロブ展開はしない）。パスに空白があれば一致せず、送らない側に倒れる
  a0="${1:-}"; a1="${2:-}"
  case "${a0##*/}" in bash) ;; *) echo "luminous_halt: PID $pid はルミナスのラッパー（bash）ではないため TERM は送りません"; return 0;; esac
  # 相対パスは PROJ を基に解く。これはラッパーが PROJ から起動されたとき（Mac の Claude Code は PROJ で Bash を動かす）だけ一致する。
  # 親フォルダから相対パスで起動されたときは一致せず、送らない側に倒れる（ラッパー自身が実行後に印と記録を見て止まる）
  case "$a1" in /*) ;; ''|-*) echo "luminous_halt: PID $pid の引数がラッパーの形でないため TERM は送りません"; return 0;; *) a1="$PROJ/$a1";; esac
  real="$(cd "$(dirname "$a1")" 2>/dev/null && pwd -P)/$(basename "$a1")"
  case "$real" in "$PROJ_REAL/tools/codex_impl.sh"|"$PROJ_REAL/tools/codex_opinion.sh") ;;
    *) echo "luminous_halt: PID $pid はルミナスの tools/codex_impl.sh・codex_opinion.sh ではないため TERM は送りません"; return 0;; esac
  # 持ち主の記録の時刻は、起動の後 5 分以内（PID の使い回しを避ける）
  et="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"; secs="$(etime_secs "$et")"
  now="$(date +%s)"; start=$(( now - secs ))
  case "${ts:-}" in ''|*[!0-9]*) ts=0;; esac
  if [ "$ts" -lt $(( start - 5 )) ] || [ "$ts" -gt $(( start + 300 )) ]; then
    echo "luminous_halt: PID $pid の開始時刻と持ち主の記録が合わないため TERM は送りません（PID の使い回しの疑い）"; return 0
  fi
  if kill -TERM "$pid" 2>/dev/null; then
    TERM_PID="$pid"
    echo "luminous_halt: 実行中の Codex のラッパー（PID $pid）に TERM を送りました（ラッパーが Codex を止めて記録します）"
  else
    echo "luminous_halt: ラッパー（PID $pid）に TERM を送れませんでした（権限か、直前に終了）"
  fi
  return 0
}
# TERM を送った後: ラッパーの終了を待ち（最長 60 秒）、印が消されていれば作り直して警告する（実行中の Codex が消しうる）
after_term() {
  local i=0
  [ -n "$TERM_PID" ] || return 0
  while [ "$i" -lt 600 ] && wrapper_alive "$TERM_PID"; do sleep 0.1; i=$(( i + 1 )); done
  wrapper_alive "$TERM_PID" && echo "luminous_halt: ラッパー（PID $TERM_PID）が 60 秒たっても終わりません。印はそのままです" >&2
  halted && return 0
  printf '%s %s\n' "$(now_utc)" "再作成（TERM の後に印が消えていた）" > "$HALT" 2>/dev/null
  halted || { echo "luminous_halt: !!! TERM の後に印が消えていて、作り直せませんでした。止まっていません（$HALT）" >&2; return 1; }
  [ "$(uname -s)" = Darwin ] && chflags uchg "$HALT" 2>/dev/null
  log_line on "再作成（TERM の後に印が消えていた）"
  echo "luminous_halt: !!! TERM の後に印が消えていました（実行中の Codex が消した疑い）。作り直しました。data/codex_runs/ の記録と差分を確かめてください" >&2
  return 3
}

cmd_on() {
  local reason; reason="$(sanitize "${*:-}")"; [ -n "$reason" ] || reason="(理由なし)"
  mkdir -p "$PROJ/data" 2>/dev/null
  if halted; then
    echo "luminous_halt: 既に全体停止中です（印はそのまま。data/.luminous_halt）"
    log_line on "$reason"; term_codex; after_term; return $?
  fi
  if ! printf '%s %s\n' "$(now_utc)" "$reason" > "$HALT" 2>/dev/null || ! halted; then
    echo "luminous_halt: 印を作れませんでした。止まっていません（$HALT）" >&2; return 1
  fi
  [ "$(uname -s)" = Darwin ] && chflags uchg "$HALT" 2>/dev/null
  log_line on "$reason"
  term_codex
  echo "luminous_halt: 全体停止中にしました（data/.luminous_halt）。解除は Mark が端末で: bash tools/luminous_halt.sh off"
  after_term; return $?
}
cmd_status() {
  if halted; then printf 'luminous_halt: 全体停止中 — %s\n' "$(head -n 1 "$HALT" 2>/dev/null | trunc 200)"
  else echo "luminous_halt: 全体停止ではありません"; fi
  return 0
}
codex_running() {  # Codex のロックがあり、持ち主がまだ無い（取ったばかり）か生きていれば「実行中」
  local lock="$PROJ/data/codex_runs/.lock" pid ts
  [ -d "$lock" ] || return 1
  [ -s "$lock/owner" ] || return 0
  read -r pid ts < "$lock/owner" || return 0
  case "${pid:-}" in ''|*[!0-9]*) return 0;; esac
  wrapper_alive "$pid"
}
cmd_off() {
  halted || { echo "luminous_halt: 印はありません（全体停止ではありません）"; return 0; }
  if codex_running; then   # 実行中に解除すると、ラッパーの突き合わせ（on の記録があるのに印が無い）が偽の違反になる
    echo "luminous_halt: Codex の実行中（data/codex_runs/.lock）は解除できません。ラッパーの終了を待ってください。動いていないのにロックが残っているなら、確かめてから data/codex_runs/.lock を消して再実行（印は残っています）" >&2; return 2
  fi
  [ -t 0 ] || { echo "luminous_halt: off は Mark が端末で実行してください（うっかり防止。印は残っています）" >&2; return 2; }
  local ans reason; reason="$(head -n 1 "$HALT" 2>/dev/null | trunc 80)"
  printf '全体停止を解除します。「解除」と入力して Return: '
  IFS= read -r ans || ans=""
  [ "$ans" = "解除" ] || { echo "luminous_halt: 中止しました（印は残っています）"; return 2; }
  [ "$(uname -s)" = Darwin ] && chflags nouchg "$HALT" 2>/dev/null
  rm -f "$HALT" 2>/dev/null
  halted && { echo "luminous_halt: 印を消せませんでした（$HALT）" >&2; return 1; }
  log_line off "$reason"
  mkdir -p "$PROJ/state" 2>/dev/null && printf '%s off %s\n' "$(now_utc)" "$reason" >> "$PROJ/state/halt.log" 2>/dev/null
  echo "luminous_halt: 解除しました。state/halt.log に記録したので、コミットしてください"
  return 0
}

case "${1:-}" in
  on) shift; cmd_on ${1+"$@"} ;;
  status) cmd_status ;;
  off) cmd_off ;;
  *) echo "使い方: bash tools/luminous_halt.sh on [理由] | status | off" >&2; exit 2 ;;
esac
exit $?
