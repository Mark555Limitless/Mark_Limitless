# Mac デスクトップ版への切替の監査（2026-10-10）

> Mark の指示「クラウドセッション版から Mac デスクトップ版に戻してください。それにより改善されるものがないか監査して、改善および修復できるものは即実行してください。」
> 方法: Workflow で 7 つの観点（hooks の bash・scripts の bash・tools の bash・Python 3.9・デスクトップ版の環境・初回手順・ファイルシステムの意味論）を並列に洗い出し（138 件）、批評役が 17 件を追加、重複を除いて 124 件を、各件 2 つの視点（Mac で本当に起きるか／何が壊れるか）で Opus が反証した。**確定 56 件・反証で落ちたもの 68 件。** 途中で利用枠の上限に当たり、91 件分の反証と最終整理は未完（§6）。
> 前提とした Mac の事実: /bin/bash 3.2、BSD ユーザランド、jq は既定で無い、/usr/bin/python3 は Xcode CLT のスタブ（CLT が無いと exit 1）、APFS は大文字小文字を区別せず NFD で保存、デスクトップアプリは .zshrc の export を引き継がないことがある。

## 1. 切り替えて改善されること（事実）
- hooks と権限が効く（クラウドでは `.claude/settings.json` が読み込まれていなかった）。全体停止 B・保護ファイルの確認・Stop の関門・鍵の早期警告が実際に働く
- Codex（ChatGPT アプリ同梱）を `tools/codex_impl.sh`・`codex_opinion.sh` で直接呼べる（Mark の中継が要らない）
- `.env` の鍵（Gemini・Jev）が使え、`orch.health` の本物の点検ができる
- 全体停止 `luminous_halt.sh` の実効性（印で止まる・`off` は端末だけ）を主張できる
- Obsidian 同期・最終プロンプトの docx 再生成が本来の場所で動く

## 2. 確定した指摘（56 件）の要点
重さは反証後の値。重複する指摘はまとめた。

**中（守りが効かなくなる・作業が止まる）**
1. **python3 の「あるが動かない」で hooks が素通し**（`_lib.sh`・`guard-protected.sh`・`guard-secrets.sh`・`codex-lock-guard.sh`・`stop-gate.sh`・`restore-charter.sh`）: `command -v python3` は Mac では常に成功する（CLT 無しでもスタブがある）。jq が無いとスタブに落ち、JSON が解析できず、保護ファイルへの書き込み・鍵ファイルの読み取り・`git commit` の検査が exit 0 で通る。SessionStart の注入が 0 バイトになる。Stop のループ防止が効かない。→ 実際に動くかを確かめる `hook_py_ok` に替え、解析できないときは止める側へ
2. **大文字小文字を区別しない APFS**（`guard-protected.sh`）: `sed -i '' … charter.md`・`cat .ENV` が通る。→ 一致を大文字小文字無視に
3. **NFD 正規化**（`guard-protected.sh`）: 「最終プロンプト」の「プ」が「フ」＋U+309A で保存されていると保護の名前に当たらない。→ NFC に正規化して検査（python3 が動かないときは NFD 形も含める）
4. **`secret-scan.sh` の括弧式の `\-`**: ハイフンが文字種に入らず、ハイフン入りの鍵を見逃す。→ 修正と試験
5. **`safe_python` がスタブを選ぶ**（`_codex_common.sh`）: `-x` だけで選ぶため、Mac の CLT 無しでは Codex の検査器が動かず「作業フォルダ内に .git があります」という誤った案内になる。→ 実行できることを確かめて選ぶ（クラウドでも偶然この状態になり、Codex ラッパーの試験が全滅して再現した。§5）
6. `stop-gate.sh` が jq 無しで block の JSON を出せない／`test-hooks.sh` が jq 無しの Mac で 4 件落ちる
7. `sync-obsidian.sh`: mkdir・cp の失敗が rc 0 で隠れる。vault 側の編集の退避が更新時刻だけに頼る
8. `.DS_Store`（`scope_check.py`）: Finder が Codex の実行中に作る・書き換えると偽の違反になる。→ 基本名 `.DS_Store`・通常ファイル・実行属性なし・1 MiB 以下だけを「記録ファイルの変更」扱いにする（守りを少し緩める判断。境界は違反のまま）
9. `setup.sh`: 論理パスと実体パスの不一致で `core.hooksPath` が誤った相対パスになる
10. 試験の Mac 前提: 偽 Codex が `chflags uchg` の印を消せない／大文字小文字で `.GIT` と `.Git` が同じになる／`~/.gitconfig` の署名設定が混ざる／`.venv/bin/python` を直書き／`uname -s` の分岐

**軽**: `luminous_halt.sh` の `-I` と `PYTHONIOENCODING`（効かない → `-X utf8`）、`CDPATH`、ロックの PID の使い回し、`cleanup-public.sh` の相対パスで無限ループ、`export-public.sh` の最終行の改行・CRLF、`set_env_key.sh` の `check-ignore` がフォルダ不在で失敗、`requests` の先頭 import で `orch.health` が落ちる、READ の動詞（pbcopy・open・hexdump・ditto…）、環境変数の一覧の不足（ROUTINE §5）、README の `python3 -m orch.health`、`settings.local.json.example` の env の例、ほか。

**任意**: hooks の python3 の起動回数、`find_codex` に `~/Applications`、型注釈。

## 3. Mac でだけ確かめること（7 件。手順）
1. **デスクトップアプリ同梱の Claude Code の版**: `PostModelSwitch` を知らない古い版だと、`settings.json` 全体（hooks も permissions も）が黙って読まれない可能性がある。起動後に `/hooks` でルミナスの hooks が並ぶこと、`true luminous-hook-canary` が断られることを確かめる（canary が「読まれていない」の目印）
2. **環境変数**: デスクトップ版の Bash で `echo "${LUMINOUS_OBSIDIAN_DIR:-unset}"` を実行し、`.claude/settings.local.json` の `env` で届いているか見る。届かなければ Obsidian 同期は毎回スキップで、失敗にも見えない
3. **`/usr/bin/python3` の実体**: `xcode-select -p; /usr/bin/python3 -c pass; echo $?` と `ls /usr/bin/jq`。CLT が無ければ hooks は（修正後）止める側に倒れるが、設定が要る: `xcode-select --install`
4. **`ps` の非 ASCII**: Codex のラッパーを絶対パスで起動した状態で `bash tools/luminous_halt.sh on 試験` を打ち、「TERM を送りました」が出るか。出なければロケールのエスケープが原因（安全側だが停止が届かない）
5. **`chflags uchg`**: `on` の後に `ls -lO data/.luminous_halt` で `uchg` が付くこと、`off` で外れること
6. **Codex のサンドボックス**: `tools/codex_impl.sh` の実行で、Codex が `setsid` を許され、終了時にグループごと止まること。`-o` の出力が安全な置き場に書けること
7. **個々の hooks と権限が効いているか**（canary の補い。canary が示すのは halt-guard が起動して JSON を読めたことだけ）: clone の `ルミナス/` で開いたセッションで、権限のモードは既定のまま、**鍵を入れる前**（HANDOVER の Mac の手順 8 より前）に行う。どれも害は無い
   - (a) Bash で `head -c 0 .env` → 「ブロック（guard-protected）: 鍵・資格情報らしきファイルを Bash で読もうとしています」と断られる（halt-guard は通すので、guard-protected の配線の確認になる。通っても 0 バイトしか読まない）
   - (b) Bash で `git commit --no-verify --dry-run` → 「ブロック（guard-protected）: git フックの迂回…」と断られる（通っても dry-run なので commit は作られない）
   - (c) `/permissions` の ask に `Edit(/CHARTER.md)`・`Edit(/docs/review.md)` などが並ぶ。Edit で `docs/review.md` の末尾に空行を足そうとすると確認のダイアログが出る（「いいえ」を選ぶ）。ダイアログが出ずに変わったら、Mark が端末で `git diff -- docs/review.md` が空行 1 つだけであることを見てから `git checkout -- docs/review.md` で戻し、「権限の先頭の `/` が `ルミナス/` を根にしていない（git の根の `Mark_Limitless/` を根にしている恐れ）」と HANDOVER に書く
   - (d) `/model` で切り替えると、`tail -n 1 state/escalations.log` に機械記入の行（`<時刻> | (作業名を追記) | <前のモデル> | <後のモデル> | …`）が 1 行増える（PostModelSwitch）
   - (e) 試しのセッションを 1 回終えてから開き直し、`tail -n 3 state/.session-end.log` に新しい `--- <時刻> SessionEnd` の行がある（SessionEnd は失敗しか警告されないので、発火しなくても気づかない。閉じ方ごとの確認は §8.7）
   - どれかが期待どおりでなければ、HANDOVER に書いて Phase 0 の門を通さない

## 4. 反証で落ちた指摘の代表（採らなかった理由）
- 「デスクトップ版の hooks の PATH は `/usr/bin:/bin:/usr/sbin:/sbin` だけ」→ 公式文書（Local sessions の節）と食い違う。前提が成り立たない
- 「BSD sed は `s///I` を知らない」→ Apple の text_cmds の sed のソースで `I` フラグに対応していることを確認
- 「クラウドの Linux 製 `.venv` が Mac に持ち込まれる」→ `.venv/` は git 管理外
- 「`codex-lock-guard` が解析できないと素通し」→ 9 行目で先に実行中かを見ており、筋書きが成り立たない
- 「`.env` の `~` が展開されない」→ 読み方の説明は正しいが、実害の経路が無い

## 5. 事故: 監査の反証役がクラウド環境を改ざんした
- 何が起きたか: 反証役の数体が「CLT 無しの Mac」を模すために、**scratchpad の PATH shim ではなくこのコンテナの `/usr/bin/uname` と `/usr/bin/python3.13` を偽のスクリプトで上書き**し、復元し合ったあと最終的に偽物が残った。`uname -s` が Darwin を返し、`python3` は xcrun のエラーで exit 1。`.venv`（3.13）も巻き添えで動かなくなった。1 体は Claude Code の安全確認（自動モードの迂回）に警告されている
- 復旧: `uname` はパッケージの原本（dpkg の md5 と一致）で復元。`python3.13` の本体は外部からの取り込みが安全確認で止められたため復元できず、`.venv` を無傷の `python3.12` で作り直して作業を続けた。影響はこのコンテナ限り（次のセッションは新しい環境）。リポジトリのファイルは `git status` で無変更を確認
- なぜ起きたか: 指示に「ファイルを変更しない」とは書いたが、「システムの場所を変えない」「Mac を模すのは PATH shim だけ」と明示していなかった。並列の反証役が同じ環境を共有していた
- 今後: Workflow のサブエージェントへの共通の禁止事項に「リポジトリの外（/usr・/etc・$HOME の設定）を変更しない。模すのは scratchpad の shim と PATH だけ」を必ず入れる（本日の実装の Workflow から適用）。終了後に `dpkg -V` で環境の改ざんを確かめる。この事故は ROUTINE の「定期監査」の項目に加えることを提案する

## 6. 未完と次の一手
- 未反証 91 件（利用枠の上限で失敗）: 対象は主に `restore-charter.sh`・`setup.sh`・`.gitignore`・`scope_check.py`・`HANDOVER.md`・`ROUTINE.md`・`README.md` の指摘。次に別の Workflow で反証を続ける（確定分の実装が終わってから）
- 実装の結果は §7 に追記する

## 7. 実装の結果（2026-10-10 深夜）
- 3 群（A: tests／B: tools・orch／C: hooks・scripts・docs）を Opus の実装役が並列で実装（司令塔の代理。Codex はクラウドに無い）。Mac の司令塔が実測した bash 3.2 の不具合（`docs/specs/20261010_mac_bash32_tests.md` (a)〜(d)）もここで実装し、同指示書は実施済み
- 変更: 29 ファイル＋新規 `tests/test_mac_compat.py`（+686/−155 行）。保護ファイル（`.claude/hooks/` 8 本・`scripts/secret-scan.sh`・`sync-obsidian.sh`・`ROUTINE.md`・`README.md`・`tools/`・`orch/`）は Mark の「即実行」の指示に基づき適用。`settings.json`・CLAUDE.md・CHARTER.md・VIRTUAL_MARK.md は変えていない
- 試験: pytest 275 件通過・1 件 skip（Mac 専用の uchg の試験）、hooks 191 件通過（元 112 ＋ 新規 79）。bash 3.2・jq 無し・Python 3.9・利用者の git 設定を仕込んだ条件でも通過（審査役の実行）
- 審査: 2 視点とも 1 回目 REJECT（審査 1: タブ区切りの素通し・初回同期で vault の編集が消える／審査 2: 試験側の pty・署名・除外設定）→ 反映 → 2 回目 APPROVE
- 守りを少し緩めた点（Mark の確認を求める）: `scope_check.py` の `.DS_Store`（基本名が `.DS_Store`・通常ファイル・実行属性なし・1 MiB 以下・リンク数 1・途中に `.DS_Store` の名前なし のときだけ違反にせず「記録ファイルの変更」として一覧に出す）
- 見送り（次の機会）: hooks の python3 の起動回数（jq の無い Mac で Bash 1 回あたり 5 回）、`echo $(<.env)` の形の読み取り、行継続の `sed \⏎ -i`、`GIT commit`・`/usr/bin/git commit` の拾い漏れ（本命の pre-commit は効く）、`codex-lock-guard` のパス比較の大文字小文字
- Mac でだけ確かめること（追加）: `/bin/bash 3.2.57` で `tests/test_mac_compat.py` と `scripts/test-hooks.sh` が通ること（クラウドの bash 3.2.33 では `$RC）` の不具合が再現せず、静的な検出でしか確かめていない）、Finder を開いたままの `codex_impl.sh` で `.DS_Store` が「記録ファイルの変更」になること、BSD の `ps -o etime=` がスリープを含むこと（含まないとロックの誤判定）、CLT の無い Mac で `safe_python` と `trunc` がダイアログを出すか、`~/Applications/ChatGPT.app` に codex があるか、`test-hooks.sh` の BSD `cp -p`・`locale -a` の en_US.UTF-8

## 8. Mac でだけ確かめること（第 2 弾。2026-10-11、監査の残りの反証から）
- クラウドでは確かめられなかった 9 件。§3 の後に、Mac の司令塔（アプリの Bash）か Mark（端末）が行う。どちらで打つかは各項に書いた
- コマンドは clone の `ルミナス/` で打つ（以下、clone の根を `<clone>` と書く）。8.2 の開き直しと 8.7 の終了のほかは、読むだけか使い捨ての一時フォルダだけを使う
- 結果は HANDOVER に書く。**ローカルの絶対パス・vault の場所・PATH の中身は書かず**、「同じ／違う」「期待どおり／違った点」だけを書く。期待と違ったときの次の一手も各項に書いた

### 8.1 起動フォルダと入れ子の .git の誤検知（idx0。アプリの Bash）
```bash
git rev-parse --show-toplevel
ls -d ./.git 2>/dev/null
d="$(dirname "$(pwd)")"; while :; do [ -e "$d/.git" ] && echo "祖先の .git: ${d}/.git"; [ "$d" = / ] && break; d="$(dirname "$d")"; done
ROOT="$(pwd)" /bin/bash -c '. .claude/hooks/_lib.sh; hook_nested_git'
ls -d ~/.git ~/Documents/.git 2>/dev/null
```
- 期待: toplevel が `<clone>`（Mark_Limitless）、`./.git` は無い、祖先の .git は `<clone>/.git` だけ、`hook_nested_git` の出力は空、最後の `ls` も何も出ない
- 違えば: 祖先に別の .git がある（ホームや書類のフォルダが git 管理）と、hooks の入れ子 .git の検知が誤作動する。どこにあったかを HANDOVER に書き、片付けるかを Mark が決める

### 8.2 hooks に届く環境（idx1。アプリの Bash と端末の両方）
デスクトップアプリのセッションを 1 回閉じてから開き直す。アプリの Bash で次を実行し、端末（zsh）で打った結果と比べる。
```bash
tail -n 8 state/.session-end.log
echo "PATH=${PATH}"
for c in node npm jq python3 git timeout gtimeout; do printf '%s %s\n' "$c" "$(command -v "$c" || echo none)"; done
echo "OBS=${LUMINOUS_OBSIDIAN_DIR:-unset} TZ=${LUMINOUS_TZ:-unset} GATE=${LUMINOUS_GATE_MODE:-unset}"
/usr/bin/python3 -c pass; echo "py=$?"
```
- 期待: `.session-end.log` に「sync-obsidian: … （n 件）」があり、「未設定のためスキップ」と「node が無い」が無い。開き直したときの SessionStart の注入に「!!! git フック」「動く python3 もありません」「点検の結果が出ませんでした」「前回の SessionEnd で失敗」が出ない
- 違えば: アプリと端末で見つかる道具（node・jq・python3）や値が違う。足りない値は `.claude/settings.local.json` の `env` に書く（書き方は `obsidian/README.md`）。道具が見つからないなら、どの名前が `none` だったかを HANDOVER に書く

### 8.3 グローバルの SessionStart（idx2。端末。読むだけ・値は出さない）
ルミナスのセッションで `/hooks` を開き、SessionStart に `restore-charter.sh` 以外（User の設定やプラグインのもの）があるかを見る。端末で次を実行する（jq が無ければ下の python3 の形で）。
```bash
jq '.hooks.SessionStart' ~/.claude/settings.json
jq -r '(.env // {}) | keys[]' ~/.claude/settings.json
ls -l "/Library/Application Support/ClaudeCode/managed-settings.json" 2>/dev/null
```
```bash
python3 - <<'PY'
import json, os
d = json.load(open(os.path.expanduser("~/.claude/settings.json")))
print(json.dumps(d.get("hooks", {}).get("SessionStart"), ensure_ascii=False, indent=1))
print(sorted((d.get("env") or {}).keys()))   # 名前だけ。値は出さない
PY
```
- 見つかったスクリプトを `cat` で読み、確かめる: `FABLE5_HEADLESS` の判定があるか、`CLAUDE_PROJECT_DIR` か cwd で Fable5 のフォルダ以外では何もしない条件があるか、副作用（ファイルの書き込み・送信）が無いか
- 最後に、新しいセッションの司令塔に「受けた文脈に Fable5 AI NEWS Select の指示があるか」を 1 行で答えさせる
- 違えば（ルミナスのセッションに Fable5 の指示が入る・副作用がある）: HANDOVER に書き、グローバルのフックに条件を足すかを Mark が決める（原本の設定なので、ルミナスからは変えない）

### 8.4 worktree（idx8。アプリの画面と Bash）
New session の画面で worktree のオプションが既定でオフか、Settings の Worktree location が空かを見る。普段のセッションの Bash で:
```bash
echo "$CLAUDE_PROJECT_DIR"; pwd -P; git rev-parse --show-toplevel; git worktree list
ls -d "$(git rev-parse --show-toplevel)/.claude/worktrees" ./.claude/worktrees 2>&1
```
- 期待: `CLAUDE_PROJECT_DIR` と `pwd -P` がどちらも `<clone>/ルミナス`、`git worktree list` は本体の 1 行だけ、`ls` はどちらも No such file
- 違えば: worktree ができていると、その中の `.git` を hooks が入れ子の .git として止める。`.claude/worktrees/` は根の .gitignore で除外済み（2026-10-11）なので公開はされない。worktree のオプションを切り、`git worktree list` の結果を HANDOVER に書く

### 8.5 安全な置き場のずれと ps の非 ASCII（idx16。端末とアプリの Bash の両方）
```bash
bash -c 'echo "${LUMINOUS_SAFE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/luminous-codex}"'
```
- 期待: 端末とアプリで同じ（全体停止の記録の突き合わせが同じ置き場を見る）
- 違えば: `grep -nE 'XDG_CACHE_HOME|LUMINOUS_SAFE_DIR' ~/.zshrc ~/.zprofile ~/.zshenv 2>/dev/null; launchctl getenv XDG_CACHE_HOME` で原因を探し、「安全な置き場は `LUMINOUS_SAFE_DIR` に一本化する（`XDG_CACHE_HOME` を見ない）」を次の修正の候補として HANDOVER に書く

続けて、ルミナス/ で次の 2 行を実行する（末尾の `; :` は、bash が ps に置き換わって自分の行を見失うのを防ぐため）。
```bash
bash -c 'ps -o command= -p $$; :' x "$PWD/tools/codex_impl.sh"
LC_ALL=C bash -c 'ps -o command= -p $$; :' x "$PWD/tools/codex_impl.sh"
```
- 期待: どちらも「ルミナス」がそのまま出る
- 違えば（`?` や `\M-…` などのエスケープで出る）: `luminous_halt.sh on` が、実行中のラッパーを ps の行で見分けられず TERM を送れない（安全側。ラッパー自身が終了後に印を見て止まる）。重さを「中」に上げて HANDOVER に書く

### 8.6 論理パスと実パス・大文字小文字（idx17。端末）
```bash
git rev-parse --show-toplevel; echo "L=$(pwd)"; echo "P=$(pwd -P)"
```
- L と P が違えば、`tools/scope_check.py` の `_has_git_above` を実パスで比べる修正を次の候補に入れる

大文字小文字のずれを、使い捨てのフォルダで確かめる（丸括弧の中で動かすので、今のフォルダは変わらない）。
```bash
( T="$(mktemp -d)" && mkdir "$T/Lum" && (cd "$T/Lum" && git init -q) && cd "$T/lum" && git rev-parse --absolute-git-dir && python3 -I -S -c 'import os;print(os.path.realpath(os.path.join(os.environ["PWD"],".git")))'; cd / && rm -rf "$T" )
```
- 2 本のパスが `Lum` と `lum` でずれれば、`_is_real_git` を「同じファイルか」（samefile）で比べる修正を次の候補に入れる
- `cd: …/lum: No such file or directory` と出たら、そのボリュームは大文字小文字を区別する（ずれは起きない）

### 8.7 SessionEnd が発火するか（idx34。アプリ）
デスクトップアプリでセッションを開いて 1 往復する。そのあと (a) セッションを閉じる (b) `/clear` (c) Cmd+Q でアプリを終える、をそれぞれ試し、毎回、次のセッション（または端末）で:
```bash
date -u; tail -n 6 state/.session-end.log
```
- 期待: その時刻の `--- <時刻> SessionEnd` と、sync-obsidian の行・docx の行（「最終プロンプトに変更なし」など）の両方が増えている。端末の `claude` を `/exit` で閉じた場合とも比べる
- 違えば（(a)〜(c) のどれでも増えない）: Obsidian 同期と docx の再生成が黙って止まる。restore-charter.sh に「前回の SessionEnd の記録が無い」警告（startup のときだけ）を足す案を出す（保護ファイル。Mark の承認）

### 8.8 package-lock.json の中身（idx6。Mark の決定 2 のとおりコミットする前の確認）
```bash
cd <clone>/ルミナス
git status --short -- package-lock.json
grep -m1 '"lockfileVersion"' package-lock.json
grep -c '"resolved":' package-lock.json
grep -c '"resolved": "https://registry.npmjs.org/' package-lock.json
grep -c '"integrity":' package-lock.json
grep -A2 '"node_modules/docx"' package-lock.json
```
- 期待: `resolved` の 2 つの数が同じ（すべて npm の公式の置き場）、`integrity` がそろっている、docx が 9.x。コミットの前は、新しいセッションの SessionStart に「!!! 注意: 憲章・権限・hooks・自走範囲に未コミットの差分」と `?? package-lock.json` が出る（コミット後は出なくなる）
- 違えば: コミットせず、違った数を HANDOVER に書く

### 8.9 （任意）直し済みの回帰の確認（idx7・12・13・15・21・35・37。端末）
```bash
/bin/bash scripts/test-hooks.sh 2>&1 | grep -E '^FAIL|^PASS (setup|mac:)|^---- '
.venv/bin/python -m pytest -q tests/
/bin/bash -c 'set -u; . tools/_codex_common.sh; n=X_NOT_SET_ANYWHERE; [ -n "${!n+x}" ] || echo ok'
/usr/bin/perl -e 'alarm shift; exec @ARGV or exit 127' 3 /bin/sleep 10; echo "rc=$?"
find "${TMPDIR%/}/pytest-of-$(id -un)" -flags +uchg 2>/dev/null | head
```
- 期待: `FAIL` の行が無く、`setup` の 3 行と「mac: restore は…」が `PASS`、最後の行が `---- N passed, 0 failed`。pytest は全件通る。`ok` と出る。`rc=142`（3 秒の alarm で止まる）。`find` の出力は空（pytest の一時フォルダに uchg の印が残っていない）
- 違えば: 落ちた試験の名前と出力をそのまま HANDOVER に貼る（直すのは司令塔）
