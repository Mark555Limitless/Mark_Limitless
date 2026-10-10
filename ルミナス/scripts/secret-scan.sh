#!/usr/bin/env bash
# 共通の秘匿情報スキャナ。stdin のテキストから鍵・トークン・資格情報の代入らしき行を探す。
# 使い方: <テキスト> | scripts/secret-scan.sh [--quiet]
# 終了コード: 0=検知なし, 2=検知あり（該当箇所は [REDACTED] に置換して stderr に出す）
# 誤検知対策: 鍵の接頭辞は大小文字を区別し、前に英数字・ハイフン・アンダースコアが無いこと（risk-based 等を除外）。
set -u
QUIET="${1:-}"
B='(^|[^A-Za-z0-9_-])'
# 1) 形式がはっきりした鍵（大小文字区別）
P_KEYS="${B}(sk-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{10,}|sk-proj-[A-Za-z0-9_-]{10,}|xai-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|ya29\.[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
# 2) 明示的な代入（大小文字無視）: api_key = "....", password: ...., token=....
# 値の文字の集合: 括弧式の中の \ は文字そのもの（POSIX）なので、ハイフンは \- と書かず末尾に置く（\- だと \ から \ の範囲になり、ハイフン入りの値を見逃す）
P_ASSIGN='(api[_ -]?key|secret[_ -]?key|access[_ -]?token|auth[_ -]?token|client[_ -]?secret|password|passwd|pw)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_\\.@/+-]{10,}'
INPUT="$(cat)"
HITS="$( { printf '%s\n' "$INPUT" | grep -nE "$P_KEYS"; printf '%s\n' "$INPUT" | grep -nEi "$P_ASSIGN"; } 2>/dev/null | sort -t: -k1,1n -u | head -8 || true)"
[ -z "$HITS" ] && exit 0
if [ "$QUIET" != "--quiet" ]; then
  printf '%s\n' "$HITS" | sed -E "s#$P_KEYS#\1[REDACTED]#g" | sed -E "s#$P_ASSIGN#\1=[REDACTED]#Ig" | { if command -v python3 >/dev/null 2>&1 && python3 -c 'pass' </dev/null >/dev/null 2>&1; then PYTHONIOENCODING=utf-8 python3 -c 'import sys
for l in sys.stdin.buffer: print(l.decode("utf-8","replace").rstrip("\n")[:120])'; else cat; fi; } | sed 's/^/  /' >&2
fi
exit 2
