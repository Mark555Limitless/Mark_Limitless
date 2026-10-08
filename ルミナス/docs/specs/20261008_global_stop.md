# 20261008_global_stop

> Mark の決定（2026-10-08）「実行の制御を独立した部品にする。ただし最初はファイルで」の最初の一歩。
> 背景は `docs/proposals/20261008-codex-proposal-response.md` §2 の A。**状態: 指示書（未実装）。**
> AGENTS.md により Codex は `.claude/`・`ROUTINE.md` を変えられないため、**A（Codex）と B（司令塔、Mark の確認つき）に分ける**。

## 目的（1〜3行）
Mark が 1 つの印で、ルミナスの新しい作業（外部AIの呼び出し・Codex の実行・Claude Code の書き込みや外部送信の道具）を最優先で止められるようにする。
印は再起動しても残り、AI 側からは付けられるが外せない（外すのは Mark が端末で行う）。

## 印と道具（共通の約束）
- 印: `data/.luminous_stop`（git 管理外）。あれば「全体停止中」。1 行目に日時と理由（任意）を書く
- `bash tools/luminous_stop.sh on [理由]` — 印を作る（誰が実行してもよい。止める方向は常に安全）。Codex の実行中なら、ロックの持ち主（`data/codex_runs/.lock/owner` の PID）に TERM を送る（ラッパーが中断として片付ける＝終了 130）
- `bash tools/luminous_stop.sh status` — 停止中かと理由を表示（読むだけ）
- `bash tools/luminous_stop.sh off` — 印を消す。**端末からの実行に限る**（標準入力が端末でなければ断る。`tools/set_env_key.sh` と同じ考え）。「解除」と打たせてから消す
- on・off は `logs/stop.log` に 1 行（日時・on/off・理由の先頭 80 字）

## A. Codex に渡す部分

### 触ってよいファイル
<!-- ALLOWED -->
tools/luminous_stop.sh
tools/_codex_common.sh
orch/config.py
orch/decisions.py
tests/test_tools.py
tests/test_decisions.py
tests/test_gemini.py
tests/test_jev.py
<!-- /ALLOWED -->

### 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出し・上記以外のファイル・`.claude/`・`ROUTINE.md`・`AGENTS.md` の変更

### 変更
1. `tools/luminous_stop.sh` を新設（上の「印と道具」のとおり。bash 3.2 で動くこと。`set -u`。パスは `$PROJ` 基準）
2. `tools/_codex_common.sh` の `codex_disabled` が、`data/.luminous_stop` があれば真を返す（`codex_impl.sh`・`codex_opinion.sh` は今のまま「停止中」で終了 2 になる）
3. `orch/config.py` に `global_stop() -> bool`（`data_dir()/.luminous_stop` の有無）を足し、`disabled(vendor)` は全体停止中なら真を返す（Gemini・Jev は呼ばれない）
4. `orch/decisions.py` の `ask()` は、全体停止中なら外部AIも `claude -p` も呼ばず、すぐ既定値を返す（`backend="rules"`、理由「全体停止中」）。影ログには理由を残す

### テスト（陽性・陰性・境界値。外部 API はモック）
- `luminous_stop.sh`: on で印ができる・status が停止中と理由を出す・標準入力が端末でない off は断って印が残る・ロックの持ち主に TERM が送られる（偽の PID のプロセスで確かめる）・印が無いときの status
- `config.disabled`: 印があれば全ベンダーで真、無ければ従来どおり
- `decisions.ask`: 印があれば `jev.call` も `_from_anthropic` も呼ばれず既定値、理由に「全体停止中」
- `codex_disabled`: 印があれば真（既存の偽の codex のテストに 1 本足す）

### 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点

## B. 司令塔が行う部分（保護ファイル。Mark の確認つき。A の審査が APPROVE の後）

1. `.claude/hooks/stop-guard.sh` を新設し、`PreToolUse` にすべての道具（matcher `*`）で登録する。印があれば、読むだけの道具（Read・Grep・Glob）と `bash tools/luminous_stop.sh status` 以外を止める（終了 2、理由を表示）。サブエージェントの起動・Web の取得・MCP の送信系も止まる
2. `stop-gate.sh`: 全体停止中は終了を止めない（止まっているのに「digest を書け」で閉じ込めない）
3. `restore-charter.sh`（SessionStart）: 全体停止中なら最初に大きく表示する（理由・解除の方法）
4. `session-end.sh`: 全体停止中は docx の再生成を見送る
5. `scripts/test-hooks.sh` に陽性・陰性のテストを足す。`ROUTINE.md` §5 の hooks の表に 1 行足す
6. 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）

## C. 文書だけの部分（司令塔。コードなし）
- 失敗の種類で対応を分ける表（回答 §2 の D）を、基本構成の提案 §2.3 に入れる（認証切れ・上限・通信は「上位モデルへ上げる」理由にしない）
- 評価の記録に版・日付・不確実性を付ける型（回答 §2 の E）を `docs/eval-design.md` に入れる

## 残る点（Phase 2 で）
- 実行中の Claude Code の道具の呼び出しは、次の呼び出しから止まる（今の 1 回は止められない）
- 止めた後に遅れて返ってきた外部AIの答えを捨てる仕組み（判断層は開始時にだけ見る）
- 予算の予約と精算（回答 §2 の B）、外部操作の状態（同 C）、権限の記録（同 F）
