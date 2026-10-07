#!/usr/bin/env bash
# 鍵を画面に表示せずに .env へ入れる（Mark 本人が端末で実行する。Claude は実行しない・値を読まない）。
# 使い方: bash tools/set_env_key.sh GEMINI_API_KEY | TYPESAFE_API_KEY
# - 入力は画面に出ない。実行前に .env を非公開フォルダ（../ルミナス_非公開/env_backups/）へバックアップする
# - .env の権限は 600。反映後に疎通を確かめる（鍵の値は表示しない）
set -u
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
VAR="${1:-}"
case "$VAR" in GEMINI_API_KEY|TYPESAFE_API_KEY) ;; *) echo "使い方: $0 GEMINI_API_KEY|TYPESAFE_API_KEY" >&2; exit 2;; esac
[ -t 0 ] || { echo "set_env_key: 端末から直接実行してください（パイプやエージェント経由の入力は受け付けません）" >&2; exit 2; }
PRIV="${LUMINOUS_PRIVATE_DIR:-$(dirname "$PROJ")/ルミナス_非公開}"
# 控えの置き場が git の管理下（公開リポジトリの中など）なら止める
if git -C "$(dirname "$PRIV")" rev-parse --is-inside-work-tree >/dev/null 2>&1 && ! git -C "$(dirname "$PRIV")" check-ignore -q "$PRIV" 2>/dev/null; then
  echo "set_env_key: 控えの置き場 $PRIV が git の管理下です。LUMINOUS_PRIVATE_DIR で管理外の場所を指定してください" >&2; exit 2
fi
printf '%s の値を入力（表示されません）: ' "$VAR"; IFS= read -rs VAL; echo
[ -n "$VAL" ] || { echo "set_env_key: 空の値は入れません" >&2; exit 2; }
umask 077
if [ -f "$PROJ/.env" ]; then mkdir -p "$PRIV/env_backups" && chmod 700 "$PRIV" "$PRIV/env_backups" && cp -p "$PROJ/.env" "$PRIV/env_backups/env.$(date +%Y%m%d-%H%M%S)"; fi
# 値はコマンドラインではなく環境変数で渡す（ps に出さない）
NEWVAL="$VAL" VARNAME="$VAR" ENVFILE="$PROJ/.env" python3 - <<'PY'
import os, re
p, k, v = os.environ["ENVFILE"], os.environ["VARNAME"], os.environ["NEWVAL"]
lines = open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else []
pat = re.compile(rf"^\s*{re.escape(k)}\s*=")
out, done = [], False
for l in lines:
    if pat.match(l):
        if not done:
            out.append(f"{k}={v}"); done = True
        continue
    out.append(l)
if not done:
    out.append(f"{k}={v}")
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
PY
chmod 600 "$PROJ/.env"; unset VAL
echo "set_env_key: $VAR を .env に保存しました（権限 600）。疎通を確認します..."
cd "$PROJ" && PYBIN="$PROJ/.venv/bin/python"; [ -x "$PYBIN" ] || PYBIN=python3
if [ "$VAR" = GEMINI_API_KEY ]; then "$PYBIN" -m orch.gemini check
else "$PYBIN" -m orch.decisions --check && echo "（Jev の実呼び出しは JEV_ENABLED=1 の上で python3 -m orch.decisions --demo --backend jev。1回 約 \$0.0003）"; fi
