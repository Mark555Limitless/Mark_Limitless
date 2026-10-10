#!/usr/bin/env bash
# export-public.sh が作った使い捨てディレクトリだけを削除する（名前が luminous-public.* でなければ何もしない）
set -eu
P="${1:-}"
[ -n "$P" ] || { echo "使い方: $0 <export-public.sh の出力>" >&2; exit 2; }
# 相対パスは絶対パスにしてから上へたどる（dirname は "." で止まり、相対パスのままだと回り続ける）。根まで上がって見つからなければ終わる
case "$P" in /*) ;; *) P="$(pwd)/$P" ;; esac
TOP="$P"
while case "$(basename "$TOP")" in luminous-public.*) false;; *) true;; esac; do
  UP="$(dirname "$TOP")"; [ "$UP" = "$TOP" ] && break; TOP="$UP"
done
case "$(basename "$TOP")" in luminous-public.??????) rm -rf -- "$TOP"; echo "cleanup-public: 削除 $TOP" >&2;; *) echo "cleanup-public: luminous-public.* ではないため削除しません: $P" >&2; exit 3;; esac
