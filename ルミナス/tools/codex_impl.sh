#!/usr/bin/env bash
# 実装役: 指示書（docs/specs/*.md）を Codex に渡して実装させ、実行前後のフォルダ全体を比べて
# ALLOWED 外の変更・非公開の印・.env の変更・HEAD の移動（Codex の commit）・.git/config の変更を検出する。
# 使い方: bash tools/codex_impl.sh docs/specs/<名前>.md [low|medium|high|xhigh]   （1回 5〜15 分。run_in_background で実行）
# 終了コード: 0=成功 / 2=前提の誤り（停止中・実行中・指示書不備・作業ツリーが汚い・本体なし・安全な置き場なし）
#             3=違反（ALLOWED 外・非公開の印・.env・HEAD・指示書や .git/config の変更）。違反は他の結果より優先
#             4=利用枠の上限（待つ。途中の差分に重ねて再実行しない）/ 5=Codex の失敗
# 検査器（scope_check.py の写し）・指示書の写し・実行前の記録は Codex が書けない場所に置き、作業領域の外の python3 を -I -S で使う。
# 本体は関数に入れてある（bash は関数全体を読んでから実行するので、実行中にこのファイルを書き換えられても影響しない）。
main() {
  set -u
  . "$(dirname "$0")/_codex_common.sh"
  cd "$PROJ" || return 2
  local SPEC="${1:-}" EFFORT="${2:-high}"
  case "$EFFORT" in low|medium|high|xhigh) ;; *) echo "codex_impl: 推論強度は low|medium|high|xhigh: $EFFORT" >&2; return 2;; esac
  codex_disabled && { echo "codex_impl: 停止中（ORCH_CODEX=0 か data/.codex_disabled）" >&2; return 2; }
  [ -n "$SPEC" ] && [ -f "$SPEC" ] || { echo "codex_impl: 指示書がありません: ${SPEC:-（未指定）}" >&2; return 2; }
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "codex_impl: git リポジトリではありません（git init が必要）" >&2; return 2; }
  if [ -n "$(git status --porcelain --untracked-files=no -- .)" ]; then
    echo "codex_impl: 追跡中のファイルに未コミットの変更があります。司令塔が仕上げてから実行してください" >&2
    git status --short --untracked-files=no -- . >&2; return 2
  fi
  local CODEX SAFE_PY SAFE
  CODEX="$(find_codex)"; [ -n "$CODEX" ] || { echo "codex_impl: Codex 本体が見つかりません（ChatGPT アプリのログイン状態を確認）" >&2; return 2; }
  SAFE_PY="$(safe_python)" || { echo "codex_impl: 作業フォルダの外に python3 がありません" >&2; return 2; }
  acquire_lock || { echo "codex_impl: 別の Codex が実行中です（data/codex_runs/.lock）" >&2; return 2; }
  SAFE="$(make_safe_dir)" || { release_lock; return 2; }
  trap 'release_lock' EXIT
  local SC=("$SAFE_PY" -I -S "$SAFE/scope_check.py")
  cp tools/scope_check.py "$SAFE/scope_check.py" && cp "$SPEC" "$SAFE/spec.md" || { remove_safe_dir "$SAFE"; return 2; }
  "${SC[@]}" allowed "$SAFE/spec.md" > "$SAFE/allowed.txt" || { remove_safe_dir "$SAFE"; return 2; }
  local SPEC_SUM ENV_SUM GITDIR START_HEAD CFG_SUM
  SPEC_SUM="$(cksum < "$SPEC")"; ENV_SUM="$( [ -f .env ] && cksum < .env || echo none)"
  GITDIR="$(git rev-parse --absolute-git-dir)"; START_HEAD="$(git rev-parse HEAD)"; CFG_SUM="$(cksum < "$GITDIR/config")"
  "${SC[@]}" snapshot "$PROJ" "$SAFE/before.json" || { remove_safe_dir "$SAFE"; return 2; }

  local DISABLE=() f
  for f in $CODEX_DISABLE_FEATURES; do DISABLE+=(--disable "$f"); done
  local PROMPT="標準入力の指示書（${SPEC}）に従って実装してください。AGENTS.md の不変条件を必ず守ること。ALLOWED に書かれたファイル以外は変更しない。git の操作（commit を含む）はしない。最後に、変更したファイル・要点3行・テスト件数・未解決の点を報告すること。"
  run_codex() { # $1=モデル（空なら ~/.codex/config.toml の既定） $2=回数
    local args=(exec -C "$PROJ" -s workspace-write -c "model_reasoning_effort=$EFFORT" "${DISABLE[@]}" -o "$SAFE/last_message.md")
    [ -n "$1" ] && args+=(-m "$1")
    "$CODEX" "${args[@]}" "$PROMPT" < "$SAFE/spec.md" > "$SAFE/stdout.$2.log" 2> "$SAFE/stderr.$2.log"
  }
  is_limit() { grep -qiE 'try again at|usage limit|rate limit' "$SAFE/stderr.$1.log" 2>/dev/null; }

  local T0 MODEL RC LIMIT=0
  T0="$(now_ms)"; MODEL="${CODEX_MODEL:-}"
  run_codex "$MODEL" 1; RC=$?
  [ "$RC" != 0 ] && is_limit 1 && LIMIT=1
  # 失敗かつ作業フォルダが無変更のときだけ、別のモデルで1回やり直す（上限のときはやり直さない）
  if [ "$RC" != 0 ] && [ "$LIMIT" = 0 ] && [ -n "$CODEX_FALLBACK_MODEL" ] && [ "$CODEX_FALLBACK_MODEL" != "$MODEL" ] \
     && [ "$("${SC[@]}" count "$PROJ" "$SAFE/before.json")" = 0 ]; then
    echo "codex_impl: 失敗（rc=$RC）・無変更のため ${CODEX_FALLBACK_MODEL} で1回だけやり直します" >&2
    MODEL="$CODEX_FALLBACK_MODEL"; run_codex "$MODEL" 2; RC=$?
    [ "$RC" != 0 ] && is_limit 2 && LIMIT=1
  fi
  local MS=$(( $(now_ms) - T0 ))
  # 実行で生じた __pycache__・.pytest_cache は消す（仕込まれた .pyc を後で読み込まないため）
  find "$PROJ" -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} + 2>/dev/null

  # 検査は終了コードに関係なく必ず行い、違反は 3 を優先する
  local VIOL=0
  [ "$(cksum < "$SPEC" 2>/dev/null)" != "$SPEC_SUM" ] && { echo "codex_impl: 指示書が実行中に変更されました" >&2; VIOL=1; }
  [ "$( [ -f .env ] && cksum < .env || echo none)" != "$ENV_SUM" ] && { echo "codex_impl: .env が変更されました。差分を確認し、鍵を差し替えてください" >&2; VIOL=1; }
  [ "$(git rev-parse HEAD 2>/dev/null)" != "$START_HEAD" ] && { echo "codex_impl: HEAD が動きました（Codex が commit した可能性）" >&2; VIOL=1; }
  [ "$(cksum < "$GITDIR/config" 2>/dev/null)" != "$CFG_SUM" ] && { echo "codex_impl: .git/config が変更されました" >&2; VIOL=1; }
  "${SC[@]}" compare "$PROJ" "$SAFE/before.json" "$SAFE/allowed.txt" || VIOL=1

  local RUNDIR="$PROJ/data/codex_runs/$(date +%Y%m%d-%H%M%S)-$(basename "$SPEC" .md)"
  mkdir -p "$RUNDIR" && cp "$SAFE"/*.log "$SAFE/allowed.txt" "$RUNDIR/" 2>/dev/null; cp "$SAFE/last_message.md" "$RUNDIR/" 2>/dev/null
  local STATUS=ok CODE=0
  if [ "$VIOL" = 1 ]; then STATUS=error; CODE=3
  elif [ "$LIMIT" = 1 ]; then STATUS=error; CODE=4
  elif [ "$RC" != 0 ]; then STATUS=error; CODE=5
  fi
  "${SC[@]}" ledger --data-dir "${ORCH_DATA_DIR:-$PROJ/data}" --vendor codex --status "$STATUS" --ms "$MS" --model "${MODEL:-default}" --purpose "$(basename "$SPEC")" || true
  remove_safe_dir "$SAFE"
  case "$CODE" in
    0) echo "codex_impl: 完了（$((MS/1000)) 秒）。次: git diff → テスト → 審査（docs/review.md、Opus、1行目 APPROVE）→ 該当ファイルだけコミット"
       echo "codex_impl: Codex の報告 → ${RUNDIR#"$PROJ"/}/last_message.md"; git status --short -- . ;;
    3) echo "codex_impl: 違反があります。差分を確認し、必要なら git checkout / 削除で戻してください（記録: ${RUNDIR#"$PROJ"/}）" >&2 ;;
    4) echo "codex_impl: 利用枠の上限に当たりました。指示書を残して待ってください。途中の差分があれば再実行せず、司令塔が仕上げます" >&2 ;;
    5) echo "codex_impl: Codex が失敗しました（rc=$RC）。${RUNDIR#"$PROJ"/}/stderr.*.log を確認" >&2 ;;
  esac
  return "$CODE"
}
main "$@"; exit $?
