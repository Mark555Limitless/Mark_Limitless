#!/usr/bin/env bash
# Codex（GPT-6 Astra）に作業パケットを渡し、回答を docs/astra-replies/ に保存する。
# 使い方: scripts/ask-astra.sh docs/astra-packets/WP-1-architecture-review.md [出力名]
# 環境変数: ASTRA_MODEL（既定 gpt-6-astra。無効なら GPT-6 Sol 等に変更）、CODEX_BIN（codex の実行パス）、ASTRA_SANDBOX（既定 read-only）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKET="${1:-}"
[ -n "$PACKET" ] && [ -f "$PACKET" ] || { echo "使い方: $0 <パケット.md> [出力名]" >&2; exit 2; }
NAME="${2:-$(basename "$PACKET" .md)}"
MODEL="${ASTRA_MODEL:-gpt-6-astra}"
CODEX="${CODEX_BIN:-codex}"
SANDBOX="${ASTRA_SANDBOX:-read-only}"
OUT="$ROOT/docs/astra-replies/$(date +%Y%m%d)-$NAME.md"

case "${PACKET#"$ROOT"/}" in docs/astra-packets/*|./docs/astra-packets/*) ;; *) echo "パケットは docs/astra-packets/ に置いてください（公開可の範囲だけを外部に送るため。VIRTUAL_MARK §6）" >&2; exit 2;; esac
command -v "$CODEX" >/dev/null 2>&1 || { echo "codex が見つかりません。npm i -g @openai/codex でインストールするか CODEX_BIN を指定してください。" >&2; exit 3; }
if ! "$CODEX" login status >/dev/null 2>&1; then
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    # 鍵の値はこのスクリプト内でだけ流れ、画面にもファイルにも出さない（憲章 I-4）
    printf '%s' "$OPENAI_API_KEY" | "$CODEX" login --with-api-key >/dev/null 2>&1 || { echo "codex login（API キー）に失敗しました。" >&2; exit 4; }
  else
    echo "Codex にログインしていません。Mark 本人が手元で \`codex login\`（ブラウザ）を実行してください。鍵をチャットや本フォルダに貼らないこと（憲章 I-4）。" >&2
    exit 4
  fi
fi

mkdir -p "$(dirname "$OUT")"
{
  echo "# Astra 回答: $NAME"
  echo
  echo "- 日時: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- モデル指定: $MODEL（実際に使われたモデルは Codex 側の表示を確認）"
  echo "- パケット: ${PACKET#"$ROOT"/}"
  echo "- 取り込み規則: docs/astra-consultation.md（憲章 I-6 で裏取りしてから採用）"
  echo
  echo "---"
  echo
} > "$OUT"

# パケット本文を stdin で渡す（プロンプト引数には役割指定だけ）。
# 注: codex exec がカスタムエージェント TOML を名前で読むかは公式文書で未確認のため、役割は文面でも指定する。
# 注: 送る前に秘匿情報が混ざっていないか検査する（憲章 I-4）
bash "$ROOT/scripts/secret-scan.sh" --quiet < "$PACKET" || { echo "パケットに鍵らしき文字列があるため送信を中止しました。" >&2; exit 6; }
# 外部AIには「公開可・push 済み」のファイルだけを書き出した使い捨てディレクトリを見せる（VIRTUAL_MARK §6）
PUB="$(bash "$ROOT/scripts/export-public.sh")" || { echo "公開用ディレクトリを作れませんでした。" >&2; exit 7; }
RC=0
"$CODEX" exec -C "$PUB" --skip-git-repo-check -s "$SANDBOX" -m "$MODEL" \
     "あなたは .codex/agents/astra-architect.toml の役割（第二意見・反証役）です。AGENTS.md と CHARTER.md を読んでから、stdin のパケットに日本語で答えてください。" \
     < "$PACKET" >> "$OUT" 2> "$OUT.err" || RC=$?
bash "$ROOT/scripts/cleanup-public.sh" "$PUB" 2>/dev/null || true
if [ "$RC" != 0 ]; then
  echo "codex exec が失敗しました。$OUT.err を確認してください（モデル名が無効なら ASTRA_MODEL を変更）。" >&2
  exit 5
fi
rm -f "$OUT.err"
echo "保存: ${OUT#"$ROOT"/}"
