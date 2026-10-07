#!/usr/bin/env bash
# 実装役: 指示書（docs/specs/*.md）を Codex に渡して実装させ、実行前後のフォルダ全体を比べて
# ALLOWED 外の変更・非公開の印・.env の変更・HEAD の移動（Codex の commit）・.git の設定や hooks の変更・入れ子の .git を検出する。
# 使い方: bash tools/codex_impl.sh docs/specs/<名前>.md [low|medium|high|xhigh]   （1回 5〜15 分。run_in_background で実行。実行中はこのフォルダを編集しない）
# 終了コード: 0=成功
#             2=前提の誤り（停止中・実行中・前回の違反が未処理・指示書不備・作業ツリーが汚い・作業フォルダ内に .git・本体なし・安全な置き場なし）
#             3=違反（ALLOWED 外・非公開の印・.env・HEAD・指示書・.git の設定や hooks・入れ子の .git・リンクや FIFO 等）。他の結果より優先し、
#               data/.codex_violation を作る（司令塔が確認して消すまで次の実行を断る）
#             4=利用枠の上限（待つ。途中の差分に重ねて再実行しない）/ 5=Codex の失敗 / 130=中断（INT・TERM・HUP。検査と片付けは行う）
# 検査器（scope_check.py の写し）・指示書の写し・実行前の記録は Codex が書けない場所に置き、作業領域の外の python3 を -I -S で使う。
# Codex の実行後は、入れ子の .git を隔離し、本物の .git の設定・hooks が変わっていないことを確かめるまで git を1回も実行しない。
# Codex は独自のプロセスグループで動かし、終了後にグループごと止め、待ち時間（LUMINOUS_SETTLE_S、既定 2 秒）を置いてから検査し、
# 片付けの後にもう一度待って比べ直す（グループから抜け出したプロセスの遅れた書き込みを検出する。完全ではない: docs/support-ai.md §10）。
# 本体は関数に入れてある（bash は関数全体を読んでから実行するので、実行中にこのファイルを書き換えられても影響しない）。
LUM_SAFE=""; LUM_CPID=""; LUM_INTERRUPTED=0; LUM_GITDIR=""; LUM_TOPLEVEL=""
on_exit() { [ -n "$LUM_SAFE" ] && remove_safe_dir "$LUM_SAFE"; release_lock; }
on_signal() { LUM_INTERRUPTED=1; [ -n "$LUM_CPID" ] && { kill -TERM -- "-$LUM_CPID" 2>/dev/null || kill -TERM "$LUM_CPID" 2>/dev/null; }; return 0; }
# Codex は独自のプロセスグループで起動し、終わったらグループごと止める（裏に残したプロセスが検査の後に書き込むのを防ぐ）
stop_group() { # $1=グループの番号（= Codex の PID）
  kill -0 -- "-$1" 2>/dev/null || return 0
  kill -TERM -- "-$1" 2>/dev/null; sleep 1
  kill -KILL -- "-$1" 2>/dev/null
  echo "codex_impl: Codex の終了後も残っていたプロセスを止めました" >&2
  return 0
}

main() {
  set -u
  . "$(dirname "$0")/_codex_common.sh"
  cd "$PROJ" || return 2
  local SPEC="${1:-}" EFFORT="${2:-high}"
  case "$EFFORT" in low|medium|high|xhigh) ;; *) echo "codex_impl: 推論強度は low|medium|high|xhigh: $EFFORT" >&2; return 2;; esac
  codex_disabled && { echo "codex_impl: 停止中（ORCH_CODEX=0 か data/.codex_disabled）" >&2; return 2; }
  if [ -e data/.codex_violation ]; then
    echo "codex_impl: 前回の実行の違反が未処理です（data/.codex_violation）。司令塔が差分を確認して片付けてから、このファイルを削除してください" >&2; return 2
  fi
  [ -n "$SPEC" ] && [ -f "$SPEC" ] && [ ! -L "$SPEC" ] || { echo "codex_impl: 指示書がありません（リンクは不可）: ${SPEC:-（未指定）}" >&2; return 2; }
  local SPEC_NAME="${SPEC##*/}"; SPEC_NAME="${SPEC_NAME%.md}"
  local CODEX SAFE_PY
  SAFE_PY="$(safe_python)" || { echo "codex_impl: 作業フォルダの外に python3 がありません" >&2; return 2; }
  # git を実行する前に、作業フォルダ内に .git が無いことを確かめる（.git の設定に仕込まれたコマンドを走らせないため）
  "$SAFE_PY" -I -S "$PROJ/tools/scope_check.py" nested-git "$PROJ" \
    || { echo "codex_impl: 作業フォルダ内に .git があります。git コマンドを使わずに中身を確かめ、作業フォルダの外へ移してから実行してください" >&2; return 2; }
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "codex_impl: git リポジトリではありません（git init が必要）" >&2; return 2; }
  LUM_GITDIR="$(git rev-parse --absolute-git-dir)"; LUM_TOPLEVEL="$(git rev-parse --show-toplevel)"
  if [ -n "$(sgit status --porcelain --untracked-files=no -- "$PROJ")" ]; then
    echo "codex_impl: 追跡中のファイルに未コミットの変更があります。司令塔が仕上げてから実行してください" >&2
    sgit status --short --untracked-files=no -- "$PROJ" >&2; return 2
  fi
  CODEX="$(find_codex)"; [ -n "$CODEX" ] || { echo "codex_impl: Codex 本体が見つかりません（ChatGPT アプリのログイン状態を確認）" >&2; return 2; }
  acquire_lock || { echo "codex_impl: 実行できません（data/codex_runs/.lock）" >&2; return 2; }
  trap on_exit EXIT
  trap on_signal INT TERM HUP
  LUM_SAFE="$(make_safe_dir)" || { LUM_SAFE=""; return 2; }
  clean_artifacts   # 前回が途中で止まっていた場合に残った .pyc なども消してから記録する
  local SC=("$SAFE_PY" -I -S "$LUM_SAFE/scope_check.py") RG=(--real-gitdir "$LUM_GITDIR")
  cp -- tools/scope_check.py "$LUM_SAFE/scope_check.py" && cp -- "$SPEC" "$LUM_SAFE/spec.md" || return 2
  "${SC[@]}" allowed "$LUM_SAFE/spec.md" > "$LUM_SAFE/allowed.txt" || return 2
  local SPEC_SUM ENV_SUM START_HEAD GITFP
  SPEC_SUM="$("${SC[@]}" fsum "$SPEC")"; ENV_SUM="$("${SC[@]}" fsum .env)"
  START_HEAD="$(sgit rev-parse HEAD)"; GITFP="$("${SC[@]}" gitfp "$LUM_GITDIR")"
  "${SC[@]}" snapshot "$PROJ" "$LUM_SAFE/before.json" "${RG[@]}" || return 2
  [ "$LUM_INTERRUPTED" = 1 ] && { echo "codex_impl: 開始前に中断しました" >&2; return 130; }

  local DISABLE=() f
  for f in $CODEX_DISABLE_FEATURES; do DISABLE+=(--disable "$f"); done
  local PROMPT="標準入力の指示書（${SPEC}）に従って実装してください。AGENTS.md の不変条件を必ず守ること。ALLOWED に書かれたファイル以外は変更しない。git の操作（commit を含む）はしない。最後に、変更したファイル・要点3行・テスト件数・未解決の点を報告すること。"
  run_codex() { # $1=モデル（空なら ~/.codex/config.toml の既定） $2=回数。信号で止められるよう、裏で動かして wait する
    local args=(exec -C "$PROJ" -s workspace-write -c "model_reasoning_effort=$EFFORT" ${DISABLE[@]+"${DISABLE[@]}"} -o "$LUM_SAFE/last_message.md") rc
    [ -n "$1" ] && args+=(-m "$1")
    "$SAFE_PY" -I -S -c 'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' "$CODEX" "${args[@]}" "$PROMPT" \
      < "$LUM_SAFE/spec.md" > "$LUM_SAFE/stdout.$2.log" 2> "$LUM_SAFE/stderr.$2.log" &
    LUM_CPID=$!
    wait "$LUM_CPID"; rc=$?
    [ "$LUM_INTERRUPTED" = 1 ] && { wait "$LUM_CPID" 2>/dev/null; rc=130; }
    stop_group "$LUM_CPID"
    LUM_CPID=""
    return "$rc"
  }
  is_limit() { grep -qiE 'try again at|usage limit|rate limit' "$LUM_SAFE/stderr.$1.log" 2>/dev/null; }

  local T0 MODEL RC LIMIT=0
  T0="$(now_ms)"; MODEL="${CODEX_MODEL:-}"
  run_codex "$MODEL" 1; RC=$?
  [ "$RC" != 0 ] && [ "$LUM_INTERRUPTED" = 0 ] && is_limit 1 && LIMIT=1
  # 失敗かつ作業フォルダが無変更のときだけ、別のモデルで1回やり直す（上限・中断のときはやり直さない）
  if [ "$RC" != 0 ] && [ "$LIMIT" = 0 ] && [ "$LUM_INTERRUPTED" = 0 ] && [ -n "$CODEX_FALLBACK_MODEL" ] && [ "$CODEX_FALLBACK_MODEL" != "$MODEL" ] \
     && [ "$("${SC[@]}" count "$PROJ" "$LUM_SAFE/before.json" "${RG[@]}")" = 0 ]; then
    echo "codex_impl: 失敗（rc=$RC）・無変更のため ${CODEX_FALLBACK_MODEL} で1回だけやり直します" >&2
    MODEL="$CODEX_FALLBACK_MODEL"; run_codex "$MODEL" 2; RC=$?
    [ "$RC" != 0 ] && [ "$LUM_INTERRUPTED" = 0 ] && is_limit 2 && LIMIT=1
  fi
  local MS=$(( $(now_ms) - T0 )) SETTLE="${LUMINOUS_SETTLE_S:-2}"
  case "$SETTLE" in ''|*[!0-9]*) SETTLE=2 ;; esac
  sleep "$SETTLE"

  # 検査は終了コードに関係なく必ず行い、違反は 3 を優先する。順序: 入れ子の .git の隔離 → 本物の .git の確認 → git → 比較 → 片付け
  local VIOL=0 GIT_OK=1 STAMP; STAMP="$(date +%Y%m%d-%H%M%S)"
  local QDIR="${LUM_SAFE%/*}/quarantine/$STAMP-$SPEC_NAME"
  "${SC[@]}" quarantine-git "$PROJ" "$LUM_SAFE/before.json" "$QDIR" "${RG[@]}"
  case $? in 0) ;; 3) VIOL=1 ;; *) VIOL=1; GIT_OK=0 ;; esac
  if [ "$("${SC[@]}" gitfp "$LUM_GITDIR")" != "$GITFP" ]; then
    echo "codex_impl: 本物の .git の設定・hooks・info/attributes が変更されました。git コマンドを使う前に確認してください" >&2; VIOL=1; GIT_OK=0
  fi
  if [ "$GIT_OK" = 1 ]; then
    [ "$(sgit rev-parse HEAD 2>/dev/null)" != "$START_HEAD" ] && { echo "codex_impl: HEAD が動きました（Codex が commit した可能性）" >&2; VIOL=1; }
  else
    echo "codex_impl: git を安全に使えると確かめられないため、HEAD の確認を省きました" >&2
  fi
  [ "$("${SC[@]}" fsum "$SPEC")" != "$SPEC_SUM" ] && { echo "codex_impl: 指示書が実行中に変更されました" >&2; VIOL=1; }
  [ "$("${SC[@]}" fsum .env)" != "$ENV_SUM" ] && { echo "codex_impl: .env が変更されました（内容か権限）。差分を確認し、鍵を差し替えてください" >&2; VIOL=1; }
  "${SC[@]}" compare "$PROJ" "$LUM_SAFE/before.json" "$LUM_SAFE/allowed.txt" "${RG[@]}" --save-after "$LUM_SAFE/after.json" || VIOL=1
  clean_artifacts   # 検査の後に消す（リンクの __pycache__ は検査で違反にしてから、リンクだけ消す）
  # 待ってから比べ直す: 検査の後にも書き込みが続いていれば違反（グループから抜け出したプロセスの可能性）
  sleep "$SETTLE"
  "${SC[@]}" quarantine-git "$PROJ" "$LUM_SAFE/before.json" "$QDIR" "${RG[@]}" || VIOL=1
  if [ -f "$LUM_SAFE/after.json" ]; then
    "${SC[@]}" recheck "$PROJ" "$LUM_SAFE/after.json" "${RG[@]}" || { echo "codex_impl: 検査の後にも書き込みがありました。裏に残ったプロセスを確かめてください" >&2; VIOL=1; }
  else
    VIOL=1
  fi
  clean_artifacts

  local RUNDIR="$PROJ/data/codex_runs/$STAMP-$SPEC_NAME"
  mkdir -p "$RUNDIR" && cp "$LUM_SAFE"/*.log "$LUM_SAFE/allowed.txt" "$RUNDIR/" 2>/dev/null; cp "$LUM_SAFE/last_message.md" "$RUNDIR/" 2>/dev/null
  local STATUS=ok CODE=0
  if [ "$VIOL" = 1 ]; then STATUS=error; CODE=3
  elif [ "$LUM_INTERRUPTED" = 1 ]; then STATUS=error; CODE=130
  elif [ "$LIMIT" = 1 ]; then STATUS=error; CODE=4
  elif [ "$RC" != 0 ]; then STATUS=error; CODE=5
  fi
  if [ "$CODE" = 3 ]; then
    { echo "日時: $STAMP"; echo "記録: ${RUNDIR#"$PROJ"/}"; [ -d "$QDIR" ] && echo "隔離した .git: $QDIR（作業フォルダの外。git コマンドで開かない）"
      echo "確認して片付けたら、このファイルを削除する（それまで codex_impl.sh は実行を断る）"; } > data/.codex_violation
  fi
  "${SC[@]}" ledger --data-dir="${ORCH_DATA_DIR:-$PROJ/data}" --vendor=codex --status="$STATUS" --ms="$MS" --model="${MODEL:-default}" --purpose="$SPEC_NAME" || true
  case "$CODE" in
    0) echo "codex_impl: 完了（$((MS/1000)) 秒）。次: git diff → テスト → 審査（docs/review.md、Opus、1行目 APPROVE）→ 該当ファイルだけコミット"
       echo "codex_impl: Codex の報告 → ${RUNDIR#"$PROJ"/}/last_message.md" ;;
    3) echo "codex_impl: 違反があります。差分を確認し、必要なら git checkout / 削除で戻してください（記録: ${RUNDIR#"$PROJ"/}）。片付けたら data/.codex_violation を削除" >&2 ;;
    130) echo "codex_impl: 中断しました。途中の差分を確認してください（記録: ${RUNDIR#"$PROJ"/}）" >&2 ;;
    4) echo "codex_impl: 利用枠の上限に当たりました。指示書を残して待ってください。途中の差分があれば再実行せず、司令塔が仕上げます" >&2 ;;
    5) echo "codex_impl: Codex が失敗しました（rc=$RC）。${RUNDIR#"$PROJ"/}/stderr.*.log を確認" >&2 ;;
  esac
  return "$CODE"
}
main "$@"; exit $?
