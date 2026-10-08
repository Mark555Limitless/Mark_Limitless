# 20261008_global_halt

> Mark の決定（2026-10-08）「実行の制御を独立した部品にする。ただし最初はファイルで」の最初の一歩。
> 背景は `docs/proposals/20261008-codex-proposal-response.md` §2 の A。**状態: 指示書 v0.2（未実装）。**
> v0.1（`20261008_global_stop`）は Opus の反証審査で REJECT。v0.2 は停止に関する指摘をすべて反映し、名前を「停止（stop）」から「全体停止（halt）」に変えた（終了の関門 `LUMINOUS_STOP_GATE` と取り違えないため）。
> AGENTS.md により Codex は `.claude/`・`ROUTINE.md` を変えられないため、**A（Codex）と B（司令塔、Mark の確認つき）に分ける**。

## 目的（1〜3行）
Mark が 1 つの印で、**この機械の中の**ルミナスの新しい作業（外部AIの呼び出し・Codex の実行・Claude Code の書き込みや送信の道具・サブエージェントの起動）を最優先で止められるようにする。
印はこの機械の中で再起動しても残り、AI 側からは付けられるが外せない（外せない根拠は B の hook と権限の設定。端末の判定は、うっかり防止にすぎない）。
**別の機械（Mac とクラウド）は止まらない**。クラウドの止め方は下の「クラウドで止めるとき」の手順で行う。

## 印と道具（共通の約束）
- 印: `<ルミナスの根>/data/.luminous_halt`（git 管理外）。場所は固定し、`ORCH_DATA_DIR` などの環境変数では動かさない。**ファイルでもリンクでも、名前があれば全体停止中**（リンク先が無くても停止中）
- 1 行目に日時と理由を書く。理由は「データ」として扱い、1 行・200 字で切り、制御文字を落としてから表示する
- `bash tools/luminous_halt.sh on [理由]` — 印を作る（誰が実行してもよい）。作れなかったら 0 以外で終わり「止まっていない」と表示する。Codex の実行中なら、ロックの持ち主に TERM を送る（下の「PID の確かめ方」を通ったときだけ）
- `bash tools/luminous_halt.sh status` — 停止中かと理由を表示（Mark の端末用）
- `bash tools/luminous_halt.sh off` — 印を消す。標準入力が端末でなければ断り、「解除」と打たせる（うっかり防止。擬似端末で破れるので守りではない）。消す前に Mac では変更禁止の属性を外す（B-6）
- on・off は `logs/halt.log` に 1 行（日時・on/off・理由の先頭 80 字）。off は git で管理する `state/halt.log` にも 1 行残す

### PID の確かめ方（TERM を送る前）
- `data/codex_runs/.lock/owner` の 1 列目が数字だけで 2 以上、かつ `ps -p <PID> -o command=` に `codex_impl.sh` か `codex_opinion.sh` が含まれるときだけ、そのプロセスグループへ TERM を送る。それ以外（`-1`・0・文字・別のプロセス）は送らず、その旨を表示する
- owner がまだ書かれていない（ロックのディレクトリだけある）ときは、1 秒待って読み直す。それでも無ければ送らない（ラッパーが起動の直前に印を見て止まる）

## A. Codex に渡す部分

### 触ってよいファイル
<!-- ALLOWED -->
tools/luminous_halt.sh
tools/_codex_common.sh
tools/codex_impl.sh
tools/codex_opinion.sh
tools/scope_check.py
orch/config.py
orch/decisions.py
orch/gemini.py
orch/jev.py
tests/test_tools.py
tests/test_decisions.py
tests/test_gemini.py
tests/test_jev.py
<!-- /ALLOWED -->

### 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出し・上記以外のファイル・`.claude/`・`ROUTINE.md`・`AGENTS.md` の変更

### 変更
1. `tools/luminous_halt.sh` を新設（上の「印と道具」「PID の確かめ方」のとおり。bash 3.2 で動くこと。`set -u`。印の場所はスクリプトの置き場所から決める）
2. `tools/_codex_common.sh`: `codex_disabled` が、印（`-e` か `-L`）があれば真を返す。**変えるのはこの関数の数行だけ**
3. `tools/codex_impl.sh`: 全体停止の確認を、今の位置に加えて**ロックを取った後**と**Codex を起動する直前**にも行う。停止中の表示に「全体停止中（data/.luminous_halt）」を出す
4. `tools/codex_opinion.sh`: Codex を前面ではなく裏で起動して `wait` し、TERM を受けたらプロセスグループごと止める（`codex_impl.sh` と同じ形）。起動の直前にも全体停止を確かめる
5. `tools/scope_check.py`: 印を MARKER_GLOBS に加える。**新しく作るのは中身があっても可、消すのは違反**（Codex に消させない）
6. `orch/config.py`: `global_halt() -> bool` を足す。場所はパッケージの位置から決めた `<根>/data/.luminous_halt` に固定し、`os.path.lexists` で調べる。`disabled(vendor)` は全体停止中なら真
7. `orch/decisions.py`・`orch/gemini.py`・`orch/jev.py`: 全体停止中は外部AIも `claude -p` も呼ばず、**専用の例外 `config.GlobalHalt` を投げる**（既定値で続けない。不変条件 4 の「失敗しても本流を止めない」の例外）。コマンドとして呼ばれたときは終了コード 6（全体停止）で終わる。影ログ・記録には「全体停止中」を残す

### テスト（陽性・陰性・境界値。外部 API はモック）
- `luminous_halt.sh`: on で印ができる／作れない場所では 0 以外／status／端末でない off は断って印が残る／正しい PID には TERM が送られる／owner が `-1`・`0`・文字・関係の無い PID のときは送らない／owner が遅れて書かれる場合
- 印がリンク（リンク先なし）でも停止中と判定される（シェル・Python とも）
- `ORCH_DATA_DIR` を別の場所にしても、Python 側が停止を見落とさない
- `decisions.ask`・`gemini`・`jev.call`: 停止中は `GlobalHalt`、外部も `claude -p` も呼ばれない
- `codex_impl.sh`: ロックを取った後・起動の直前に印ができた場合に、Codex を起動せず止まる（偽の codex で）
- `codex_opinion.sh`: 実行中の TERM でプロセスグループごと止まる
- `scope_check.py`: 実行中に印が作られても違反にならない・印を消すと違反

### 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）
- `git diff --stat` が ALLOWED のファイルだけ
- 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）では、特に「PID の確かめ方」「印を消す経路が無いこと」「起動の直前の競合」「`_codex_common.sh` の変更が `codex_disabled` の数行だけであること」を名指しで確かめる（Codex に Codex を止める仕組みを書かせるため）
- 最後に変更ファイル・要点3行・未解決の点

## B. 司令塔が行う部分（保護ファイル。Mark の確認つき。A の審査が APPROVE の後。Mac の正本で）

1. `.claude/hooks/halt-guard.sh` を新設し、`PreToolUse` にすべての道具（matcher `*`）で登録する
   - **JSON を読む前に、まず印の有無（`-e` か `-L`）を見る。** 印があれば、その後のどの失敗（jq が無い・壊れた入力・未定義変数）でも終了 2（止める）にする
   - 印があるとき通すのは Read・Grep・Glob と、止める方向・質問の道具（TaskStop・AskUserQuestion）だけ。**Bash は一切通さない**（停止中であることと理由は、断るときの文で出す）
   - 無人実行（`FABLE5_HEADLESS=1`）でも素通しにしない。短い timeout を付ける
2. `.claude/settings.json`: `permissions.deny` に印の編集（`Edit`・`Write` の `data/.luminous_halt`）を足す。`guard-protected.sh` の保護の対象に `luminous_halt` を足す
3. `stop-gate.sh`: 全体停止中は終了を止めない（閉じ込めない）
4. `restore-charter.sh`（SessionStart）: 全体停止中なら最初に大きく表示する（理由は「データ」として、1 行・200 字・制御文字なし）
5. `session-end.sh`: 全体停止中は docx の再生成を見送る
6. Mac では on のときに印へ変更禁止の属性（`chflags uchg`）を付け、off のときに外す（`luminous_halt.sh` に入れてよい。A の ALLOWED の範囲）
7. `scripts/test-hooks.sh` に陽性・陰性のテスト（壊れた入力・jq なしでも止まる、TaskStop は通る、Bash は通らない）。`ROUTINE.md` §5 の hooks の表に 1 行（`LUMINOUS_STOP_GATE` との違いも 1 行）
8. 新しいセッションを開いて、実際に止まることを確かめる（hooks は開始時に読み込まれるので、登録の前から動いているセッションには効かない）
9. 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）

## クラウドで止めるとき（印は効かない）
- Claude のアプリの画面で、そのセッションを止める（または閉じる）
- 予約した実行（Routine・send_later）は、アプリの Routines の画面で無効にする（新しいコンテナには印が無いので、止まらない）
- クラウドのセッションにはルミナスの hooks が効いていない（2026-10-08 に確認。`docs/proposals/20261008-autonomy-grants.md` §0）

## C. 文書だけの部分（司令塔。コードなし）
- 失敗の種類で対応を分ける表（回答 §2 の D）を、基本構成の提案 §2.3 に入れる（認証切れ・上限・通信は「上位モデルへ上げる」理由にしない）
- 評価の記録に版・日付・不確実性を付ける型（回答 §2 の E）を `docs/eval-design.md` に入れる

## 残る点（Phase 2 以降）
- **機械をまたいで止める方法**（git で管理する停止の印を、Mac とクラウドの両方が開始時と操作の前に見る、など）
- 停止の前に裏で起動した Bash・Monitor は動き続ける（TaskStop で止める）
- 実行中の Claude Code の道具の呼び出しは、次の呼び出しから止まる（今の 1 回は止められない）
- 止めた後に遅れて返ってきた外部AIの答えを捨てる仕組み（判断層は呼ぶ前にだけ見る）
- クラウドの環境側の Stop hook（未コミットの変更があると「コミットして push せよ」と言う）は、このプロジェクトから制御できない
- 予算の予約と精算（回答 §2 の B）、外部操作の状態（同 C）、権限の記録（同 F）
