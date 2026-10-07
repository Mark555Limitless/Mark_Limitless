#!/usr/bin/env bash
# obsidian/*.md, digest/*.md, CHARTER.md, ROUTINE.md を Obsidian vault の「ルミナス/」へ複製する。
# vault の場所は環境変数 LUMINOUS_OBSIDIAN_DIR（.claude/settings.local.json の env で設定）。未設定なら何もしない。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VAULT="${LUMINOUS_OBSIDIAN_DIR:-}"
if [ -z "$VAULT" ]; then
  echo "sync-obsidian: LUMINOUS_OBSIDIAN_DIR 未設定のためスキップ（.claude/settings.local.json.example を参照）"
  exit 0
fi
if [ ! -d "$VAULT" ]; then
  echo "sync-obsidian: vault が見つかりません: $VAULT" >&2
  exit 1
fi
DEST="$VAULT/ルミナス"
mkdir -p "$DEST/digest"
cp -f "$ROOT"/obsidian/*.md "$DEST/" 2>/dev/null || true
rm -f "$DEST/README.md"   # obsidian/README.md は同期しない
cp -f "$ROOT"/digest/*.md "$DEST/digest/" 2>/dev/null || true
rm -f "$DEST/digest/README.md"
cp -f "$ROOT/CHARTER.md" "$ROOT/ROUTINE.md" "$DEST/"
echo "sync-obsidian: $(date -u +%Y-%m-%dT%H:%MZ) → $DEST（$(ls "$DEST" | wc -l | tr -d ' ') 件）"
