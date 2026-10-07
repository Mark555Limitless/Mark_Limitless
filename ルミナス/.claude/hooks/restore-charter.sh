#!/usr/bin/env bash
# SessionStart hook: 「探偵アニの号令」の現実化。
# セッション開始・再開・圧縮後に、憲章の要約と直近状態をコンテキストへ注入する。
# stdout はそのまま Claude のコンテキストに追加される（exit 0）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
CHARTER="$ROOT/CHARTER.md"
LATEST="$ROOT/state/latest.md"
ROUTINE="$ROOT/ROUTINE.md"
mkdir -p "$ROOT/state" && date +%s > "$ROOT/state/.session-start"   # Stop hook の判定基準

echo "=== ルミナス憲章の復元（SessionStart hook） ==="
if [ -f "$CHARTER" ]; then
  # 「1. 始源の目的」「2. 不変条件」の 2 節だけを、太字記号を外して注入する
  awk '/^## 1\./ {p=1} /^## 3\./ {p=0} p && !/^$/ {print}' "$CHARTER" | sed -E 's/\*\*//g; s/^- (I-[0-9]+) /\1 /'
else
  echo "警告: $CHARTER が見つかりません。憲章の所在を確認してください。"
fi

echo
echo "=== 直近状態（state/latest.md 先頭） ==="
if [ -f "$LATEST" ]; then
  head -n 12 "$LATEST"
else
  echo "（latest.md なし。新規セッションとして開始）"
fi
echo
echo "=== ROUTINE §1 開始時チェックリスト ==="
if [ -f "$ROUTINE" ]; then
  awk '/^## 1\./ {p=1; next} /^## 2\./ {p=0} p && /^- \[ \]/ {print}' "$ROUTINE"
fi
echo
echo "=== 最新 digest ==="
LATEST_DIGEST="$(ls -1 "$ROOT"/digest/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md 2>/dev/null | sort | tail -n 1)"
if [ -n "$LATEST_DIGEST" ]; then
  echo "($(basename "$LATEST_DIGEST"))"; head -n 10 "$LATEST_DIGEST"
else
  echo "（digest なし）"
fi
echo
echo "終了前に書くもの: digest/$(date +%Y-%m-%d).md と state/latest.md（Stop hook が未更新なら停止を止める）。ROUTINE §3 参照。"
echo "手順: 憲章 → latest.md → 直近の判断の自己点検（1分）→ 未解決事項から再開。全文は CHARTER.md を参照。"
exit 0
