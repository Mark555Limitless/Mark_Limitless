#!/usr/bin/env bash
# hooks・スキャナ・同期の再現テスト（憲章 I-3: 実測を再現可能に）。使い捨てディレクトリだけに書き込む。
set -u
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

# 9) Codex 実行中の編集ガード・SessionEnd の見送り・違反の印・入れ子の .git（git を使う前に検知）
LG() { printf '%s' "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$1\"}}" | bash "$R/.claude/hooks/codex-lock-guard.sh" >/dev/null 2>&1; echo $?; }
[ "$(LG "$R/HANDOVER.md")" = 0 ] && ok "lock-guard: Codex が動いていなければ通す" || ng "lock-guard: 未実行"
mkdir -p "$R/data/codex_runs/.lock"; echo "$$ 0" > "$R/data/codex_runs/.lock/owner"
[ "$(LG "$R/HANDOVER.md")" = 2 ] && ok "lock-guard: 実行中はフォルダ内の編集を止める" || ng "lock-guard: 実行中"
[ "$(LG "$R/newdir/new.md")" = 2 ] && ok "lock-guard: まだ無いファイルも止める" || ng "lock-guard: 新規ファイル"
[ "$(LG "$T/outside.md")" = 0 ] && ok "lock-guard: フォルダの外は通す" || ng "lock-guard: フォルダの外"
bash "$R/.claude/hooks/session-end.sh" </dev/null >/dev/null 2>&1
grep -q '見送り' "$R/state/.session-end.log" 2>/dev/null && ok "session-end: Codex 実行中は docx 再生成を見送る" || ng "session-end: 実行中の見送り"
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
rm -f "$HALT"
OUT="$(printf '%s' "$SID3" | bash "$R/.claude/hooks/restore-charter.sh")"
printf '%s' "$OUT" | grep -q '全体停止中' && ng "restore: 印なしで停止の表示が出る" || ok "restore: 印なしでは停止の表示を出さない"

echo "---- $pass passed, $fail failed"
[ "$fail" = 0 ]
