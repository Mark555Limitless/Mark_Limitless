#!/usr/bin/env bash
# 実装役: 指示書（docs/specs/*.md）を Codex に渡して実装させ、ALLOWED 外の変更と非公開の印を機械で検査する。
# 使い方: bash tools/codex_impl.sh docs/specs/<名前>.md [low|medium|high|xhigh]   （1回 5〜15 分。run_in_background で実行）
# 終了コード: 0=成功 / 2=前提の誤り（停止中・実行中・指示書不備・作業ツリーが汚い・本体なし）
#             3=ALLOWED 外の変更、非公開の印の混入、.env の変更 / 4=利用枠の上限（待つ。再実行しない）/ 5=Codex の失敗
# Codex は commit しない。差分は司令塔が git diff → テスト → 審査（Opus、1行目 APPROVE）→ 該当ファイルだけコミット。
set -u
. "$(dirname "$0")/_codex_common.sh"
cd "$PROJ" || exit 2
SPEC="${1:-}"; EFFORT="${2:-high}"
case "$EFFORT" in low|medium|high|xhigh) ;; *) echo "codex_impl: 推論強度は low|medium|high|xhigh: $EFFORT" >&2; exit 2;; esac
codex_disabled && { echo "codex_impl: 停止中（ORCH_CODEX=0 か data/.codex_disabled）" >&2; exit 2; }
[ -n "$SPEC" ] && [ -f "$SPEC" ] || { echo "codex_impl: 指示書がありません: ${SPEC:-（未指定）}" >&2; exit 2; }
grep -q '<!--[[:space:]]*ALLOWED[[:space:]]*-->' "$SPEC" || { echo "codex_impl: 指示書に ALLOWED ブロックがありません" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "codex_impl: git リポジトリではありません（git init が必要）" >&2; exit 2; }
# 追跡中のファイルに未コミットの変更があれば始めない（途中の差分に重ねると壊れる）
if [ -n "$(git status --porcelain --untracked-files=no -- .)" ]; then
  echo "codex_impl: 作業ツリーに未コミットの変更があります。司令塔が仕上げてから実行してください" >&2; git status --short --untracked-files=no -- . >&2; exit 2
fi
CODEX="$(find_codex)"; [ -n "$CODEX" ] || { echo "codex_impl: Codex 本体が見つかりません（ChatGPT アプリのログイン状態を確認）" >&2; exit 2; }
acquire_lock || { echo "codex_impl: 別の Codex が実行中です（data/codex_runs/.lock）" >&2; exit 2; }
trap release_lock EXIT

RUN="data/codex_runs/$(date +%Y%m%d-%H%M%S)-$(basename "$SPEC" .md)"; mkdir -p "$RUN"
git ls-files --others --exclude-standard > "$RUN/baseline_untracked.txt"
ENV_HASH_BEFORE="$( [ -f .env ] && cksum < .env || echo none)"
DISABLE=(); for f in ${CODEX_DISABLE_FEATURES:-memories multi_agent}; do DISABLE+=(--disable "$f"); done
PROMPT="指示書 ${SPEC} に従って実装してください（標準入力にも同じ内容があります）。AGENTS.md の不変条件を必ず守ること。ALLOWED に書かれたファイル以外は変更しない。git commit はしない。最後に、変更したファイル・要点3行・テスト件数・未解決の点を報告すること。"

run_codex() { # $1=モデル（空なら ~/.codex/config.toml の既定）
  local m=("${@:1}") args=(exec -C "$PROJ" -s workspace-write -c "model_reasoning_effort=$EFFORT" "${DISABLE[@]}" -o "$RUN/last_message.md")
  [ -n "${m[0]:-}" ] && args+=(-m "${m[0]}")
  "$CODEX" "${args[@]}" "$PROMPT" < "$SPEC" >> "$RUN/stdout.log" 2>> "$RUN/stderr.log"
}
unchanged() { [ -z "$(git status --porcelain --untracked-files=no -- .)" ] && cmp -s <(git ls-files --others --exclude-standard) "$RUN/baseline_untracked.txt"; }

T0="$(now_ms)"; MODEL="${CODEX_MODEL:-}"
run_codex "$MODEL"; RC=$?
if grep -qiE 'try again at|usage limit|rate limit' "$RUN/stderr.log" "$RUN/stdout.log" 2>/dev/null; then
  ledger error $(( $(now_ms) - T0 )) "${MODEL:-default}" "$(basename "$SPEC")"
  echo "codex_impl: 利用枠の上限に当たりました。指示書を残して待ってください。途中の差分があれば再実行せず、司令塔が仕上げます" >&2; exit 4
fi
# 失敗かつ作業ツリーが無変更のときだけ、別のモデルで1回やり直す
if [ "$RC" != 0 ] && unchanged && [ -n "${CODEX_FALLBACK_MODEL:-}" ] && [ "${CODEX_FALLBACK_MODEL}" != "$MODEL" ]; then
  echo "codex_impl: 失敗（rc=$RC）・無変更のため ${CODEX_FALLBACK_MODEL} で1回だけやり直します" >&2
  MODEL="$CODEX_FALLBACK_MODEL"; run_codex "$MODEL"; RC=$?
fi
MS=$(( $(now_ms) - T0 ))
ENV_HASH_AFTER="$( [ -f .env ] && cksum < .env || echo none)"
if [ "$ENV_HASH_BEFORE" != "$ENV_HASH_AFTER" ]; then
  ledger error "$MS" "${MODEL:-default}" "$(basename "$SPEC")"; echo "codex_impl: .env が変更されました。差分を確認し、鍵を差し替えてください" >&2; exit 3
fi
if [ "$RC" != 0 ]; then ledger error "$MS" "${MODEL:-default}" "$(basename "$SPEC")"; echo "codex_impl: Codex が失敗しました（rc=$RC）。$RUN/stderr.log を確認" >&2; exit 5; fi
"$PY" tools/scope_check.py "$SPEC" --baseline "$RUN/baseline_untracked.txt"; SC=$?
if [ "$SC" != 0 ]; then ledger error "$MS" "${MODEL:-default}" "$(basename "$SPEC")"; exit 3; fi
ledger ok "$MS" "${MODEL:-default}" "$(basename "$SPEC")"
echo "codex_impl: 完了（$((MS/1000)) 秒）。次: git diff → テスト → 審査（docs/review.md、Opus、1行目 APPROVE）→ 該当ファイルだけコミット"
echo "codex_impl: Codex の報告 → $RUN/last_message.md"
git status --short -- .
exit 0
