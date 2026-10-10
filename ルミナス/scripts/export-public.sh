#!/usr/bin/env bash
# 公開可（docs/external-allowlist.txt）のパスだけを、push 済みのコミットから使い捨てディレクトリに書き出し、そのパスを出力する。
# 外部AIの CLI はこのディレクトリで起動する（送出の単位は「外部AIが読めるもの全部」。VIRTUAL_MARK §6）。
# 片付けは呼び出し側が scripts/cleanup-public.sh <出力されたパス> で行う。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "export-public: git リポジトリではありません" >&2; exit 2; }
# push 済みの上流があればそれを、無ければ HEAD を使う（未 push の変更は外へ出さない）
if REF="$(git -C "$ROOT" rev-parse --verify -q '@{u}' 2>/dev/null)"; then SRC="上流（push 済み）"; else REF="HEAD"; SRC="HEAD（上流なし）"; fi
OUT="$(mktemp -d "${TMPDIR:-/tmp}/luminous-public.XXXXXX")"
CR="$(printf '\r')"
while IFS= read -r p || [ -n "$p" ]; do   # 最終行に改行が無くても読む
  p="${p%"$CR"}"                           # CRLF の許可リストでも末尾の \r をパスに残さない
  case "$p" in ''|\#*) continue;; esac
  # 上流に無いパスがあっても止まらないよう 1 件ずつ書き出す
  git -C "$ROOT" archive "$REF" -- "$p" 2>/dev/null | tar -x -C "$OUT" 2>/dev/null || true
done < "$ROOT/docs/external-allowlist.txt"
# git archive はサブフォルダから実行するとそのフォルダ基準のパスで書き出す
DIR="$OUT"
if [ -z "$(ls -A "$DIR")" ]; then echo "export-public: 書き出せませんでした（allowlist のパスが $REF に無い）。空の $OUT が残っています" >&2; exit 3; fi
echo "export-public: $SRC から $(find "$DIR" -type f | wc -l | tr -d ' ') ファイルを書き出し → $OUT" >&2
printf '%s\n' "$DIR"
