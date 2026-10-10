# 提案: 全体停止 B（hooks・権限の設定）— 差分の案

> `docs/specs/20261008_global_halt.md` の B。保護ファイル（`.claude/`・`ROUTINE.md`・`scripts/test-hooks.sh`）を変えるため、**Mark が差分の文面を見て承認した後に、司令塔が適用する**（CLAUDE.md「変更の進め方」・憲章 §4）。
> 状態: **適用済み（2026-10-10）**。Mark がチャットで「B を適用してよい」と承認 → 司令塔が適用 → `scripts/test-hooks.sh` 112 件通過 → Opus 審査 APPROVE（軽 1・任意 4 を反映して再確認も APPROVE）。
> 提案からの差（審査で妥当と確認）: (1) `settings.json` のコマンドは `exec … || exit 2` ではなく「halt-guard.sh を呼び、0 以外なら 2」（スクリプトが無いとき 127 で素通しにならないため）。(2) deny は既存に合わせ `Edit(/data/.luminous_halt)` と `**/data/.luminous_halt` の両方。(3) canary は先頭が `true luminous-hook-canary` のコマンドだけ断る。(4) 許可の一覧に KillShell・KillBash（古い版の停止の道具名）。(5) guard-protected は `bash tools/luminous_halt.sh on|status`（1 行・`; | & < > $( )` バッククォートなし）を通す。
> 元の案: A（`tools/`・`orch/`・`tests/`）の Opus 審査が APPROVE になってから進める。適用の後、Mac のルミナスのフォルダで新しいセッションを開き、実際に止まることを確かめる（hooks は開始時に読み込まれる）。

## 0. 何が変わるか（Mark 向けの要約）

- Mac で `bash tools/luminous_halt.sh on 理由` と打つと、その Mac の Claude Code は次の道具の呼び出しから、読むだけの道具（Read・Grep・Glob）と「止める・質問する」道具（TaskStop・AskUserQuestion）以外を使えなくなる。Bash も Edit も Web も、サブエージェントの起動も止まる
- 印は AI 側（Edit・Write・Bash）から消せない。消すのは Mark が端末で `off`
- 停止中は、終了の関門（digest を書け）で閉じ込めない。開始時には大きく表示する
- 効くのは **その Mac の中だけ**。クラウドのセッションは、アプリの画面で止める

## 1. 新設: `.claude/hooks/halt-guard.sh`

```bash
#!/usr/bin/env bash
# PreToolUse（すべての道具）: 全体停止の印（data/.luminous_halt）があれば、読むだけの道具と「止める・質問」以外を止める。
# JSON を読む前にまず印を見る。印があれば、その後のどの失敗（jq なし・壊れた入力・未定義変数）でも終了 2（止める）。
# 無人実行（FABLE5_HEADLESS=1）でも素通しにしない。timeout は止める側の仕組みとして扱わない（印の確認は settings.json のコマンドの先頭にもある）。
# canary: 印が無くても `true luminous-hook-canary` という Bash のコマンドだけは常に断る（hooks が効いているかを司令塔が確かめるため。docs/proposals/20261008-autonomy-grants.md §3.1）
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
HALT="$ROOT/data/.luminous_halt"
if [ -e "$HALT" ] || [ -L "$HALT" ]; then
  set +e
  INPUT="$(cat 2>/dev/null)"
  TOOL=""
  if command -v jq >/dev/null 2>&1; then TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
  elif command -v python3 >/dev/null 2>&1; then TOOL="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))' 2>/dev/null)"; fi
  case "$TOOL" in Read|Grep|Glob|TaskStop|AskUserQuestion) exit 0 ;; esac
  REASON="$(head -n 1 "$HALT" 2>/dev/null | tr -d '\000-\037\177' | cut -c1-600)"
  echo "全体停止中（data/.luminous_halt）: ${REASON:-（理由なし）}。読むだけの道具と TaskStop・AskUserQuestion 以外は使えません。解除は Mark が端末で: bash tools/luminous_halt.sh off" >&2
  exit 2
fi
# 印が無いとき: canary だけ断る
set -u
INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then CMD="$(printf '%s' "$INPUT" | jq -r 'select(.tool_name=="Bash") | .tool_input.command // empty' 2>/dev/null)"
else CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command","") if d.get("tool_name")=="Bash" else "")' 2>/dev/null)"; fi
case "$CMD" in *luminous-hook-canary*) echo "canary: hooks は効いています（このコマンドは常に断ります）" >&2; exit 2 ;; esac
exit 0
```

## 2. `.claude/settings.json`

**PreToolUse の先頭に 1 項目を足す**（matcher は `*`。コマンドの中に印の確認を直接書く。スクリプトが消えた・壊れたときも止まる）
```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "command",
      "command": "bash -c 'P=\"$CLAUDE_PROJECT_DIR\"; if [ -e \"$P/data/.luminous_halt\" ] || [ -L \"$P/data/.luminous_halt\" ]; then exec bash \"$P/.claude/hooks/halt-guard.sh\" || { echo 全体停止中 >&2; exit 2; }; fi; exec bash \"$P/.claude/hooks/halt-guard.sh\"'",
      "timeout": 10
    }
  ]
}
```
注: 印があるときに `halt-guard.sh` が起動できなければ（127 など）`exit 2` で止める。印が無いときはスクリプトに任せる（canary）。

**permissions.deny に足す**（印を Edit・Write で消せないように。Bash は guard-protected で止める）
```json
"Edit(data/.luminous_halt)", "Write(data/.luminous_halt)", "Edit(**/data/.luminous_halt)", "Write(**/data/.luminous_halt)"
```

## 3. `.claude/hooks/guard-protected.sh`

`PROT` の正規表現に `luminous_halt` を足す（`tools/luminous_halt.sh` と `data/.luminous_halt` の両方に当たる。Bash での書き換え・削除を止める）:
```diff
-PROT='(CHARTER\.md|\.env\.example|VIRTUAL_MARK\.md|ROUTINE\.md|CLAUDE\.md|AGENTS\.md|最終プロンプト|\.claude/|\.codex/|\.githooks/|\.mcp\.json|secret-scan\.sh|sync-obsidian\.sh|build-final-prompt-docx\.mjs|package(-lock)?\.json)'
+PROT='(CHARTER\.md|\.env\.example|VIRTUAL_MARK\.md|ROUTINE\.md|CLAUDE\.md|AGENTS\.md|最終プロンプト|\.claude/|\.codex/|\.githooks/|\.mcp\.json|secret-scan\.sh|sync-obsidian\.sh|build-final-prompt-docx\.mjs|package(-lock)?\.json|luminous_halt)'
```
あわせて、2 回目の反証審査の指摘（`git tag`・`git config`・署名の操作）は許可台帳の提案で扱う（この差分には入れない）。

## 4. `.claude/hooks/stop-gate.sh`

停止中は終了を止めない（閉じ込めない）。`[ "${FABLE5_HEADLESS:-0}" = "1" ] && exit 0` の次の行に:
```bash
{ [ -e "$ROOT/data/.luminous_halt" ] || [ -L "$ROOT/data/.luminous_halt" ]; } && exit 0   # 全体停止中は終了を止めない（docs/specs/20261008_global_halt.md）
```

## 5. `.claude/hooks/restore-charter.sh`（SessionStart）

`_lib.sh` を読み込んだ直後に、停止中なら最初に大きく表示する（理由は「データ」。1 行・200 字・制御文字なし）:
```bash
if [ -e "$ROOT/data/.luminous_halt" ] || [ -L "$ROOT/data/.luminous_halt" ]; then
  echo "!!!!! 全体停止中（data/.luminous_halt）。外部AI・Codex・判断層・書き込みの道具は動きません。解除は Mark が端末で: bash tools/luminous_halt.sh off"
  echo "      理由（データ）: $(head -n 1 "$ROOT/data/.luminous_halt" 2>/dev/null | tr -d '\000-\037\177' | hook_trunc 200)"
fi
```

## 6. `.claude/hooks/session-end.sh`

停止中は docx の再生成を見送る。`RUNNING=0; hook_codex_running && RUNNING=1` の次に:
```bash
{ [ -e "$ROOT/data/.luminous_halt" ] || [ -L "$ROOT/data/.luminous_halt" ]; } && RUNNING=1   # 全体停止中も書き換えを見送る（記録への追記だけ）
```

## 7. `scripts/test-hooks.sh`

足す試験（使い捨てディレクトリで。本物の `data/` に印を作らない）:
- 印あり: Bash は終了 2／Edit は終了 2／Read・Grep・Glob・TaskStop・AskUserQuestion は終了 0
- 印あり・壊れた JSON を渡す → 終了 2／`PATH` から jq を外す → 終了 2
- 印がリンク（リンク先なし）→ 終了 2
- 印なし: 通常の Bash は 0／`true luminous-hook-canary` は 2
- `FABLE5_HEADLESS=1` でも印があれば 2
- stop-gate: 印があれば未更新でも 0
- session-end: 印があれば docx 再生成を見送る旨がログに出る

## 8. `ROUTINE.md` §5 の表に 1 行

| PreToolUse（すべての道具） | `.claude/hooks/halt-guard.sh` | 全体停止の印（`data/.luminous_halt`）があれば、読むだけの道具と TaskStop・AskUserQuestion 以外を止める。印は `bash tools/luminous_halt.sh on` で誰でも付けられ、消すのは Mark が端末で `off`。**終了の関門を外す `LUMINOUS_STOP_GATE=off` とは別物**（あちらは記録の催促を外すだけで、作業は止めない） |

## 9. 適用の手順

1. A の Opus 審査が APPROVE → A をコミット
2. Mark がこの差分を承認（チャットで「B を適用してよい」）
3. 司令塔が 1〜8 を適用し、`scripts/test-hooks.sh` を通し、Opus の審査（APPROVE）→ コミット・push
4. Mac のルミナスのフォルダで新しいセッションを開き、`bash tools/luminous_halt.sh on 試験` → Edit・Bash が止まることを確認 → Mark が `off` → 動くことを確認。結果を HANDOVER に書く（Phase 1 の門）

## 10. 残る点（指示書の「残る点」と同じ）

- 効くのはその機械の中だけ。クラウドはアプリの画面で止める。機械をまたぐ停止は Phase 2
- 停止の前に裏で起動した Bash・Monitor は動き続ける（TaskStop で止める）
- 今の 1 回の道具の呼び出しは止められない（次の呼び出しから）
