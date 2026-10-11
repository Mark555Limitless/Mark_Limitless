#!/usr/bin/env bash
# hooks・スキャナ・同期の再現テスト（憲章 I-3: 実測を再現可能に）。使い捨てディレクトリだけに書き込む。
set -u
# 呼び出し元（.zshrc・settings.local.json の env）の値を持ち込まない（本物の vault へ書かない。ゲートの設定や無人実行の印で結果を変えない）
unset LUMINOUS_OBSIDIAN_DIR LUMINOUS_OBSIDIAN_FORCE LUMINOUS_STOP_GATE LUMINOUS_GATE_MODE LUMINOUS_TZ FABLE5_HEADLESS CLAUDE_PROJECT_DIR
# 利用者の git の設定（commit.gpgsign・全体の core.hooksPath など）を読まない（GIT_CONFIG_GLOBAL は git 2.32 以降）
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T="${TMPDIR:-/tmp}/luminous-test-$$"; mkdir -p "$T"
SAFE_TEST="$HOME/.cache/luminous-hooktest-$$"   # 保留の置き場は /tmp の外でなければ使われない
trap 'rm -rf "$T" "$SAFE_TEST"' EXIT
pass=0; fail=0
export LUMINOUS_SAFE_DIR="$SAFE_TEST"   # Codex が書けない置き場（保留中の記録など）をテスト用に差し替える
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
# 値にハイフンがあっても検知する（括弧式の中の \- はハイフンにならない罠）。値は実行時に組み立てる（本文に代入の形を置かない）
expect "scanner: ハイフン入りの password 代入を検知" 2 bash -c "printf 'password: %s\n' 'abc''-def-ghi-jkl-mno' | bash '$HERE/scripts/secret-scan.sh' --quiet"
expect "scanner: ハイフン入りの api_key 代入を検知" 2 bash -c "printf 'api_key = \"%s\"\n' 'abcd''-efgh-ijkl-mnop' | bash '$HERE/scripts/secret-scan.sh' --quiet"
expect "scanner: UUID 形の api_key 代入を検知" 2 bash -c "printf 'api_key=%s\n' '550e8400''-e29b-41d4-a716-446655440000' | bash '$HERE/scripts/secret-scan.sh' --quiet"
OUT="$(printf 'password: %s\n' 'abcdefghij''-klmnopq' | bash "$HERE/scripts/secret-scan.sh" 2>&1)"
printf '%s' "$OUT" | grep -q 'REDACTED' && ! printf '%s' "$OUT" | grep -q 'klmnopq' && ok "scanner: ハイフンの後ろも伏せる（値の一部を表示しない）" || ng "scanner: 伏せ字から値が漏れる"
expect "scanner: ハイフン入りの普通の文（鍵の代入ではない）は通る" 0 bash -c "printf 'see how-to-set-up-the-password-manager.md\n' | bash '$HERE/scripts/secret-scan.sh' --quiet"

# 2) 作業用の仮リポジトリ（hooks を複製）
R="$T/repo"; mkdir -p "$R"; cp -R "$HERE/.claude" "$HERE/scripts" "$HERE/.githooks" "$R/"; cp "$HERE/CHARTER.md" "$HERE/ROUTINE.md" "$R/"; mkdir -p "$R/state" "$R/digest" "$R/obsidian" "$R/prompts"
cp "$HERE/obsidian/ルミナス.md" "$R/obsidian/"; cp "$HERE/prompts/ルミナス_最終プロンプト.md" "$R/prompts/"; printf '# HANDOVER\n\n## 節1\n- a\n- b\n- c\n' > "$R/HANDOVER.md"
git -C "$R" init -q; git -C "$R" -c user.email=t@t -c user.name=t add -A >/dev/null; git -C "$R" -c user.email=t@t -c user.name=t commit -q -m init
git -C "$R" rev-parse -q --verify HEAD >/dev/null || { echo "FAIL 準備: 仮リポジトリの初期コミットに失敗（git の設定を確認）"; exit 1; }
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
# 4b) setup.sh: 記号リンク経由・リポジトリの下位フォルダでも、フックの場所を正しく設定する（Mac の /tmp→/private/tmp・リンクしたフォルダと同じ型）
N="$T/nest"; mkdir -p "$N/top/ルミナス"; cp -R "$HERE/scripts" "$HERE/.githooks" "$N/top/ルミナス/"; git -C "$N/top" init -q; ln -s "$N" "$T/nest-link"
SB="$T/setupbin"; mkdir -p "$SB"   # python3・npm の無い PATH（.venv と npm の段を飛ばす）
for c in bash env git dirname chmod cat; do p="$(command -v "$c")"; case "$p" in /*) ln -s "$p" "$SB/$c" ;; esac; done
expect "setup: 記号リンク経由・下位フォルダでもフックを有効化" 0 env PATH="$SB" bash "$T/nest-link/top/ルミナス/scripts/setup.sh"
printf 'ok\n' > "$N/top/ルミナス/clean.txt"; git -C "$N/top" add ルミナス/clean.txt
expect "setup 後: 鍵の無いコミットは通る" 0 git -C "$N/top" -c user.email=t@t -c user.name=t commit -q -m clean
printf 'api_key = \"abcdefghijklmnop123\"\n' > "$N/top/ルミナス/bad.txt"; git -C "$N/top" add ルミナス/bad.txt
expect "setup 後: pre-commit が鍵入りコミットを拒否（設定したフックが本当に効く）" 1 git -C "$N/top" -c user.email=t@t -c user.name=t commit -q -m bad
# 4c) setup.sh: git 管理外（クラウドからのコピー・zip の展開）では git init を勧めず、.venv と npm の段は続けてから失敗で終わる
NGD="$T/nongit/ルミナス"; mkdir -p "$NGD"; cp -R "$HERE/scripts" "$HERE/.githooks" "$NGD/"
SB2="$T/setupbin2"; mkdir -p "$SB2"; for c in bash env git dirname chmod cat; do [ -e "$SB/$c" ] && ln -s "$SB/$c" "$SB2/$c"; done
printf '#!/bin/sh
: > "%s"
exit 0
' "$T/npm-called" > "$SB2/npm"; chmod +x "$SB2/npm"   # 偽の npm（呼ばれたことだけ残す）
OUT="$(env PATH="$SB2" GIT_CEILING_DIRECTORIES="$T" bash "$NGD/scripts/setup.sh" 2>&1)"; RC=$?
[ "$RC" = 1 ] && printf '%s' "$OUT" | grep -q 'git init はしないこと' && printf '%s' "$OUT" | grep -q 'git clone した写しの ルミナス/' && [ ! -e "$NGD/.git" ] \
  && ok "setup: git 管理外では git init を勧めず失敗で終わる (exit $RC)" || ng "setup: git 管理外 (exit ${RC})"
[ -e "$T/npm-called" ] && ok "setup: git 管理外でも npm の段は止めない" || ng "setup: git 管理外で npm の段が止まった"
printf '%s' "$OUT" | grep -q 'true luminous-hook-canary' && printf '%s' "$OUT" | grep -q 'state/.sessions/' && ok "setup: 最後の案内に hooks が効いているかの確かめ方（canary・state/.sessions）がある" || ng "setup: 確かめ方の案内"
OUT="$(env PATH="$SB" bash "$T/nest-link/top/ルミナス/scripts/setup.sh" 2>&1)"
! printf '%s' "$OUT" | grep -q '!!!' && ok "setup: git の中では警告を出さない" || ng "setup: git の中で警告が出た"

# 5) SessionStart → Stop ゲート
SID='{"session_id":"test-1","source":"startup"}'
expect "restore: 実行できる" 0 bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'"
bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | grep -q '始源の目的' && ok "restore: 憲章を注入" || ng "restore: 憲章を注入"
bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | grep -q '## 4\.' && ok "restore: 禁止事項（§4）も注入" || ng "restore: §4 注入"
LC_ALL=C bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | python3 -c 'import sys; sys.stdin.buffer.read().decode("utf-8")' 2>/dev/null && ok "restore: C ロケールでも UTF-8 を壊さない" || ng "restore: UTF-8 が壊れている"
[ "$(bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | python3 -c 'import sys; print(len(sys.stdin.buffer.read().decode("utf-8","replace")))')" -le 8700 ] && ok "restore: 注入量が上限内" || ng "restore: 注入量が上限超え"
# Mark への伝え方 [伝]（Mark の指示 2026-10-11・恒久）: SessionStart の先頭と UserPromptSubmit で毎回注入する
bash -c "printf '%s' '$SID' | bash '$R/.claude/hooks/restore-charter.sh'" | head -n 4 | grep -q '^\[伝\] Mark への伝え方' && ok "restore: [伝] を先頭で注入" || ng "restore: [伝] の注入"
OUT="$(printf '%s' '{"session_id":"test-1","prompt":"x"}' | bash "$R/.claude/hooks/tell-rule.sh")"; RC=$?
[ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q '過程の説明は書かない' && printf '%s' "$OUT" | grep -q '省略せず' && ok "tell-rule: [伝] を注入 (exit $RC)" || ng "tell-rule: [伝] (exit ${RC})"
python3 -c 'import json,sys; h=json.load(open(sys.argv[1]))["hooks"]["UserPromptSubmit"]; assert any("tell-rule.sh" in x["command"] for e in h for x in e["hooks"])' "$R/.claude/settings.json" 2>/dev/null && ok "settings: UserPromptSubmit に tell-rule.sh" || ng "settings: UserPromptSubmit の登録"
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
# vault で編集した後に repo 側も更新された（Stop ゲートが毎回ハブノートの更新を求めるので普通に起きる）ときも、時刻ではなく内容で見て退避する
printf 'mark note\n' >> "$V/ルミナス/ルミナス.md"; sleep 1; printf -- '- 最新\n' >> "$R/obsidian/ルミナス.md"
env LUMINOUS_OBSIDIAN_DIR="$V" bash "$R/scripts/sync-obsidian.sh" >/dev/null 2>&1
grep -l 'mark note' "$V/ルミナス"/ルミナス.vault-edit-*.md >/dev/null 2>&1 && grep -q -- '- 最新' "$V/ルミナス/ルミナス.md" && ok "sync: vault の編集の後に repo が更新されても退避してから上書き" || ng "sync: vault 編集→repo 更新で退避されない"
n0="$(ls -A "$V/ルミナス" | wc -l | tr -d ' ')"; env LUMINOUS_OBSIDIAN_DIR="$V" bash "$R/scripts/sync-obsidian.sh" >/dev/null 2>&1
[ "$(ls -A "$V/ルミナス" | wc -l | tr -d ' ')" = "$n0" ] && ok "sync: 変化が無ければ退避を増やさない" || ng "sync: 変化なしで退避が増えた"
# 作れない・複製できないときは exit 1 と「失敗」（session-end.sh がログに残し、次回 SessionStart が警告する）
VF="$T/vaultfail"; mkdir -p "$VF/.obsidian"; : > "$VF/ルミナス"   # 複製先の「ルミナス」がファイル（フォルダを作れない）
expect "sync: 複製先を作れなければ exit 1" 1 env LUMINOUS_OBSIDIAN_DIR="$VF" bash "$R/scripts/sync-obsidian.sh"
env LUMINOUS_OBSIDIAN_DIR="$VF" bash "$R/scripts/sync-obsidian.sh" 2>&1 | grep -q '失敗' && ok "sync: 作れないときは『失敗』と書く" || ng "sync: 失敗の表示"
VC="$T/vaultcp"; mkdir -p "$VC/.obsidian" "$VC/ルミナス/digest" "$VC/ルミナス/CHARTER.md/CHARTER.md"   # CHARTER.md の場所がフォルダ（複製できない）
expect "sync: 1 件でも複製できなければ exit 1" 1 env LUMINOUS_OBSIDIAN_DIR="$VC" bash "$R/scripts/sync-obsidian.sh"
[ -f "$VC/ルミナス/ROUTINE.md" ] && ok "sync: 失敗があっても残りは複製する" || ng "sync: 失敗で残りが止まった"
# 記録（.luminous-sync-sums）が無く、vault 側の編集の方が古い（Mac に切り替えて pull した直後の形）: 時刻では見逃すので、内容が違えば退避する
V2="$T/vault2"; mkdir -p "$V2/.obsidian" "$V2/ルミナス"; printf 'old mark note\n' > "$V2/ルミナス/ルミナス.md"; touch -t 202001010000 "$V2/ルミナス/ルミナス.md"
env LUMINOUS_OBSIDIAN_DIR="$V2" bash "$R/scripts/sync-obsidian.sh" >/dev/null 2>&1
grep -l 'old mark note' "$V2/ルミナス"/ルミナス.vault-edit-*.md >/dev/null 2>&1 && grep -q -- '- 最新' "$V2/ルミナス/ルミナス.md" && ok "sync: 記録の無い初回でも、古い時刻の vault の編集を退避してから上書き" || ng "sync: 初回の退避（時刻で見逃し）"


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
# Mac の形: BSD の sed -i ''、APFS は既定で大文字小文字を区別しない（claude.md・.ENV・.Claude/ は CLAUDE.md・.env・.claude/ と同じファイル）
for c in "sed -i '' 's/a/b/' CHARTER.md" "sed -i '' 's/a/b/' charter.md" "echo x >> claude.md" "echo x > .Claude/hooks/stop-gate.sh" "cat .ENV" "cat .claude/Settings.Local.json" "CAT .env" "git -c core.hookspath=/dev/null commit -m x" "MV x CHARTER.md" "$(printf 'echo hi\nMV x CLAUDE.md')"; do
  [ "$(gp "$c")" = 2 ] && ok "guard-protected: Mac の形「$(printf '%s' "$c" | tr '\n' '/')」を止める" || ng "guard-protected: Mac の形 $c"
done
[ "$(gp "cat charter.md")" = 0 ] && ok "guard-protected: 小文字の名前でも読み取りは通す" || ng "guard-protected: 小文字の読み取り"
[ "$(gp "perl -MFile::Copy -e 'copy(\"x\",\"CHARTER.md\")'")" = 2 ] && ok "guard-protected: perl -M での書き換えは止めたまま（大文字小文字を区別しない判定でも外さない）" || ng "guard-protected: perl -M"
# 鍵ファイルを読む Mac の道具（pbcopy・open・hexdump・ditto）と cut・sort・tr・perl
for c in 'pbcopy < .env.local' 'open .env.local' 'hexdump -C .env.local' 'ditto .env.local x' 'cut -c1-80 .env.local' 'sort .env' 'tr -d x < .env' 'perl -ne print .env'; do
  [ "$(gp "$c")" = 2 ] && ok "guard-protected: $c を止める" || ng "guard-protected: $c"
done
for c in 'sort < .env.example' 'ls -la .env*' 'git status --short'; do
  [ "$(gp "$c")" = 0 ] && ok "guard-protected: $c は通す" || ng "guard-protected: $c"
done
# Mac（APFS）: NFD の「プ」（フ＋U+309A）で書いた最終プロンプトの名前も止める（C と UTF-8 のロケール）
NFD_PU="$(printf '\343\203\225\343\202\232')"; NFD_FP="prompts/ルミナス_最終${NFD_PU}ロン${NFD_PU}ト.md"
UL="$(locale -a 2>/dev/null | grep -iE '^(en_US|C)\.utf-?8$' | head -n 1)"
for loc in C $UL; do
  [ "$(LC_ALL=$loc gp "sed -i '' 's/a/b/' $NFD_FP")" = 2 ] && ok "guard-protected: NFD の最終プロンプトへの sed -i を止める（${loc}）" || ng "guard-protected: NFD の最終プロンプト（${loc}）"
done
[ "$(gp "sed -i '' 's/a/b/' prompts/ルミナス_最終プロンプト.md")" = 2 ] && ok "guard-protected: NFC の最終プロンプトへの sed -i を止める" || ng "guard-protected: NFC の最終プロンプト"
[ "$(gp "echo 最終確認のロングテキスト > notes.md")" = 0 ] && ok "guard-protected: 似た文字列（保護名ではない）は通す" || ng "guard-protected: 似た文字列"

# 8) 外部AI用の書き出し（公開可・push 済みだけ）
printf 'README.md\nCHARTER.md\n' > "$R/allow.tmp"; mkdir -p "$R/docs"; mv "$R/allow.tmp" "$R/docs/external-allowlist.txt"
printf 'private\n' > "$R/state/private.md"; git -C "$R" add -A >/dev/null; git -C "$R" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -q -m add
cp "$HERE/scripts/export-public.sh" "$HERE/scripts/cleanup-public.sh" "$R/scripts/"
PUB="$(bash "$R/scripts/export-public.sh" 2>/dev/null)"
[ -f "$PUB/CHARTER.md" ] && [ ! -e "$PUB/state" ] && ok "export-public: 許可リストだけを書き出す" || ng "export-public: 書き出し"
bash "$R/scripts/cleanup-public.sh" "$PUB" 2>/dev/null; [ ! -e "$PUB" ] && ok "cleanup-public: 使い捨てディレクトリを削除" || ng "cleanup-public"
expect "cleanup-public: 対象外のパスは消さない" 3 bash "$R/scripts/cleanup-public.sh" "$R"
# 許可リストが CRLF・最終行に改行なしでも全行読む（Mac・Windows のエディタで保存したとき）
printf 'CHARTER.md\r\nROUTINE.md' > "$R/docs/external-allowlist.txt"; git -C "$R" add -A >/dev/null; git -C "$R" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -q -m crlf
PUB="$(bash "$R/scripts/export-public.sh" 2>/dev/null)"
[ -n "$PUB" ] && [ -f "$PUB/CHARTER.md" ] && [ -f "$PUB/ROUTINE.md" ] && [ ! -e "$PUB/state" ] && ok "export-public: CRLF・最終行に改行なしの許可リストも全行読む" || ng "export-public: CRLF・最終行"
[ -n "$PUB" ] && bash "$R/scripts/cleanup-public.sh" "$PUB" 2>/dev/null
# 相対パスを渡されても回り続けずに終わる（対象外は消さない）。相対で指した使い捨てディレクトリは消す
expect "cleanup-public: 相対パスでも止まって消さない" 3 bash -c "cd '$R' && bash '$R/scripts/cleanup-public.sh' foo"
mkdir -p "$T/rel/luminous-public.abcdef/sub"
expect "cleanup-public: 相対パスの使い捨てディレクトリは消す" 0 bash -c "cd '$T' && bash '$R/scripts/cleanup-public.sh' rel/luminous-public.abcdef/sub"
[ ! -e "$T/rel/luminous-public.abcdef" ] && ok "cleanup-public: 相対パスで指したものを消した" || ng "cleanup-public: 相対パスで消えない"

# 9) Codex 実行中の編集ガード・SessionEnd の見送り・違反の印・入れ子の .git（git を使う前に検知）
LG() { printf '%s' "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$1\"}}" | bash "$R/.claude/hooks/codex-lock-guard.sh" >/dev/null 2>&1; echo $?; }
[ "$(LG "$R/HANDOVER.md")" = 0 ] && ok "lock-guard: Codex が動いていなければ通す" || ng "lock-guard: 未実行"
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
[ "$(LG "$R/HANDOVER.md")" = 2 ] && ok "lock-guard: 実行中はフォルダ内の編集を止める" || ng "lock-guard: 実行中"
[ "$(LG "$R/newdir/new.md")" = 2 ] && ok "lock-guard: まだ無いファイルも止める" || ng "lock-guard: 新規ファイル"
[ "$(LG "$T/outside.md")" = 0 ] && ok "lock-guard: フォルダの外は通す" || ng "lock-guard: フォルダの外"
bash "$R/.claude/hooks/session-end.sh" </dev/null >/dev/null 2>&1
grep -q '見送り' "$R/state/.session-end.log" 2>/dev/null && ok "session-end: Codex 実行中は docx 再生成を見送る" || ng "session-end: 実行中の見送り"
grep -q 'LUMINOUS_OBSIDIAN_DIR 未設定のためスキップ' "$R/state/.session-end.log" 2>/dev/null && ok "session-end: 試験では本物の vault へ同期しない（呼び出し元の環境を持ち込まない）" || ng "session-end: 試験が vault へ同期した"
OUT="$(printf '%s' "$SID" | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q 'Codex が実行中' && printf '%s' "$OUT" | grep -q 'orch.health）は省略' && ok "restore: 実行中を警告し点検を省く" || ng "restore: 実行中の警告"
DEAD="$(bash -c 'echo $$')"; echo "$DEAD 0" > "$R/data/codex_runs/.lock/owner"
[ "$(LG "$R/HANDOVER.md")" = 0 ] && ok "lock-guard: 持ち主が死んだロックでは止めない" || ng "lock-guard: 死んだロック"
rm -rf "$R/data/codex_runs/.lock"
printf '日時: test\n' > "$R/data/.codex_violation"
printf '%s' "$SID" | bash "$R/.claude/hooks/restore-charter.sh" | grep -q '違反が出たまま' && ok "restore: Codex の違反の印を警告" || ng "restore: 違反の印"
rm -f "$R/data/.codex_violation"
P="$T/parent"; mkdir -p "$P"; git -C "$P" init -q; cp -R "$R" "$P/lum"; rm -rf "$P/lum/.git"; git -C "$P/lum" init -q
printf '#!/bin/sh\ntouch "%s"\n' "$T/pwned" > "$P/lum/.git/fsm.sh"; chmod +x "$P/lum/.git/fsm.sh"; git -C "$P/lum" config core.fsmonitor "$P/lum/.git/fsm.sh"
OUT="$(printf '%s' "$SID" | CLAUDE_PROJECT_DIR="$P/lum" bash "$P/lum/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q '作業フォルダ内に .git' && [ ! -e "$T/pwned" ] && ok "restore: 入れ子の .git を git を使わずに検知（fsmonitor は走らない）" || ng "restore: 入れ子の .git"
expect "guard-secrets: 入れ子の .git があれば commit を止める" 2 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"git commit -m x\"}}' | CLAUDE_PROJECT_DIR='$P/lum' bash '$P/lum/.claude/hooks/guard-secrets.sh'"
[ ! -e "$T/pwned" ] && ok "guard-secrets: 入れ子の .git の fsmonitor は走らない" || ng "guard-secrets: fsmonitor が走った"
OUT="$(printf '%s' "$SID" | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q '作業フォルダ内に .git' && ng "restore: リポジトリの根の .git を誤検知" || ok "restore: リポジトリの根の .git は正当とみなす"

# 10) 3回目の審査: 大文字小文字の .git・違反の印の間は git を使わない・Codex 実行中のモデル切替の保留
mkdir -p "$R/sub/.GIT"
printf '%s' "$SID" | bash "$R/.claude/hooks/restore-charter.sh" | grep -q '作業フォルダ内に .git' && ok "restore: 大文字小文字の違う .GIT も検知" || ng "restore: .GIT"
rm -rf "$R/sub"
printf '日時: test\n' > "$R/data/.codex_violation"
printf '%s' "$SID" | bash "$R/.claude/hooks/restore-charter.sh" | grep -q 'git の点検を省きました' && ok "restore: 違反の印の間は git を使わない" || ng "restore: 違反の印で git 省略"
expect "guard-secrets: 違反の印の間は commit を止める" 2 bash -c "printf '%s' '{\"tool_input\":{\"command\":\"git commit -m x\"}}' | bash '$R/.claude/hooks/guard-secrets.sh'"
rm -f "$R/data/.codex_violation"
ESC="$R/state/escalations.log"; PEND="$LUMINOUS_SAFE_DIR/escalations.pending"
N0="$(cat "$ESC" 2>/dev/null | wc -l | tr -d ' ')"
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
printf '%s' '{"from_model":"a","to_model":"b"}' | bash "$R/.claude/hooks/log-model-switch.sh" >/dev/null 2>&1
[ "$(cat "$ESC" 2>/dev/null | wc -l | tr -d ' ')" = "$N0" ] && [ -s "$PEND" ] && ok "model-switch: Codex 実行中は追跡中の記録を書き換えず保留" || ng "model-switch: 実行中の保留"
rm -rf "$R/data/codex_runs/.lock"
printf '%s' '{"from_model":"b","to_model":"c"}' | bash "$R/.claude/hooks/log-model-switch.sh" >/dev/null 2>&1
[ "$(cat "$ESC" | wc -l | tr -d ' ')" = "$((N0 + 2))" ] && [ ! -e "$PEND" ] && ok "model-switch: 終了後に保留分を移して記録" || ng "model-switch: 保留分の移動"

# 11) 4回目の審査: 保留の記録は機械的な書式の行だけ移す・モデル名の無害化・Stop ゲートの開始時刻の検証
PRIV="/Us""ers/someone/secret"
printf '2026-10-08T00:00:00Z | x | %s\n' "$PRIV" > "$PEND"
OUT="$(printf '%s' '{"from_model":"c","to_model":"d"}' | bash "$R/.claude/hooks/log-model-switch.sh" 2>&1)"
! grep -q "$PRIV" "$ESC" && [ ! -e "$PEND" ] && ok "model-switch: 書式に合わない保留行（非公開の印）は公開の記録へ移さない" || ng "model-switch: 不正な保留行"
printf '%s' "$OUT" | grep -q '1 行を捨てました' && ! printf '%s' "$OUT" | grep -q "$PRIV" && ok "model-switch: 捨てた行数だけを知らせる（中身は出さない）" || ng "model-switch: 捨てた行数の表示"
printf '%s' "{\"from_model\":\"x$PRIV\",\"to_model\":\"e f\"}" | bash "$R/.claude/hooks/log-model-switch.sh" >/dev/null 2>&1
! grep -q "$PRIV" "$ESC" && tail -n 1 "$ESC" | grep -q '| e_f |' && ok "model-switch: モデル名のパスや空白を無害化" || ng "model-switch: モデル名の無害化"
sleep 1
printf '%s' '{"session_id":"test-3","source":"startup"}' | bash "$R/.claude/hooks/restore-charter.sh" >/dev/null 2>&1
echo abc > "$R/state/.sessions/test-3.start"
OUT="$(printf '%s' '{"session_id":"test-3","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh")"
printf '%s' "$OUT" | grep -q '"block"' && ok "stop-gate: 開始時刻が数字でなければ印の更新時刻で判定（ゲートは外れない）" || ng "stop-gate: 数字でない開始時刻"
echo 99999999999 > "$R/state/.sessions/test-3.start"
OUT="$(printf '%s' '{"session_id":"test-3","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh")"
printf '%s' "$OUT" | grep -q '"block"' && ok "stop-gate: 未来の開始時刻は使わない" || ng "stop-gate: 未来の開始時刻"

# 12) 5回目の審査（任意の軽）: 保留の置き場が作業フォルダや /tmp の中なら保留しない
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
OUT="$(printf '%s' '{"from_model":"f","to_model":"g"}' | LUMINOUS_SAFE_DIR="$R/unsafe" bash "$R/.claude/hooks/log-model-switch.sh" 2>&1)"
[ ! -e "$R/unsafe/escalations.pending" ] && printf '%s' "$OUT" | grep -q '保留できませんでした' && ok "model-switch: 作業フォルダ内の置き場には保留しない" || ng "model-switch: 安全でない置き場"
OUT="$(printf '%s' '{"from_model":"f","to_model":"g"}' | LUMINOUS_SAFE_DIR="$T/unsafe" bash "$R/.claude/hooks/log-model-switch.sh" 2>&1)"
[ ! -e "$T/unsafe/escalations.pending" ] && printf '%s' "$OUT" | grep -q '保留できませんでした' && ok "model-switch: /tmp の中の置き場には保留しない" || ng "model-switch: /tmp の置き場"
rm -rf "$R/data/codex_runs/.lock" "$R/unsafe"


# 13) 全体停止 B（docs/specs/20261008_global_halt.md）: halt-guard（PreToolUse *）・settings.json の先頭の確認・stop-gate・restore・session-end・guard-protected
HG="$R/.claude/hooks/halt-guard.sh"; HALT="$R/data/.luminous_halt"; mkdir -p "$R/data"
hg() { printf '%s' "$1" | bash "$HG" >/dev/null 2>&1; echo $?; }   # $1=JSON
SJ_CMD="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print([h for h in d["hooks"]["PreToolUse"] if h.get("matcher")=="*"][0]["hooks"][0]["command"])' "$R/.claude/settings.json")"
sj() { printf '%s' "$1" | bash -c "$SJ_CMD" >/dev/null 2>&1; echo $?; }   # settings.json に書いた先頭の確認を、そのまま実行
rm -f "$HALT"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}')" = 0 ] && ok "halt-guard: 印なしの Bash は通る" || ng "halt-guard: 印なしの Bash"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"true luminous-hook-canary"}}')" = 2 ] && ok "halt-guard: 印なしでも canary は断る" || ng "halt-guard: canary"
[ "$(sj '{"tool_name":"Bash","tool_input":{"command":"true luminous-hook-canary"}}')" = 2 ] && ok "settings: 印なしの canary も settings の経路で断る" || ng "settings: canary"
[ "$(sj '{"tool_name":"Edit","tool_input":{"file_path":"x"}}')" = 0 ] && ok "settings: 印なしの Edit は通る" || ng "settings: 印なし Edit"
printf '2026-10-10T00:00:00Z 試験の理由\n' > "$HALT"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"ls"}}')" = 2 ] && ok "halt-guard: 印あり Bash は 2" || ng "halt-guard: 印あり Bash"
[ "$(hg '{"tool_name":"Edit","tool_input":{"file_path":"x"}}')" = 2 ] && ok "halt-guard: 印あり Edit は 2" || ng "halt-guard: 印あり Edit"
[ "$(hg '{"tool_name":"Agent","tool_input":{}}')" = 2 ] && ok "halt-guard: 印あり Agent（サブエージェント）は 2" || ng "halt-guard: 印あり Agent"
[ "$(hg '{"tool_name":"WebFetch","tool_input":{}}')" = 2 ] && ok "halt-guard: 印あり WebFetch は 2" || ng "halt-guard: 印あり WebFetch"
RO=0; for t in Read Grep Glob TaskStop AskUserQuestion; do J="{\"tool_name\":\"$t\",\"tool_input\":{}}"; [ "$(hg "$J")" = 0 ] || RO=1; done   # JSON は先に変数へ（bash 3.2 は "$( )" の中の {a,b} をブレース展開してしまう）
[ "$RO" = 0 ] && ok "halt-guard: 印あり Read・Grep・Glob・TaskStop・AskUserQuestion は通る" || ng "halt-guard: 読むだけの道具"
[ "$(hg 'not json at all')" = 2 ] && ok "halt-guard: 印あり・壊れた JSON でも 2" || ng "halt-guard: 壊れた JSON"
[ "$(printf '%s' '{"tool_name":"Read"}' | PATH="$T/nopath" /bin/bash "$HG" >/dev/null 2>&1; echo $?)" = 2 ] && ok "halt-guard: 印あり・jq も python3 も無ければ 2（読む道具でも）" || ng "halt-guard: jq/python3 なし"
[ "$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | FABLE5_HEADLESS=1 bash "$HG" >/dev/null 2>&1; echo $?)" = 2 ] && ok "halt-guard: 無人実行でも印があれば 2" || ng "halt-guard: headless"
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash "$HG" 2>&1 >/dev/null | grep -q '試験の理由' && ok "halt-guard: 断る文に理由を出す" || ng "halt-guard: 理由の表示"
[ "$(sj '{"tool_name":"Bash","tool_input":{"command":"ls"}}')" = 2 ] && ok "settings: 印あり Bash は settings の経路でも 2" || ng "settings: 印あり Bash"
[ "$(sj '{"tool_name":"Read","tool_input":{}}')" = 0 ] && ok "settings: 印あり Read は settings の経路でも通る" || ng "settings: 印あり Read"
mv "$HG" "$HG.away"
[ "$(sj '{"tool_name":"Read","tool_input":{}}')" = 2 ] && ok "settings: 印あり・halt-guard.sh が無くても 2（Read でも。127 にならない）" || ng "settings: スクリプト欠落"
mv "$HG.away" "$HG"
rm -f "$HALT"; ln -s /nonexistent/luminous-halt-target "$HALT"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"ls"}}')" = 2 ] && ok "halt-guard: 先の無いリンクの印でも 2" || ng "halt-guard: リンクの印"
rm -f "$HALT"; printf '2026-10-10T00:00:00Z 試験の理由\n' > "$HALT"
# guard-protected: Bash で印を消す・書き換えるのを止める
[ "$(gp "rm -f data/.luminous_halt")" = 2 ] && ok "guard-protected: Bash の rm で印を消すのを止める" || ng "guard-protected: rm 印"
[ "$(gp "echo x > data/.luminous_halt")" = 2 ] && ok "guard-protected: Bash のリダイレクトで印を書き換えるのを止める" || ng "guard-protected: > 印"
[ "$(gp "echo x > tools/luminous_halt.sh")" = 2 ] && ok "guard-protected: tools/luminous_halt.sh の書き換えを止める" || ng "guard-protected: halt スクリプト"
[ "$(gp "printf '* -diff\n' > .gitattributes")" = 2 ] && ok "guard-protected: .gitattributes の書き換えを止める（-diff で鍵の検査を外させない）" || ng "guard-protected: .gitattributes"
[ "$(gp "bash tools/luminous_halt.sh on")" = 0 ] && ok "guard-protected: 全体停止の on は通す（誰でも付けられる）" || ng "guard-protected: on"
[ "$(gp "bash tools/luminous_halt.sh on 試験の理由 2>&1")" = 0 ] && ok "guard-protected: on 理由 2>&1 も通す" || ng "guard-protected: on 2>&1"
[ "$(gp 'bash tools/luminous_halt.sh on "誤って rm を実行した"')" = 0 ] && ok "guard-protected: 理由に rm が入っていても on は通す" || ng "guard-protected: on 理由 rm"
[ "$(gp "cd $R && bash tools/luminous_halt.sh status 2>&1")" = 0 ] && ok "guard-protected: cd … && status 2>&1 も通す" || ng "guard-protected: cd && status"
[ "$(gp "bash tools/luminous_halt.sh status 2>&1 | tail -3")" = 0 ] && ok "guard-protected: status | tail は通す（書き込みではない）" || ng "guard-protected: status | tail"
[ "$(gp "bash tools/luminous_halt.sh status; rm data/.luminous_halt")" = 2 ] && ok "guard-protected: status に rm をつなげると止める" || ng "guard-protected: status; rm"
[ "$(gp "$(printf 'bash tools/luminous_halt.sh status\nrm data/.luminous_halt')")" = 2 ] && ok "guard-protected: 2 行目の rm も止める" || ng "guard-protected: 2 行目"
[ "$(gp "bash tools/luminous_halt.sh off")" = 0 ] && ok "guard-protected: off はこの hook では止めない（端末の判定が断る）" || ng "guard-protected: off"
[ "$(gp "bash tools/luminous_halt.sh status > CLAUDE.md")" = 2 ] && ok "guard-protected: status の出力を保護ファイルへ向けるのは止める" || ng "guard-protected: status > CLAUDE.md"
[ "$(gp 'bash tools/luminous_halt.sh on $(rm CLAUDE.md)')" = 2 ] && ok "guard-protected: 理由に \$( ) を含む on は止める（シェルが実行する）" || ng "guard-protected: on \$( )"
[ "$(gp 'bash tools/luminous_halt.sh on `rm CLAUDE.md`')" = 2 ] && ok "guard-protected: 理由にバッククォートを含む on は止める" || ng "guard-protected: on バッククォート"
[ "$(gp 'cd $(rm CLAUDE.md) && bash tools/luminous_halt.sh status')" = 2 ] && ok "guard-protected: cd の引数に \$( ) があれば止める" || ng "guard-protected: cd \$( )"
[ "$(gp ".venv/bin/python -m pytest tests/test_tools.py -k luminous_halt")" = 0 ] && ok "guard-protected: pytest -k luminous_halt は通す（-m は書き込みの旗ではない）" || ng "guard-protected: pytest -k"
[ "$(gp "python3 -c 'open(\"tools/luminous_halt.sh\",\"w\")'")" = 2 ] && ok "guard-protected: python -c での書き換えは引き続き止める" || ng "guard-protected: python -c"
[ "$(gp "perl -pi -e 's/a/b/' CLAUDE.md")" = 2 ] && ok "guard-protected: perl -pi -e の書き換えを止める" || ng "guard-protected: perl -pi"
[ "$(gp "perl -0pi -e 's/a/b/' .claude/settings.json")" = 2 ] && ok "guard-protected: perl -0pi -e の書き換えを止める" || ng "guard-protected: perl -0pi"
[ "$(gp "ruby -pi -e 'gsub(/a/,\"b\")' CLAUDE.md")" = 2 ] && ok "guard-protected: ruby -pi -e の書き換えを止める" || ng "guard-protected: ruby -pi"
[ "$(gp "python3 -I -c 'import os; os.remove(\"CLAUDE.md\")'")" = 2 ] && ok "guard-protected: python3 -I -c の削除を止める" || ng "guard-protected: python3 -I -c"
[ "$(gp "python3 -Ic 'import os; os.remove(\"CLAUDE.md\")'")" = 2 ] && ok "guard-protected: python3 -Ic の削除を止める" || ng "guard-protected: python3 -Ic"
[ "$(gp "node --eval 'require(\"fs\").unlinkSync(\"CLAUDE.md\")'")" = 2 ] && ok "guard-protected: node --eval の削除を止める" || ng "guard-protected: node --eval"
[ "$(gp "python3 - < CLAUDE.md")" = 2 ] && ok "guard-protected: python3 - （標準入力）も止める" || ng "guard-protected: python3 -"
rm -f "$HALT"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"grep -rn luminous-hook-canary docs/"}}')" = 0 ] && ok "halt-guard: canary の文字列を含むだけの grep は通す" || ng "halt-guard: grep canary"
[ "$(hg '{"tool_name":"Bash","tool_input":{"command":"  true luminous-hook-canary 2>&1"}}')" = 2 ] && ok "halt-guard: 先頭が canary なら断る（空白・後続つき）" || ng "halt-guard: canary 先頭"
printf '2026-10-10T00:00:00Z 試験の理由\n' > "$HALT"
[ "$(hg '{"tool_name":"KillShell","tool_input":{}}')" = 0 ] && ok "halt-guard: 印あり KillShell（古い版の停止の道具）は通る" || ng "halt-guard: KillShell"
printf '2026-10-10T00:00:00Z a\xc2\x85b\xe2\x80\xaec\n' > "$HALT"
OUT="$(printf '%s' '{"session_id":"test-4","source":"startup"}' | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q 'abc' && ! printf '%s' "$OUT" | grep -q "$(printf '\xe2\x80\xae')" && ok "restore: 理由の C1・双方向の上書きの文字を落とす" || ng "restore: 制御文字の除去"
printf '2026-10-10T00:00:00Z 試験の理由\n' > "$HALT"
# stop-gate: 全体停止中は未更新でも閉じ込めない
SID3='{"session_id":"test-3","source":"startup"}'
OUT="$(printf '%s' "$SID3" | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q '全体停止中' && ok "restore: 全体停止中なら最初に大きく表示" || ng "restore: 全体停止の表示"
printf '%s' "$OUT" | grep -q '試験の理由' && ok "restore: 理由をデータとして表示" || ng "restore: 理由"
sleep 1
OUT="$(printf '%s' '{"session_id":"test-3","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh")"
[ -z "$OUT" ] && ok "stop-gate: 全体停止中は未更新でも止めない" || ng "stop-gate: 全体停止中 ($OUT)"
# session-end: 全体停止中は docx 再生成を見送る
rm -f "$R/state/.session-end.log"; bash "$R/.claude/hooks/session-end.sh" >/dev/null 2>&1
grep -q '全体停止中のため docx 再生成を見送り' "$R/state/.session-end.log" 2>/dev/null && ok "session-end: 全体停止中は docx 再生成を見送る（理由も正しい）" || ng "session-end: 全体停止中の見送り"
# session-end: 全体停止中は Obsidian 同期も見送る（停止の原因かもしれない中身を vault へ広げない）。見送りの文に「失敗」を入れない（次回の SessionStart が誤って警告する）
VH="$T/vaulthalt"; mkdir -p "$VH/.obsidian"
rm -f "$R/state/.session-end.log"; LUMINOUS_OBSIDIAN_DIR="$VH" bash "$R/.claude/hooks/session-end.sh" >/dev/null 2>&1
[ ! -e "$VH/ルミナス" ] && grep -q '全体停止中のため Obsidian 同期を見送り' "$R/state/.session-end.log" 2>/dev/null && ! grep -q '失敗' "$R/state/.session-end.log" \
  && ok "session-end: 全体停止中は Obsidian 同期も見送る（vault へ書かない・「失敗」と書かない）" || ng "session-end: 全体停止中に vault へ同期した"
rm -f "$HALT"
LUMINOUS_OBSIDIAN_DIR="$VH" bash "$R/.claude/hooks/session-end.sh" >/dev/null 2>&1
[ -f "$VH/ルミナス/ルミナス.md" ] && ok "session-end: 印を消せば Obsidian 同期を行う" || ng "session-end: 印なしで同期されない"
OUT="$(printf '%s' "$SID3" | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q '全体停止中' && ng "restore: 印なしで停止の表示が出る" || ok "restore: 印なしでは停止の表示を出さない"

# 14) restore: 本命の git フックが効いていなければ最初に警告する・点検（orch.health）が動かないときは理由を 1 行出す（.venv の無い Mac の初回）
H="$T/health"; mkdir -p "$H/orch" "$H/state"; cp -R "$R/.claude" "$R/.githooks" "$R/scripts" "$H/"; cp "$R/CHARTER.md" "$R/ROUTINE.md" "$H/"; : > "$H/orch/__init__.py"
printf 'import luminous_no_such_module_xyz\n' > "$H/orch/health.py"
git -C "$H" init -q; git -C "$H" add -A >/dev/null; git -C "$H" -c user.email=t@t -c user.name=t commit -q -m init   # 未コミットの orch/ があると点検を省くので先にコミット
OUT="$(printf '%s' "$SID" | CLAUDE_PROJECT_DIR="$H" bash "$H/.claude/hooks/restore-charter.sh" 2>/dev/null)"
printf '%s' "$OUT" | grep -q 'git フック（pre-commit / pre-push の鍵の検査）が効いていません' && ok "restore: フックの場所が未設定なら警告" || ng "restore: フック未設定の警告"
printf '%s' "$OUT" | grep -qE '点検の結果が出ませんでした|点検（orch.health）は実行できません' && ok "restore: 点検が動かない（依存を読めない）ときは setup.sh を促す 1 行を出す" || ng "restore: 点検の空振りが無言"
git -C "$H" config core.hooksPath .githooks
printf 'import sys\nsys.stderr.write("NotOpenSSLWarning: dummy\\n")\nprint("codex: test-line")\n' > "$H/orch/health.py"; git -C "$H" add -A >/dev/null; git -C "$H" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null commit -q -m ok
OUT="$(printf '%s' "$SID" | CLAUDE_PROJECT_DIR="$H" bash "$H/.claude/hooks/restore-charter.sh" 2>/dev/null)"
printf '%s' "$OUT" | grep -q 'が効いていません' && ng "restore: フックが効いているのに警告" || ok "restore: フックが効いていれば警告しない"
printf '%s' "$OUT" | grep -q '^codex: test-line' && ! printf '%s' "$OUT" | grep -q 'NotOpenSSLWarning\|点検の結果が出ませんでした' && ok "restore: 点検の結果だけを出し stderr は注入しない" || ng "restore: 点検の出力"

# 15) Mac を模す（システムは触らず、使い捨ての置き場の shim と PATH だけで模す）: jq が無く、python3 は「有るが exit 1 で終わる」
#     （CLT が無い・壊れた Mac の /usr/bin/python3）。解析できなくても、各 hook が止める側に倒れること
MB="$T/macbin"; mkdir -p "$MB"
for c in bash sh cat cp mv rm mkdir ls ln chmod touch date stat sed grep awk tr cut head tail sort wc find dirname basename env git cmp cksum; do
  p="$(command -v "$c" 2>/dev/null)"; case "$p" in /*) ln -s "$p" "$MB/$c" ;; esac
done
printf '#!/bin/sh\necho "xcrun: error: invalid active developer path" >&2\nexit 1\n' > "$MB/python3"; chmod +x "$MB/python3"
[ ! -e "$MB/jq" ] && ! PATH="$MB" "$MB/python3" -c pass 2>/dev/null && ok "mac: 模した PATH には jq が無く python3 は動かない" || ng "mac: 模した PATH の用意"
mj() { python3 -c 'import json,sys; print(json.dumps({"session_id":"test-m","transcript_path":"/home/u/.claude/projects/p/test-m.jsonl","cwd":sys.argv[3],"hook_event_name":"PreToolUse","tool_name":sys.argv[1],"tool_input":{"command":sys.argv[2],"description":"x"}},ensure_ascii=False))' "$1" "$2" "$R"; }   # Claude Code と同じ形（非 ASCII はそのまま。会話記録の場所は .claude/ を含む）
mh() { PATH="$MB" "$MB/bash" "$@" >/dev/null 2>&1; echo $?; }   # $1=hook（標準入力に JSON）
gpm() { mj Bash "$1" | mh "$R/.claude/hooks/guard-protected.sh"; }
for c in "sed -i '' 's/a/b/' CHARTER.md" "cat .env" "git commit --no-verify -m x" "$(printf 'echo hi\nrm CLAUDE.md')" "echo x >> claude.md" "echo x > .claude/settings.json" "sed -i '' 's/a/b/' $NFD_FP" "sed -i '' 's/a/b/' prompts/ルミナス_最終プロンプト.md"; do
  [ "$(gpm "$c")" = 2 ] && ok "mac: guard-protected は解析できなくても「$(printf '%s' "$c" | tr '\n' '/')」を止める" || ng "mac: guard-protected $c"
done
for c in "ls -la" "cat CHARTER.md" "bash tools/luminous_halt.sh on 試験の理由" "echo x > notes.txt" "cp a.txt b.txt"; do
  [ "$(gpm "$c")" = 0 ] && ok "mac: guard-protected は解析できなくても「${c}」は通す" || ng "mac: guard-protected $c"
done
# タブ区切り（JSON では \t）: 予備の道で \t を「; 」にすると rm[[:space:]] に当たらず素通りした（審査で発見）。空白に戻して止める
for c in "$(printf 'rm\tCLAUDE.md')" "$(printf 'cat\t.env')" "$(printf 'sed\t-i\t%s\ts/a/b/\tCHARTER.md' "''")" "$(printf 'git\tcommit\t--no-verify')"; do
  [ "$(gpm "$c")" = 2 ] && ok "mac: guard-protected は解析できなくてもタブ区切りの「$(printf '%s' "$c" | tr '\t' '~')」を止める" || ng "mac: guard-protected タブ区切り $c"
done
printf 'TOKEN=%s\n' "$FAKE_KEY" > "$R/leak.txt"
[ "$(mj Bash 'git commit -m x' | mh "$R/.claude/hooks/guard-secrets.sh")" = 2 ] && ok "mac: guard-secrets は検査できなければ git commit を止める" || ng "mac: guard-secrets commit"
[ "$(mj Bash 'ls -la' | mh "$R/.claude/hooks/guard-secrets.sh")" = 0 ] && ok "mac: guard-secrets は git 以外を通す" || ng "mac: guard-secrets ls"
rm -f "$R/leak.txt"
lgm() { printf '%s' "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$1\"}}" | mh "$R/.claude/hooks/codex-lock-guard.sh"; }
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
[ "$(lgm "$R/HANDOVER.md")" = 2 ] && ok "mac: lock-guard は Codex の実行中なら編集先を確かめられなくても止める" || ng "mac: lock-guard 実行中"
rm -rf "$R/data/codex_runs/.lock"
[ "$(lgm "$R/HANDOVER.md")" = 0 ] && ok "mac: lock-guard は Codex が動いていなければ通す" || ng "mac: lock-guard 未実行"
printf '%s' '{"session_id":"test-m","source":"startup"}' | PATH="$MB" "$MB/bash" "$R/.claude/hooks/restore-charter.sh" > "$T/mac-restore.txt" 2>/dev/null
grep -q '始源の目的' "$T/mac-restore.txt" && grep -q '## 4\.' "$T/mac-restore.txt" && grep -q 'HANDOVER.md（最新の節）' "$T/mac-restore.txt" && grep -q '節1' "$T/mac-restore.txt" \
  && ok "mac: restore は動く python3 が無くても憲章・禁止事項・HANDOVER を注入（切り詰めずに出す）" || ng "mac: restore の注入が欠ける"
python3 -c 'import sys; sys.stdin.buffer.read().decode("utf-8")' < "$T/mac-restore.txt" 2>/dev/null && ok "mac: restore の出力は UTF-8 として壊れていない" || ng "mac: restore の UTF-8"
OUT="$(printf '%s' '{"session_id":"test-m","stop_hook_active":true}' | PATH="$MB" "$MB/bash" "$R/.claude/hooks/stop-gate.sh" 2>/dev/null)"; RC=$?
[ "$RC" = 0 ] && [ -z "$OUT" ] && ok "mac: stop-gate は stop_hook_active なら許可（解析できなくてもループ防止）" || ng "mac: stop-gate stop_hook_active (exit $RC)"
OUT="$(printf '%s' '{"session_id":"test-m","stop_hook_active":false}' | PATH="$MB" "$MB/bash" "$R/.claude/hooks/stop-gate.sh" 2>/dev/null)"
printf '%s' "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["decision"]=="block" and "ROUTINE" in d["reason"]' 2>/dev/null && ok "mac: stop-gate は jq も python3 も無くても JSON で止める" || ng "mac: stop-gate の JSON ($OUT)"
printf '2026-10-10T00:00:00Z 試験の理由\n' > "$HALT"
[ "$(mj Bash ls | mh "$HG")" = 2 ] && ok "mac: halt-guard は印があれば Bash を止める" || ng "mac: halt-guard Bash"
[ "$(printf '%s' '{"tool_name":"Read"}' | mh "$HG")" = 2 ] && ok "mac: halt-guard は印があり解析できなければ読む道具でも止める" || ng "mac: halt-guard Read"
rm -f "$HALT"

# 16) stop-gate: Codex の実行中は催促しない（codex-lock-guard が記録の Edit を止め、Bash で書けば範囲検査の違反になる）。終われば催促する
date +%s > "$R/state/.sessions/test-g.start"   # 記録 3 件はこれより前に書いた（間に sleep がある）
SG_M='{"session_id":"test-g","stop_hook_active":false}'
printf '%s' "$SG_M" | bash "$R/.claude/hooks/stop-gate.sh" | grep -q '"block"' && ok "stop-gate: （前提）未更新ならブロック" || ng "stop-gate: 前提のブロック"
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
OUT="$(printf '%s' "$SG_M" | bash "$R/.claude/hooks/stop-gate.sh")"
[ -z "$OUT" ] && ok "stop-gate: Codex の実行中は催促しない（書けないものを求めない）" || ng "stop-gate: Codex の実行中に催促した"
echo "$DEAD 0" > "$R/data/codex_runs/.lock/owner"
printf '%s' "$SG_M" | bash "$R/.claude/hooks/stop-gate.sh" | grep -q '"block"' && ok "stop-gate: 持ち主が死んだロックでは催促する" || ng "stop-gate: 死んだロックで催促しない"
rm -rf "$R/data/codex_runs/.lock"
printf '%s' "$SG_M" | bash "$R/.claude/hooks/stop-gate.sh" | grep -q '"block"' && ok "stop-gate: Codex が終われば催促する" || ng "stop-gate: 終了後に催促しない"

mkdir -p "$R/data/codex_runs/.lock"; echo "0 0" > "$R/data/codex_runs/.lock/owner"
OUT="$(printf '%s' '{"session_id":"test-g","stop_hook_active":false}' | bash "$R/.claude/hooks/stop-gate.sh" 2>/dev/null)"
printf '%s' "$OUT" | grep -q '"decision"' && ok "stop-gate: 持ち主の PID が 0（kill -0 が通る）でも素通りしない" || ng "stop-gate: PID 0 で素通り"
rm -rf "$R/data/codex_runs/.lock"

# 17) restore: 圧縮（compact）では開始時刻を上書きしない（それまでに書いた記録を「開始前」にしない）。source を読めなければ従来どおり上書き
SM="$R/state/.sessions/test-c.start"; rm -f "$SM"
rc_src() { printf '{"session_id":"test-c","source":"%s"}' "$1" | bash "$R/.claude/hooks/restore-charter.sh" >/dev/null 2>&1; }
rc_src compact; [ -f "$SM" ] && ok "restore: compact でも開始の印が無ければ作る" || ng "restore: compact で印を作らない"
echo 12345 > "$SM"; rc_src compact
[ "$(cat "$SM")" = 12345 ] && ok "restore: compact では開始時刻を上書きしない（Stop ゲートの基準を保つ）" || ng "restore: compact で上書きした"
rc_src resume
[ "$(cat "$SM")" != 12345 ] && ok "restore: resume では開始時刻を上書きする" || ng "restore: resume で上書きしない"
echo 12345 > "$SM"; rc_src startup
[ "$(cat "$SM")" != 12345 ] && ok "restore: startup では開始時刻を上書きする" || ng "restore: startup で上書きしない"
SMN="$R/state/.sessions/nosession.start"; echo 12345 > "$SMN"   # 解析できないと session_id も読めず nosession になる
printf '%s' '{"session_id":"test-c","source":"compact"}' | PATH="$MB" "$MB/bash" "$R/.claude/hooks/restore-charter.sh" >/dev/null 2>&1
[ "$(cat "$SMN")" != 12345 ] && ok "mac: source を読めない（jq も動く python3 も無い）ときは従来どおり上書きする" || ng "mac: source を読めないのに上書きしない"

# 18) session-end: 最終プロンプトの md が変わったときだけ docx を作り直す（docx は作るたびに時刻が入ってバイト列が変わり、追跡中の docx を汚して
#     codex_impl.sh の「未コミットの変更」で止まるため）。docx が今の md から作ったものだと確かめられなければ従来どおり作り直す
D="$T/docx"; mkdir -p "$D/state" "$D/prompts" "$D/.claude"; cp -R "$HERE/.claude/hooks" "$D/.claude/"; cp -R "$HERE/scripts" "$D/"; cp "$HERE/prompts/ルミナス_最終プロンプト.md" "$D/prompts/"; printf 'state/\ndata/\n' > "$D/.gitignore"
DX="$D/☆ルミナス_最終プロンプト.docx"; MDF="$D/prompts/ルミナス_最終プロンプト.md"; DXSRC="$D/state/.sessions/docx.src"
FN="$T/fakenode"; mkdir -p "$FN"
cat > "$FN/node" <<'NODE'
#!/bin/sh
# 偽の node（scripts/build-final-prompt-docx.mjs の代わり）: 作るたびにバイト列が変わる docx を書く（本物も作るたびに時刻が入る）
printf 'docx %s %s\n' "$(date +%s)" "$$" > "☆ルミナス_最終プロンプト.docx"
NODE
chmod +x "$FN/node"
gd() { git -C "$D" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null "$@"; }
se() { CLAUDE_PROJECT_DIR="$D" PATH="$FN:$PATH" bash "$D/.claude/hooks/session-end.sh" </dev/null >/dev/null 2>&1; }
dsum() { cksum < "$DX" 2>/dev/null; }
git -C "$D" init -q; gd add -A; gd commit -q -m init
se; [ -f "$DX" ] && [ -s "$DXSRC" ] && ok "session-end: docx がまだコミットされていなければ作り、作ったときの md を記録する" || ng "session-end: 初回の docx"
gd add -A; gd commit -q -m docx
D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && [ -z "$(gd status --porcelain)" ] && grep -q '最終プロンプトに変更なし（docx 再生成を省略）' "$D/state/.session-end.log" \
  && ok "session-end: md が変わっていなければ docx を作り直さない（バイト列も git status も変わらない）" || ng "session-end: md 未変更で docx を作り直した"
printf '\n- 試験の追記\n' >> "$MDF"; D0="$(dsum)"; se
[ "$(dsum)" != "$D0" ] && ok "session-end: md を作業ツリーで変えたら docx を作り直す" || ng "session-end: md の変更で作り直さない"
gd checkout -q -- "☆ルミナス_最終プロンプト.docx"; gd add -A; gd commit -q -m md
D0="$(dsum)"; se
[ "$(dsum)" != "$D0" ] && ok "session-end: md が docx の後にコミットされたら作り直す" || ng "session-end: md が後のコミットで作り直さない"
gd add -A; gd commit -q -m docx2; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && ok "session-end: 作り直した docx をコミットした後は作り直さない" || ng "session-end: コミット後も作り直した"
printf -- '- 二つ目\n' >> "$MDF"; se; gd add -A; gd commit -q -m both; D0="$(dsum)"; se
[ "$(dsum)" != "$D0" ] && ok "session-end: md と docx が同じコミットで変わったら作り直す（どの md から作ったか分からない）" || ng "session-end: 同じコミットで作り直さない"
gd add -A; gd commit -q -m docx3; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && ok "session-end: （前提）docx を別にコミットすれば作り直さない" || ng "session-end: 別コミット後に作り直した"
echo "1 1" > "$DXSRC"; D0="$(dsum)"; se
[ "$(dsum)" != "$D0" ] && [ "$(cat "$DXSRC")" = "$(cksum < "$MDF")" ] && ok "session-end: 前に作ったときの md が今と違えば作り直す（古い md の docx が md の後にコミットされたとき）" || ng "session-end: 記録の md の違いで作り直さない"
gd add -A; gd commit -q -m docx4
printf 'keep\n' > "$T/docxsrc-target"; rm -f "$DXSRC"; ln -s "$T/docxsrc-target" "$DXSRC"; D0="$(dsum)"; se
[ "$(dsum)" != "$D0" ] && [ "$(cat "$T/docxsrc-target")" = keep ] && [ -f "$DXSRC" ] && [ ! -L "$DXSRC" ] && ok "session-end: 記録が記号リンクなら作り直し、リンクの先は書き換えない" || ng "session-end: 記号リンクの記録"
gd add -A; gd commit -q -m docx5; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && ok "session-end: （前提）記録を戻せば作り直さない" || ng "session-end: 記録を戻しても作り直した"
mkdir -p "$D/data"; printf '日時: test\n' > "$D/data/.codex_violation"; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && grep -q '違反の印・ロック・入れ子の .git があるため docx 再生成を見送り' "$D/state/.session-end.log" && ok "session-end: Codex の違反の印があれば node を動かさず見送る（未審査の中身を外で動かさない）" || ng "session-end: 違反の印で docx を作り直した"
rm -f "$D/data/.codex_violation"; gd checkout -q -- "☆ルミナス_最終プロンプト.docx"
mkdir -p "$D/sub/.git"; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && ok "session-end: 入れ子の .git があれば node を動かさず見送る" || ng "session-end: 入れ子の .git で docx を作り直した"
rm -rf "$D/sub"; gd checkout -q -- "☆ルミナス_最終プロンプト.docx"
mkdir -p "$D/data/codex_runs/.lock"; echo "$$ 0" > "$D/data/codex_runs/.lock/owner"; D0="$(dsum)"; se
[ "$(dsum)" = "$D0" ] && ok "session-end: Codex の実行中は（変更が無くても）作り直さない" || ng "session-end: Codex の実行中に作り直した"
rm -rf "$D/data/codex_runs/.lock"

# 19) restore: 前回の開始の後に、保護ファイルがコミット（pull・merge を含む）で変わったら警告する。この clone だけの記録（state/.sessions/、git 管理外）と比べる
#     （クラウドでは hooks も確認のダイアログも効かないので、クラウドでコミットされた保護ファイルの変更は Mac の pull で黙って入る）
O="$T/cloud"; mkdir -p "$O/.claude"; cp -R "$HERE/.claude/hooks" "$O/.claude/"; cp "$HERE/CHARTER.md" "$HERE/ROUTINE.md" "$O/"; printf 'state/\n' > "$O/.gitignore"
gt() { local d="$1"; shift; git -C "$d" -c user.email=t@t -c user.name=t -c core.hooksPath=/dev/null "$@"; }
git -C "$O" init -q; gt "$O" add -A; gt "$O" commit -q -m init
M="$T/mac"; git clone -q "$O" "$M" 2>/dev/null
PL="$M/state/.sessions/protected.last"
mr() { printf '%s' '{"session_id":"test-p","source":"startup"}' | CLAUDE_PROJECT_DIR="$M" bash "$M/.claude/hooks/restore-charter.sh" 2>/dev/null; }
WARN27='保護ファイルがコミットで変わりました'
OUT="$(mr)"
printf '%s' "$OUT" | grep -q '基準をこの clone に記録しました' && ! printf '%s' "$OUT" | grep -q "$WARN27" && grep -qE '^[0-9a-f]{40,64}$' "$PL" \
  && ok "restore: 初回は保護ファイルの基準を記録するだけ（警告しない）" || ng "restore: 初回の基準"
printf '\n- 試験の追記（クラウド）\n' >> "$O/CHARTER.md"; gt "$O" commit -qam cloud; gt "$M" pull -q --ff-only
OUT="$(mr)"
printf '%s' "$OUT" | grep -q "$WARN27" && printf '%s' "$OUT" | grep -q 'CHARTER.md' && ok "restore: pull で入った保護ファイルの変更を警告し、ファイルを示す" || ng "restore: pull で入った保護ファイルの変更を警告しない"
OUT="$(mr)"
printf '%s' "$OUT" | grep -q "$WARN27" && ng "restore: 一度知らせた変更を繰り返し警告した" || ok "restore: 一度知らせた変更は次の開始で繰り返さない"
printf 'x\n' > "$O/notes.txt"; gt "$O" add notes.txt; gt "$O" commit -q -m notes; gt "$M" pull -q --ff-only
OUT="$(mr)"
printf '%s' "$OUT" | grep -q "$WARN27" && ng "restore: 保護ファイル以外のコミットで警告した" || ok "restore: 保護ファイル以外のコミットでは警告しない"
printf 'local\n' > "$M/local.txt"; gt "$M" add local.txt; gt "$M" commit -q -m local
printf '\n- merge の試験\n' >> "$O/ROUTINE.md"; gt "$O" commit -qam cloud2; gt "$M" -c pull.rebase=false pull -q --no-edit >/dev/null 2>&1
OUT="$(mr)"
printf '%s' "$OUT" | grep -q "$WARN27" && printf '%s' "$OUT" | grep -q 'ROUTINE.md' && ok "restore: merge で入った保護ファイルの変更も警告する" || ng "restore: merge で入った変更を警告しない"
printf -- '--output=%s\n' "$T/pwned27" > "$PL"; printf '\n- 注入の試験\n' >> "$O/CHARTER.md"; gt "$O" commit -qam cloud3; gt "$M" -c pull.rebase=false pull -q --no-edit >/dev/null 2>&1
OUT="$(mr)"
[ ! -e "$T/pwned27" ] && ! printf '%s' "$OUT" | grep -q "$WARN27" && grep -qE '^[0-9a-f]{40,64}$' "$PL" && ok "restore: 記録に書かれた git の引数（--output=…）は使わず、基準を記録し直す" || ng "restore: 記録の引数の注入"
printf 'keep\n' > "$T/pl-target"; rm -f "$PL"; ln -s "$T/pl-target" "$PL"; mr >/dev/null
[ "$(cat "$T/pl-target")" = keep ] && [ -f "$PL" ] && [ ! -L "$PL" ] && ok "restore: 記録が記号リンクでも先を書き換えない" || ng "restore: 記号リンクの先を書き換えた"
cp "$PL" "$T/pl-before"; printf '\n- 無人の試験\n' >> "$O/CHARTER.md"; gt "$O" commit -qam cloud4; gt "$M" -c pull.rebase=false pull -q --no-edit >/dev/null 2>&1
OUT="$(printf '%s' '{"session_id":"test-p","source":"startup"}' | FABLE5_HEADLESS=1 CLAUDE_PROJECT_DIR="$M" bash "$M/.claude/hooks/restore-charter.sh" 2>/dev/null)"
printf '%s' "$OUT" | grep -q "$WARN27" && cmp -s "$PL" "$T/pl-before" && ok "restore: 無人実行では警告しても記録を進めない" || ng "restore: 無人実行で記録を進めた"
mr | grep -q "$WARN27" && ok "restore: 無人実行の後の開始でも警告する（人が見る）" || ng "restore: 無人実行で警告を使い切った"

# 記録がフォルダ（またはリンク）だと書けない: 「記録しました」と言わず、確かめられないと警告する（黙って検知が止まらない）
rm -f "$PL"; mkdir -p "$PL"; OUT="$(mr)"
printf '%s' "$OUT" | grep -q '通常のファイルではないため' && printf '%s' "$OUT" | grep -q '基準を記録できませんでした' && ! printf '%s' "$OUT" | grep -q '基準をこの clone に記録しました' \
  && ok "restore: 記録がフォルダなら「記録しました」と言わず警告する" || ng "restore: フォルダの記録"
rmdir "$PL"; mr >/dev/null

# 20) session-end: 最終プロンプトの docx を LUMINOUS_PRIVATE_DIR（非公開フォルダ）にも写す（Mark の依頼 2026-10-11）。中身が違うときだけ。危ない置き場には書かない
P20="$T/priv20"; mkdir -p "$P20"; DXP="$P20/☆ルミナス_最終プロンプト.docx"
sep() { CLAUDE_PROJECT_DIR="$D" PATH="$FN:$PATH" LUMINOUS_PRIVATE_DIR="$1" bash "$D/.claude/hooks/session-end.sh" </dev/null >/dev/null 2>&1; }
sep "$P20"; cmp -s "$DX" "$DXP" && grep -q '非公開フォルダへ写しました' "$D/state/.session-end.log" && ok "session-end: docx を非公開フォルダへ写す" || ng "session-end: 非公開フォルダへの写し"
touch -t 202001010000 "$DXP"; sep "$P20"; [ "$(find "$DXP" -newer "$DX" | wc -l | tr -d ' ')" = 0 ] && cmp -s "$DX" "$DXP" && ok "session-end: 中身が同じなら写し直さない" || ng "session-end: 同じ中身で写し直した"
printf 'old\n' > "$DXP"; sep "$P20"; cmp -s "$DX" "$DXP" && ok "session-end: 写しが古ければ写し直す" || ng "session-end: 古い写しを直さない"
rm -f "$DXP"; printf 'victim\n' > "$T/victim20"; ln -s "$T/victim20" "$DXP"; sep "$P20"
[ "$(cat "$T/victim20")" = victim ] && [ -L "$DXP" ] && grep -q 'docx の写し 失敗（写し先が通常のファイルではない）' "$D/state/.session-end.log" && ok "session-end: 写し先がリンクなら書かない（リンクの先を上書きしない）" || ng "session-end: リンクの写し先"
rm -f "$DXP"
mkdir -p "$D/privin"; sep "$D/privin"; [ ! -e "$D/privin/☆ルミナス_最終プロンプト.docx" ] && ok "session-end: このフォルダの中の置き場には写さない" || ng "session-end: フォルダの中へ写した"
sep "rel/priv"; [ ! -e "$D/rel/priv/☆ルミナス_最終プロンプト.docx" ] && grep -q 'docx の写し 失敗（LUMINOUS_PRIVATE_DIR が絶対パスではない' "$D/state/.session-end.log" && ok "session-end: 相対パス（~ を含む）の置き場には写さず「失敗」と書く" || ng "session-end: 相対パス"
sep "$T/nope20"; [ ! -e "$T/nope20" ] && grep -q 'docx の写し 失敗（LUMINOUS_PRIVATE_DIR のフォルダが無い）' "$D/state/.session-end.log" && ok "session-end: 無いフォルダは作らず「失敗」と書く" || ng "session-end: 無いフォルダ"
grep -q 'docx の写し 失敗（LUMINOUS_PRIVATE_DIR がこのフォルダの中）' "$D/state/.session-end.log" && ok "session-end: このフォルダの中の置き場は「失敗」と書く" || ng "session-end: フォルダの中の失敗の表示"
! grep -q "$P20" "$D/state/.session-end.log" && ok "session-end: ログに置き場のパスを書かない" || ng "session-end: ログにパス"
rm -f "$DXP"; mkdir -p "$D/data/codex_runs/.lock"; echo "$$ 0" > "$D/data/codex_runs/.lock/owner"; sep "$P20"
[ ! -e "$DXP" ] && ok "session-end: Codex の実行中は非公開フォルダへ写さない" || ng "session-end: 実行中に写した"
rm -rf "$D/data/codex_runs/.lock"; printf '日時: test\n' > "$D/data/.codex_violation"; sep "$P20"
[ ! -e "$DXP" ] && ok "session-end: Codex の違反が未処理なら非公開フォルダへ写さない" || ng "session-end: 違反の印で写した"
rm -f "$D/data/.codex_violation"
ls -a "$P20" | grep -q '^\.luminous-docx\.' && ng "session-end: 一時ファイルが残った" || ok "session-end: 一時ファイルを残さない"
printf '2026-10-11T00:00:00Z 試験\n' > "$D/data/.luminous_halt" 2>/dev/null || { mkdir -p "$D/data"; printf '2026-10-11T00:00:00Z 試験\n' > "$D/data/.luminous_halt"; }
sep "$P20"; [ ! -e "$DXP" ] && ok "session-end: 全体停止中は非公開フォルダへ写さない" || ng "session-end: 停止中に写した"
rm -f "$D/data/.luminous_halt"

echo "---- $pass passed, $fail failed"
[ "$fail" = 0 ]
