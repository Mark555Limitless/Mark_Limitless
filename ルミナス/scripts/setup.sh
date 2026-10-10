#!/usr/bin/env bash
# 一度だけ実行: git フック（pre-commit / pre-push）の有効化と docx 生成用の依存。鍵は扱わない。
set -eu
# HERE と TOP は両方とも実体パスにそろえる（pwd は記号リンクを残すが git は実体を返す。Mac の /tmp→/private/tmp・
# クラウドのフォルダへのリンクなどで文字列の前方一致が外れると "./.githooks" を設定してしまい、鍵の検査が黙って効かなくなる）。
# 根からの相対（REL）は git 自身に聞く（bash の pwd -P は大文字小文字を打ったままにするので、APFS ではそれでも外れうる）
HERE="$(cd "$(dirname "$0")/.." && pwd -P)"
chmod +x "$HERE"/scripts/*.sh "$HERE"/.claude/hooks/*.sh "$HERE"/.githooks/* 2>/dev/null || true
HOOKS_NG=0
if git -C "$HERE" rev-parse --show-toplevel >/dev/null 2>&1; then
  TOP="$(cd "$(git -C "$HERE" rev-parse --show-toplevel)" && pwd -P)"
  REL="$(git -C "$HERE" rev-parse --show-prefix)"; REL="${REL%/}"; [ -n "$REL" ] || REL="."
  git -C "$TOP" config core.hooksPath "$REL/.githooks"
  # 設定したフックが本当に使われるかを git に聞いて確かめてから「有効化」と出す
  HP="$(cd "$HERE" && git rev-parse --git-path hooks)"
  if (cd "$HERE" && [ -x "$HP/pre-commit" ] && [ -x "$HP/pre-push" ]); then
    echo "git フックを有効化: core.hooksPath=$REL/.githooks（pre-commit / pre-push で鍵を検査）"
  else
    echo "!!! git フックを有効化できませんでした（$HP に実行できる pre-commit / pre-push がありません）。鍵の検査が効いていません" >&2; HOOKS_NG=1
  fi
else
  echo "git リポジトリではないため git フックは未設定（git init 後に再実行）"
fi
# Python の仮想環境（orch・tests 用。requests・python-dotenv・pytest）
if command -v python3 >/dev/null 2>&1; then
  [ -x "$HERE/.venv/bin/python" ] || python3 -m venv "$HERE/.venv"
  "$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt" && echo "Python 仮想環境を用意（.venv）"
fi
if command -v npm >/dev/null 2>&1; then
  (cd "$HERE" && npm install --no-audit --no-fund >/dev/null 2>&1 && echo "npm 依存を導入（docx 生成）") || echo "npm install に失敗（docx 生成は手動で）"
fi
cat <<'MSG'
次に行うこと（Mark 本人）:
  - Obsidian へ同期するなら、.claude/settings.local.json の "env" に LUMINOUS_OBSIDIAN_DIR（vault の絶対パス）を書く（例は .claude/settings.local.json.example。git 管理外）。デスクトップアプリから開いたセッションの hooks には .zshrc の export が届かないことがあるので、シェルの export だけに頼らない
  - Codex は ChatGPT アプリ（Codex 同梱）にログイン済みであること
  - Gemini / Jev の鍵は  bash tools/set_env_key.sh GEMINI_API_KEY  /  bash tools/set_env_key.sh TYPESAFE_API_KEY  で .env（600・git 管理外）に入れる。チャットには貼らない
  - 点検:  .venv/bin/python -m orch.health
  - このフォルダで  claude  を起動すると hooks（復元・鍵ガード・Stop ゲート・同期）が有効になる
MSG
[ "$HOOKS_NG" = 0 ] || exit 1
