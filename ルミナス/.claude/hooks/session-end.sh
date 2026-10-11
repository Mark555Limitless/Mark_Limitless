#!/usr/bin/env bash
# SessionEnd hook: Obsidian 同期と最終プロンプト docx の再生成（md が変わったときだけ）。失敗は state/.session-end.log に残し、次回 SessionStart で警告する。
# Codex の実行中（data/codex_runs/.lock の持ち主が生きている）は、作業フォルダ内を書き換える処理（docx 再生成・記録の切り詰め）を見送り、
# 記録への追記だけを行う（実行中の書き換えは範囲検査で違反になるため。Obsidian 同期は作業フォルダの外へ書くので行う）。
# 全体停止中は、それに加えて Obsidian 同期も見送る（停止の原因かもしれない中身を vault へ広げない。解除後の SessionEnd で行う）。
# docx は、LUMINOUS_PRIVATE_DIR（非公開フォルダ。Mark の依頼 2026-10-11）にも写す。場所は環境変数だけから決め、リポジトリに Mac のパスを書かない。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
. "$ROOT/.claude/hooks/_lib.sh"
LOG="$ROOT/state/.session-end.log"
MD_REL='prompts/ルミナス_最終プロンプト.md'; DX_REL='☆ルミナス_最終プロンプト.docx'
DX_SRC="$ROOT/state/.sessions/docx.src"   # この clone で最後に docx を作ったときの md の cksum（git 管理外）
RUNNING=0; HALT=0; SKIP=""; hook_codex_running && { RUNNING=1; SKIP="Codex 実行中"; }
# Codex の違反の印・ロック（中断を含む）・入れ子の .git があるうちは、未審査の中身（build-final-prompt-docx.mjs・node_modules）で node を動かさず、
# 作業ツリーの docx を外へ写さない（Codex が書き換えた中身をサンドボックスの外で動かす・広げることになるため）
UNSETTLED=0; { hook_codex_unsettled || [ -n "$(hook_nested_git)" ]; } && UNSETTLED=1
{ [ -e "$ROOT/data/.luminous_halt" ] || [ -L "$ROOT/data/.luminous_halt" ]; } && { HALT=1; RUNNING=1; SKIP="${SKIP:+${SKIP}・}全体停止中"; }   # 全体停止中は書き換えも vault への同期も見送る（記録への追記だけ）
# docx が今の md から作ったものだと確かめられれば真（再生成を省く。docx は作るたびに時刻が入ってバイト列が変わり、追跡中のファイルを汚すため）。
# 確かめられなければ偽（作り直す。docx が md と食い違ったまま残らない側）。Codex の印・ロック・入れ子の .git があるときは、その前で見送る（UNSETTLED）。
# 限界: 記録（docx.src）が無い clone の初回は git の順序だけで判断するので、md の後にコミットされた古い docx を省くことがある（次に md が変われば作り直す）
docx_current() {
  local mc dc rec
  [ -z "$(hook_nested_git)" ] && ! hook_codex_unsettled || return 1
  hook_git -C "$ROOT" diff --no-ext-diff --quiet HEAD -- "$MD_REL" "$DX_REL" 2>/dev/null || return 1   # md も docx も作業ツリーで未変更
  mc="$(hook_git -C "$ROOT" -c log.showSignature=false log -1 --format=%H -- "$MD_REL" 2>/dev/null)"
  dc="$(hook_git -C "$ROOT" -c log.showSignature=false log -1 --format=%H -- "$DX_REL" 2>/dev/null)"
  case "$mc" in ""|*[!0-9a-f]*) return 1 ;; esac
  case "$dc" in ""|*[!0-9a-f]*) return 1 ;; esac
  # docx の最後のコミットが md の最後のコミットより後（子孫）であること。同じコミットで両方が変わったときは、どの md から作ったか分からないので作り直す
  [ "$mc" != "$dc" ] && hook_git -C "$ROOT" merge-base --is-ancestor "$mc" "$dc" 2>/dev/null || return 1
  # この clone で前に作ったときの md が今の md と違えば作り直す（古い md から作った docx が、md の後にコミットされたとき）。記録が無ければ git の判定だけ
  if [ -e "$DX_SRC" ] || [ -L "$DX_SRC" ]; then
    [ -f "$DX_SRC" ] && [ ! -L "$DX_SRC" ] || return 1
    rec="$(head -n 1 "$DX_SRC" 2>/dev/null)"
    [ -n "$rec" ] && [ "$rec" = "$(cksum < "$ROOT/$MD_REL" 2>/dev/null)" ] || return 1
  fi
  return 0
}
# 最終プロンプトの docx を非公開フォルダへ写す（中身が違うときだけ）。写さない条件: 未設定・相対パス・フォルダでない・このフォルダの中・写し先がリンク。
# 置き場の中身は読まない（docx の写し先のファイルを比べるだけ）。場所はログに書かない
copy_docx_private() {
  local priv="${LUMINOUS_PRIVATE_DIR:-}" real root src dst tmp
  [ -n "$priv" ] || return 0   # 未設定なら何もしない（写しは任意）。設定があるのに写せないときは「失敗」と書く（次の SessionStart が警告する）
  case "$priv" in /*) ;; *) echo "docx の写し 失敗（LUMINOUS_PRIVATE_DIR が絶対パスではない。~ は使えない）"; return 0 ;; esac
  [ -d "$priv" ] || { echo "docx の写し 失敗（LUMINOUS_PRIVATE_DIR のフォルダが無い）"; return 0; }
  real="$(cd "$priv" 2>/dev/null && pwd -P)" || { echo "docx の写し 失敗（LUMINOUS_PRIVATE_DIR のフォルダに入れない）"; return 0; }
  root="$(cd "$ROOT" 2>/dev/null && pwd -P)" || { echo "docx の写し 失敗（作業フォルダを確かめられない）"; return 0; }
  case "${real}/" in "${root}/"*) echo "docx の写し 失敗（LUMINOUS_PRIVATE_DIR がこのフォルダの中）"; return 0 ;; esac
  src="$ROOT/$DX_REL"; dst="${real}/$DX_REL"
  [ -f "$src" ] && [ ! -L "$src" ] || { echo "docx の写し 失敗（作業フォルダに docx が無い）"; return 0; }
  if [ -L "$dst" ] || { [ -e "$dst" ] && [ ! -f "$dst" ]; }; then echo "docx の写し 失敗（写し先が通常のファイルではない）"; return 0; fi
  [ -f "$dst" ] && cmp -s "$src" "$dst" && return 0
  tmp="$(mktemp "${real}/.luminous-docx.XXXXXX" 2>/dev/null)" || { echo "docx の写し 失敗（非公開フォルダへ書けない）"; return 0; }   # 名前を予測させない（先にリンクを置かれない）
  if cp "$src" "$tmp" 2>/dev/null && mv -f "$tmp" "$dst" 2>/dev/null; then echo "最終プロンプトの docx を非公開フォルダへ写しました"
  else rm -f "$tmp" 2>/dev/null; echo "docx の写し 失敗（非公開フォルダへ書けない）"; fi
  return 0
}
{
  echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ) SessionEnd"
  if [ "$HALT" = 1 ]; then
    echo "全体停止中のため Obsidian 同期を見送り（解除後の SessionEnd で行う）"
  else
    bash "$ROOT/scripts/sync-obsidian.sh" 2>&1 || echo "sync-obsidian 失敗"
  fi
  if [ "$RUNNING" = 1 ]; then
    echo "${SKIP}のため docx 再生成を見送り（次回の SessionEnd で行う）"
  elif [ "$UNSETTLED" = 1 ]; then
    echo "Codex の違反の印・ロック・入れ子の .git があるため docx 再生成を見送り（未審査の中身で node を動かさない。片付けた後の SessionEnd で行う）"
  elif docx_current; then
    echo "最終プロンプトに変更なし（docx 再生成を省略）"
  elif command -v node >/dev/null 2>&1; then
    MDSUM="$(cksum < "$ROOT/$MD_REL" 2>/dev/null)"
    if (cd "$ROOT" && node scripts/build-final-prompt-docx.mjs 2>&1); then
      # 作ったときの md を記録する（記号リンクの先は書き換えない）
      mkdir -p "$ROOT/state/.sessions" 2>/dev/null; rm -f "$DX_SRC" 2>/dev/null
      [ -n "$MDSUM" ] && printf '%s\n' "$MDSUM" > "$DX_SRC" 2>/dev/null
    else
      echo "docx 再生成 失敗（scripts/setup.sh を実行して docx 依存を入れる）"
    fi
  else
    echo "docx 再生成 失敗: node が無い"
  fi
  [ "$RUNNING" = 1 ] || [ "$UNSETTLED" = 1 ] || copy_docx_private   # 全体停止中・Codex の実行中・違反やロックが残るうちは外へ写さない
} >> "$LOG" 2>&1
if [ "$RUNNING" = 0 ]; then
  tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  hook_flush_escalations >> "$LOG" 2>&1   # Codex の実行中に保留したモデル切替の記録を移す
fi
exit 0
