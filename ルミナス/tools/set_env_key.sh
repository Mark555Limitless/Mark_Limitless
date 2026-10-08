#!/usr/bin/env bash
# 鍵を画面に表示せずに .env へ入れる（Mark 本人が端末で実行する。Claude は実行しない・値を読まない）。
# 使い方: bash tools/set_env_key.sh GEMINI_API_KEY | TYPESAFE_API_KEY
# - 入力は画面に出ない。端末以外（パイプ・エージェント）からの入力は受け付けない
# - 既存の .env を非公開フォルダ（既定: ルミナスの隣の ルミナス_非公開/env_backups/.env.bak.<日時>、権限 600）へ控えてから書き換える
# - 書き込みは権限 600 の一時ファイルに書いてから置き換える（途中の失敗で鍵が 644 のまま残らない）。どの段で失敗しても止まる
# - 反映後の疎通確認は、シェルに残っている古い鍵を外して .env の値で行う（値は表示しない）
main() {
  set -u
  local PROJ VAR PRIV VAL
  PROJ="$(cd "$(dirname "$0")/.." && pwd)"
  VAR="${1:-}"
  case "$VAR" in GEMINI_API_KEY|TYPESAFE_API_KEY) ;; *) echo "使い方: $0 GEMINI_API_KEY|TYPESAFE_API_KEY" >&2; return 2;; esac
  [ -t 0 ] || { echo "set_env_key: 端末から直接実行してください（パイプやエージェント経由の入力は受け付けません）" >&2; return 2; }
  PRIV="${LUMINOUS_PRIVATE_DIR:-$(dirname "$PROJ")/ルミナス_非公開}"
  # 控えの置き場が git の管理下（公開リポジトリの中など）で、しかも ignore されていなければ止める
  if git -C "$(dirname "$PRIV")" rev-parse --is-inside-work-tree >/dev/null 2>&1 && ! git -C "$(dirname "$PRIV")" check-ignore -q "$PRIV" 2>/dev/null; then
    echo "set_env_key: 控えの置き場 $PRIV が git の管理下です。LUMINOUS_PRIVATE_DIR で管理外の場所を指定してください" >&2; return 1
  fi
  printf '%s の値を入力（表示されません）: ' "$VAR"; IFS= read -rs VAL; echo
  [ -n "$VAL" ] || { echo "set_env_key: 空の値は入れません" >&2; return 2; }
  umask 077
  if [ -f "$PROJ/.env" ]; then
    mkdir -p "$PRIV/env_backups" && chmod 700 "$PRIV" "$PRIV/env_backups" \
      && cp "$PROJ/.env" "$PRIV/env_backups/.env.bak.$(date +%Y%m%d-%H%M%S)" \
      && chmod 600 "$PRIV/env_backups/".env.bak.* \
      || { echo "set_env_key: 控えを作れなかったので中止しました（.env は変えていません）" >&2; unset VAL; return 1; }
  fi
  # 値はコマンドラインではなく環境変数で渡す（ps に出さない）。600 の一時ファイルに書いてから置き換える
  if ! NEWVAL="$VAL" VARNAME="$VAR" ENVFILE="$PROJ/.env" python3 - <<'PY'
import os, re, sys, tempfile
p, k, v = os.environ["ENVFILE"], os.environ["VARNAME"], os.environ["NEWVAL"]
lines = open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else []
pat = re.compile(r"^\s*" + re.escape(k) + r"\s*=")
out, done = [], False
for l in lines:
    if pat.match(l):
        if not done:
            out.append(f"{k}={v}"); done = True
        continue
    out.append(l)
if not done:
    out.append(f"{k}={v}")
fd, tmp = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=os.path.dirname(p))
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, p)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    sys.exit(1)
PY
  then
    unset VAL; echo "set_env_key: .env への書き込みに失敗しました（控えから戻せます: $PRIV/env_backups/）" >&2; return 1
  fi
  unset VAL
  chmod 600 "$PROJ/.env" || { echo "set_env_key: 権限 600 にできませんでした" >&2; return 1; }
  echo "set_env_key: $VAR を .env に保存しました（権限 600）。疎通を確認します..."
  local PYBIN="$PROJ/.venv/bin/python"; [ -x "$PYBIN" ] || PYBIN=python3
  cd "$PROJ" || return 1
  if [ "$VAR" = GEMINI_API_KEY ]; then
    env -u GEMINI_API_KEY -u TYPESAFE_API_KEY "$PYBIN" -m orch.gemini check \
      || echo "set_env_key: 保存はできましたが、疎通確認は通りませんでした（上の表示を確認）" >&2
  else
    env -u GEMINI_API_KEY -u TYPESAFE_API_KEY "$PYBIN" -m orch.decisions --check \
      && echo "（Jev の実呼び出しは JEV_ENABLED=1 の上で python3 -m orch.decisions --demo --backend jev。1回 約 \$0.0001）"
  fi
  return 0
}
main "$@"; exit $?
