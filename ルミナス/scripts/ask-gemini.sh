#!/usr/bin/env bash
# Gemini CLI にパケットを渡し、回答を docs/gemini-replies/ に保存する（クロスベンダー検証・調査役）。
# 使い方: scripts/ask-gemini.sh docs/gemini-packets/<パケット>.md [出力名]
# 環境変数: GEMINI_API_KEY（必須。値は表示しない）、GEMINI_MODEL（既定は CLI の既定モデル）、GEMINI_BIN
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKET="${1:-}"
[ -n "$PACKET" ] && [ -f "$PACKET" ] || { echo "使い方: $0 <パケット.md> [出力名]" >&2; exit 2; }
NAME="${2:-$(basename "$PACKET" .md)}"
GEMINI="${GEMINI_BIN:-gemini}"
OUT="$ROOT/docs/gemini-replies/$(date +%Y%m%d)-$NAME.md"
command -v "$GEMINI" >/dev/null 2>&1 || { echo "gemini が見つかりません。npm i -g @google/gemini-cli でインストールするか GEMINI_BIN を指定してください。" >&2; exit 3; }
if [ -z "${GEMINI_API_KEY:-}" ] && [ ! -d "$HOME/.gemini" ]; then
  echo "GEMINI_API_KEY が未設定で、Google ログインの記録もありません。鍵は環境変数で渡してください（チャットやファイルに貼らない）。" >&2
  exit 4
fi
mkdir -p "$(dirname "$OUT")"
{
  echo "# Gemini 回答: $NAME"; echo
  echo "- 日時: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- モデル指定: ${GEMINI_MODEL:-（CLI 既定）}"
  echo "- パケット: ${PACKET#"$ROOT"/}"
  echo "- 取り込み規則: docs/support-ai.md §3（憲章 I-6 で裏取りしてから採用）"; echo; echo "---"; echo
} > "$OUT"
bash "$ROOT/scripts/secret-scan.sh" --quiet < "$PACKET" || { echo "パケットに鍵らしき文字列があるため送信を中止しました。" >&2; exit 6; }
# 注: Gemini CLI の承認モード・サンドボックスの指定フラグは公式文書で要確認。読み取り専用で使う運用（ファイル変更は司令塔が行う）
ARGS=(-p "あなたはルミナス（Luminous）のサポートAI（調査・クロスベンダー検証役）です。AGENTS.md と CHARTER.md を読んでから、stdin のパケットに日本語で、出典と信頼度を添えて答えてください。推測は「推測」と書き、鍵やパスワードは出力しないこと。")
[ -n "${GEMINI_MODEL:-}" ] && ARGS+=(-m "$GEMINI_MODEL")
if ! (cd "$ROOT" && "$GEMINI" "${ARGS[@]}" < "$PACKET") >> "$OUT" 2> "$OUT.err"; then
  echo "gemini が失敗しました。$OUT.err を確認してください。" >&2; exit 5
fi
rm -f "$OUT.err"; echo "保存: ${OUT#"$ROOT"/}"
