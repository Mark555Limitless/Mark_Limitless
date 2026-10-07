#!/usr/bin/env bash
# hooks・スキャナ・同期の再現テスト（憲章 I-3: 実測を再現可能に）。使い捨てディレクトリだけに書き込む。
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T="${TMPDIR:-/tmp}/luminous-test-$$"; mkdir -p "$T"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
# 偽の鍵は実行時に組み立てる（ファイル本文に鍵の形を置かない。置くと自分の pre-commit に止められる）
FAKE_KEY="sk""-FAKEFAKEFAKEFAKEFAKEFAKE1234567"
ok() { pass=$((pass+1)); echo "PASS $1"; }
ng() { fail=$((fail+1)); echo "FAIL $1"; }
expect() { # $1=説明 $2=期待exit $3...=コマンド
  local d="$1" e="$2"; shift 2; "$@" >/dev/null 2>&1; local r=$?; [ "$r" = "$e" ] && ok "$d (exit $r)" || ng "$d (exit $r, expect $e)"; }

# 1) スキャナ
expect "scanner: 平文は通る" 0 bash -c "printf 'risk-based-evaluation-framework\nhello\n' | bash '$HERE/scripts/secret-scan.sh' --quiet"
expect "scanner: sk- 形式の鍵を検知" 2 bash -c "printf 'K=%s\n' '$FAKE_KEY' | bash '$HERE/scripts/secret-scan.sh' --quiet"
expect "scanner: password= 代入を検知" 2 bash -c "printf 'db_password = \"SuperSecretValue123\"\n' | bash '$HERE/scripts/secret-scan.sh' --quiet"

# 2) 作業用の仮リポジトリ（hooks を複製）
R="$T/repo"; mkdir -p "$R"; cp -R "$HERE/.claude" "$HERE/scripts" "$HERE/.githooks" "$R/"; cp "$HERE/CHARTER.md" "$HERE/ROUTINE.md" "$R/"; mkdir -p "$R/state" "$R/digest" "$R/obsidian" "$R/prompts"
cp "$HERE/obsidian/ルミナス.md" "$R/obsidian/"; cp "$HERE/prompts/ルミナス_最終プロンプト.md" "$R/prompts/"; printf '# HANDOVER\n\n## 節1\n- a\n- b\n- c\n' > "$R/HANDOVER.md"
git -C "$R" init -q; git -C "$R" -c user.email=t@t -c user.name=t add -A >/dev/null; git -C "$R" -c user.email=t@t -c user.name=t commit -q -m init
export CLAUDE_PROJECT_DIR="$R"

# 3) PreToolUse ガード
printf 'TOKEN=%s\n' "$FAKE_KEY" > "$R/leak.txt"
expect "guard: git add -A && git commit を検知" 2 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"git add -A && git commit -m x\"}}' | bash '$R/.claude/hooks/guard-secrets.sh'"
expect "guard: git -c k=v commit を検知" 2 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"git -c a=b commit -am x\"}}' | bash '$R/.claude/hooks/guard-secrets.sh'"
expect "guard: git 以外は素通し" 0 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"ls -la\"}}' | bash '$R/.claude/hooks/guard-secrets.sh'"
rm -f "$R/leak.txt"
expect "guard: 漏洩なしなら通る" 0 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"git commit -m x\"}}' | bash '$R/.claude/hooks/guard-secrets.sh'"

# 4) git pre-commit
git -C "$R" config core.hooksPath .githooks
printf 'api_key = \"abcdefghijklmnop123\"\n' > "$R/bad.txt"; git -C "$R" add bad.txt
expect "pre-commit: 鍵入りコミットを拒否" 1 git -C "$R" -c user.email=t@t -c user.name=t commit -q -m bad
git -C "$R" rm -q --cached bad.txt; rm -f "$R/bad.txt"

# 5) SessionStart → Stop ゲート
SID='{"session_id":"test-1","source":"startup"}'
expect "restore: 実行できる" 0 bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'"
bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | grep -q '始源の目的' && ok "restore: 憲章を注入" || ng "restore: 憲章を注入"
bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | grep -q '## 4\.' && ok "restore: 禁止事項（§4）も注入" || ng "restore: §4 注入"
LC_ALL=C bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | python3 -c 'import sys; sys.stdin.buffer.read().decode("utf-8")' 2>/dev/null && ok "restore: C ロケールでも UTF-8 を壊さない" || ng "restore: UTF-8 が壊れている"
[ "$(bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | python3 -c 'import sys; print(len(sys.stdin.buffer.read().decode("utf-8","replace")))')" -le 8700 ] && ok "restore: 注入量が上限内" || ng "restore: 注入量が上限超え"
sleep 1
OUT="$(printf '%s' '{"session_id":"test-1","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh")"
printf '%s' "$OUT" | grep -q '"block"' && ok "stop-gate: 未更新ならブロック" || ng "stop-gate: 未更新ならブロック"
TODAY="$(TZ=Asia/Tokyo date +%Y-%m-%d)"; printf '# d\n## 10:00\n- a\n- b\n- c\n' > "$R/digest/$TODAY.md"; touch "$R/HANDOVER.md" "$R/obsidian/ルミナス.md"
OUT="$(printf '%s' '{"session_id":"test-1","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh")"
[ -z "$OUT" ] && ok "stop-gate: 3 ファイル更新後は許可" || ng "stop-gate: 更新後は許可 ($OUT)"
OUT="$(printf '%s' '{"session_id":"test-1","stop_hook_active":false}' | FABLE5_HEADLESS=1 bash "$R/.claude/hooks/stop-gate.sh")"
[ -z "$OUT" ] && ok "stop-gate: 無人実行（FABLE5_HEADLESS=1）では止めない" || ng "stop-gate: headless"
OUT="$(printf '%s' '{"session_id":"test-2","stop_hook_active":true}' | bash "$R/.claude/hooks/stop-gate.sh")"
[ -z "$OUT" ] && ok "stop-gate: stop_hook_active なら許可" || ng "stop-gate: stop_hook_active"
OUT="$(LUMINOUS_STOP_GATE=off bash -c "printf '%s' '{\"session_id\":\"test-1\",\"stop_hook_active\":false}' | bash '$R/.claude/hooks/stop-gate.sh'")"
printf '%s' "$OUT" | grep -q 'STOP_GATE=off' && ok "stop-gate: off でも理由が無ければブロック" || ng "stop-gate: off 理由必須"

# 6) Obsidian 同期（vault 側編集の退避）
V="$T/vault"; mkdir -p "$V/.obsidian"
expect "sync: 相対パスは拒否" 1 env LUMINOUS_OBSIDIAN_DIR=. bash "$R/scripts/sync-obsidian.sh"
expect "sync: .obsidian が無ければ拒否" 1 env LUMINOUS_OBSIDIAN_DIR="$T/notvault" bash -c "mkdir -p '$T/notvault'; bash '$R/scripts/sync-obsidian.sh'"
expect "sync: 正常" 0 env LUMINOUS_OBSIDIAN_DIR="$V" bash "$R/scripts/sync-obsidian.sh"
sleep 1; printf 'edited in vault\n' > "$V/ルミナス/ROUTINE.md"
env LUMINOUS_OBSIDIAN_DIR="$V" bash "$R/scripts/sync-obsidian.sh" | grep -q '退避' && ls "$V/ルミナス"/ROUTINE.vault-edit-*.md >/dev/null 2>&1 && ok "sync: vault 側の編集を退避してから上書き" || ng "sync: 退避"


# 7) 保護ファイルへの Bash 書き込み・鍵ファイル読み取り・git フック迂回
gp() { printf '%s' "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")}}" | bash "$R/.claude/hooks/guard-protected.sh" >/dev/null 2>&1; echo $?; }
[ "$(gp "sed -i 's/a/b/' CHARTER.md")" = 2 ] && ok "guard-protected: sed -i で憲章を書き換えるのを止める" || ng "guard-protected: sed -i"
[ "$(gp "python3 -c 'open(\"CLAUDE.md\",\"w\")'")" = 2 ] && ok "guard-protected: python での書き換えを止める" || ng "guard-protected: python"
[ "$(gp "cat .claude/settings.local.json")" = 2 ] && ok "guard-protected: 鍵ファイルの Bash 読み取りを止める" || ng "guard-protected: secret read"
[ "$(gp "git commit --no-verify -m x")" = 2 ] && ok "guard-protected: --no-verify を止める" || ng "guard-protected: --no-verify"
[ "$(gp "cat CHARTER.md")" = 0 ] && ok "guard-protected: 読み取りは通す" || ng "guard-protected: read"
[ "$(gp "git add CHARTER.md && git commit -m x")" = 0 ] && ok "guard-protected: 通常のコミットは通す" || ng "guard-protected: commit"
[ "$(gp "cat .env")" = 2 ] && ok "guard-protected: .env の Bash 読み取りを止める" || ng "guard-protected: .env"
[ "$(gp "cat .env.example")" = 0 ] && ok "guard-protected: .env.example は読める" || ng "guard-protected: .env.example"
for v in ".env.test" ".env.staging" ".env.backup" ".envrc" "../ルミナス_非公開/env_backups/.env.bak.1"; do
  [ "$(gp "cat $v")" = 2 ] && ok "guard-protected: $v の読み取りを止める" || ng "guard-protected: $v"
done

# 8) 外部AI用の書き出し（公開可・push 済みだけ）
printf 'README.md\nCHARTER.md\n' > "$R/allow.tmp"; mkdir -p "$R/docs"; mv "$R/allow.tmp" "$R/docs/external-allowlist.txt"
printf 'private\n' > "$R/state/private.md"; git -C "$R" add -A >/dev/null; git -C "$R" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -q -m add
cp "$HERE/scripts/export-public.sh" "$HERE/scripts/cleanup-public.sh" "$R/scripts/"
PUB="$(bash "$R/scripts/export-public.sh" 2>/dev/null)"
[ -f "$PUB/CHARTER.md" ] && [ ! -e "$PUB/state" ] && ok "export-public: 許可リストだけを書き出す" || ng "export-public: 書き出し"
bash "$R/scripts/cleanup-public.sh" "$PUB" 2>/dev/null; [ ! -e "$PUB" ] && ok "cleanup-public: 使い捨てディレクトリを削除" || ng "cleanup-public"
expect "cleanup-public: 対象外のパスは消さない" 3 bash "$R/scripts/cleanup-public.sh" "$R"

echo "---- $pass passed, $fail failed"
[ "$fail" = 0 ]
