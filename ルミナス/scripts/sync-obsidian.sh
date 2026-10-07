#!/usr/bin/env bash
# 管理対象（obsidian/ルミナス.md, CHARTER.md, ROUTINE.md, digest/YYYY-MM-DD.md）を Obsidian vault の「ルミナス/」へ複製する。
# 条件: LUMINOUS_OBSIDIAN_DIR が絶対パスで、$VAULT/.obsidian が存在（Obsidian の vault であることの確認）。未設定なら何もしない。
# vault 側で編集されていた（複製先の方が新しく内容が違う）場合は、複製先を <name>.vault-edit-<時刻>.md に退避してから上書きし、警告する。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VAULT="${LUMINOUS_OBSIDIAN_DIR:-}"
if [ -z "$VAULT" ]; then echo "sync-obsidian: LUMINOUS_OBSIDIAN_DIR 未設定のためスキップ（scripts/setup.sh の案内を参照）"; exit 0; fi
case "$VAULT" in /*) ;; *) echo "sync-obsidian: LUMINOUS_OBSIDIAN_DIR は絶対パスにしてください: $VAULT" >&2; exit 1;; esac
if [ ! -d "$VAULT/.obsidian" ] && [ "${LUMINOUS_OBSIDIAN_FORCE:-0}" != "1" ]; then
  echo "sync-obsidian: $VAULT に .obsidian が無く Obsidian の vault と確認できません（確信があれば LUMINOUS_OBSIDIAN_FORCE=1）" >&2; exit 1
fi
DEST="$VAULT/ルミナス"; mkdir -p "$DEST/digest"
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }
copy_one() { # $1=src $2=dst
  local src="$1" dst="$2"
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst" && [ "$(mtime "$dst")" -gt "$(mtime "$src")" ]; then
    local bak="${dst%.md}.vault-edit-$(date +%Y%m%d-%H%M%S).md"; cp -p "$dst" "$bak"
    echo "sync-obsidian: 警告: vault 側で編集されていたため退避しました → $(basename "$bak")"
  fi
  cp -f "$src" "$dst"
}
n=0
for f in "$ROOT/obsidian/ルミナス.md" "$ROOT/CHARTER.md" "$ROOT/ROUTINE.md"; do [ -f "$f" ] && copy_one "$f" "$DEST/$(basename "$f")" && n=$((n+1)); done
for f in "$ROOT"/digest/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md; do [ -f "$f" ] && copy_one "$f" "$DEST/digest/$(basename "$f")" && n=$((n+1)); done
echo "sync-obsidian: $(date -u +%Y-%m-%dT%H:%MZ) → $DEST（$n 件）"
