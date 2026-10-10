#!/usr/bin/env bash
# 管理対象（obsidian/ルミナス.md, CHARTER.md, ROUTINE.md, digest/YYYY-MM-DD.md）を Obsidian vault の「ルミナス/」へ複製する。
# 条件: LUMINOUS_OBSIDIAN_DIR が絶対パスで、$VAULT/.obsidian が存在（Obsidian の vault であることの確認）。未設定なら何もしない。
# vault 側で編集されていた（前回この同期が書いた内容と複製先が違う）場合は、複製先を <name>.vault-edit-<時刻>.md に退避してから上書きし、警告する。
# 前回書いた内容は vault 側の $DEST/.luminous-sync-sums に cksum で記録する。記録が無いときは、内容が違えば vault 側の編集とみなして退避する（時刻は使わない。時刻は iCloud・Obsidian Sync・git で変わるため）。
# 作れない・退避できない・複製できないものがあれば「失敗」と書いて exit 1（SessionEnd のログに残り、次回 SessionStart で警告される）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VAULT="${LUMINOUS_OBSIDIAN_DIR:-}"
if [ -z "$VAULT" ]; then echo "sync-obsidian: LUMINOUS_OBSIDIAN_DIR 未設定のためスキップ（scripts/setup.sh の案内を参照）"; exit 0; fi
case "$VAULT" in /*) ;; *) echo "sync-obsidian: LUMINOUS_OBSIDIAN_DIR は絶対パスにしてください: $VAULT" >&2; exit 1;; esac
if [ ! -d "$VAULT/.obsidian" ] && [ "${LUMINOUS_OBSIDIAN_FORCE:-0}" != "1" ]; then
  echo "sync-obsidian: $VAULT に .obsidian が無く Obsidian の vault と確認できません（確信があれば LUMINOUS_OBSIDIAN_FORCE=1）" >&2; exit 1
fi
DEST="$VAULT/ルミナス"
mkdir -p "$DEST/digest" || { echo "sync-obsidian: 失敗: $DEST/digest を作れません（権限・空き容量・iCloud・macOS のプライバシー設定を確認）" >&2; exit 1; }
SUMS="$DEST/.luminous-sync-sums"   # 1 行に「<名前> <cksum>-<バイト数>」
sum_of() { cksum < "$1" 2>/dev/null | awk '{print $1 "-" $2}'; }
last_sum() { awk -v k="$1" '$1==k{v=$2} END{print v}' "$SUMS" 2>/dev/null; }
record() { { awk -v k="$1" '$1!=k' "$SUMS" 2>/dev/null; echo "$1 $(sum_of "$2")"; } > "$SUMS.tmp.$$" && mv -f "$SUMS.tmp.$$" "$SUMS"; }
fail=0   # copy_one より前に置く（set -u のもとで未定義だと止まる）
copy_one() { # $1=複製元 $2=vault の「ルミナス/」からの名前
  local src="$1" key="$2" dst="$DEST/$2" last bak edited=0
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then [ -n "$(last_sum "$key")" ] || record "$key" "$dst"; return 0; fi   # 同じ内容なら書かない
  if [ -f "$dst" ]; then
    last="$(last_sum "$key")"
    if [ -n "$last" ]; then [ "$(sum_of "$dst")" != "$last" ] && edited=1          # 前回書いた内容から変わっている＝vault 側の編集
    else edited=1; fi   # 記録が無い（初回・切替の直後）ときは、内容が違うだけで vault 側の編集とみなして退避する（pull 直後は repo の時刻の方が新しく、時刻では見逃す）
  fi
  if [ "$edited" = 1 ]; then
    bak="${dst%.md}.vault-edit-$(date +%Y%m%d-%H%M%S).md"
    cp -p "$dst" "$bak" 2>/dev/null   # 成否は中身の一致で見る（Mac の cp -p は属性を移せないと、複製できていても 1 を返すことがある）
    if cmp -s "$dst" "$bak"; then echo "sync-obsidian: 警告: vault 側で編集されていたため退避しました → $(basename "$bak")"
    else echo "sync-obsidian: 失敗: vault 側の編集を退避できないため上書きしません → $key" >&2; fail=$((fail+1)); return 1; fi
  fi
  cp -f "$src" "$dst" || { echo "sync-obsidian: 失敗: 複製できません → $key" >&2; fail=$((fail+1)); return 1; }
  record "$key" "$dst"
}
n=0
for f in "$ROOT/obsidian/ルミナス.md" "$ROOT/CHARTER.md" "$ROOT/ROUTINE.md"; do [ -f "$f" ] && copy_one "$f" "$(basename "$f")" && n=$((n+1)); done
for f in "$ROOT"/digest/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md; do [ -f "$f" ] && copy_one "$f" "digest/$(basename "$f")" && n=$((n+1)); done
echo "sync-obsidian: $(date -u +%Y-%m-%dT%H:%MZ) → ${DEST}（$n 件）"
[ "$fail" = 0 ] || { echo "sync-obsidian: 失敗 $fail 件（退避・複製できなかったものは上書きしていません）" >&2; exit 1; }
