#!/usr/bin/env bash
# 一度だけ実行: git フック（pre-commit / pre-push）の有効化と docx 生成用の依存。鍵は扱わない。
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$HERE"/scripts/*.sh "$HERE"/.claude/hooks/*.sh "$HERE"/.githooks/* 2>/dev/null || true
if git -C "$HERE" rev-parse --show-toplevel >/dev/null 2>&1; then
  TOP="$(git -C "$HERE" rev-parse --show-toplevel)"
  REL="${HERE#"$TOP"/}"; [ "$REL" = "$HERE" ] && REL="."
  git -C "$TOP" config core.hooksPath "$REL/.githooks"
  echo "git フックを有効化: core.hooksPath=$REL/.githooks（pre-commit / pre-push で鍵を検査）"
else
  echo "git リポジトリではないため git フックは未設定（git init 後に再実行）"
fi
if command -v npm >/dev/null 2>&1; then
  (cd "$HERE" && npm install --no-audit --no-fund >/dev/null 2>&1 && echo "npm 依存を導入（docx 生成）") || echo "npm install に失敗（docx 生成は手動で）"
fi
cat <<'MSG'
次に行うこと（Mark 本人）:
  - Obsidian へ同期するなら、シェルで  export LUMINOUS_OBSIDIAN_DIR="/絶対パス/Vault"  を設定（鍵ではないので .zshrc 可）
  - Codex は  codex login  をブラウザで。Gemini / Jev の鍵は OS のキーチェーンやシェル環境から各ラッパーが読む（ファイルには書かない）
  - このフォルダで  claude  を起動すると hooks（復元・鍵ガード・Stop ゲート・同期）が有効になる
MSG
