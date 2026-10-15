# 20261015_gate_followups

## 目的（1〜3行）
ゲート接続（コミット 164721e）の審査で後回しにした指摘を直す。とくに、名簿の役割を日本語の名前の完全一致で選んでいる点（柔軟性の方針に合わない）と、Codex の実行中にゲートの台帳へ追記があると範囲検査の違反になる点。
**Codex の利用枠が戻ってから実行する**（2026-10-15 に上限。共有枠なので Fable5・脳でんちの作業を優先する）。

## 触ってよいファイル
<!-- ALLOWED -->
orch/gemini.py
orch/jev.py
orch/roster.py
tools/scope_check.py
tests/conftest.py
tests/test_gemini.py
tests/test_jev.py
tests/test_decisions.py
tests/test_roster.py
tests/test_tools.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない（名簿の変更は人が行う。必要な追記は「未解決」に書く）

## 変更
1. **（中 5）役割を機械用のキーで選ぶ**: 名簿の行に任意の `role_key`（英小文字とハイフン。例 `drafter`・`decision-signal`）を足せるようにし、`orch/roster.py` の `active()` は `role_key` があればそれで、無ければ従来の `role` で照合する。`orch/gemini.py` は `drafter`、`orch/jev.py` は `decision-signal` で探す（名簿に `role_key` が無い間は従来の日本語名で動く＝後方互換）。名簿への `role_key` の追記は人が行う（完了報告の「未解決」に、足すべき 2 行を書く）。
2. **（中 3）`tools/scope_check.py`**: ゲートの台帳 `data/gate_ledger.jsonl` を、実行中に追記してよい記録（APPEND_ONLY）に加える。追記された行は JSON オブジェクトで、数値（`usd`・`actual_usd`・トークン）は 0 以上の有限の数であること（既存の台帳と同じ基準）。
3. **（軽 b）** `check_status` の全体停止の判定の試験（名簿を壊した状態と全体停止を同時に作り「全体停止中」と出る）。到達しなくなった 2 つ目の判定を消す。
4. **（軽 7）** 点検（check_status）が当日の上限を使い切って拒否されたとき、表示を「上限到達（疎通は未確認）」にし、model と支出を表示から消さない。
5. **（軽 a）** リダイレクトの試験は、正しい answers を含む本文でも失敗になることを確かめる形にする（gemini・jev とも）。
6. **（軽 c・d）** 既存の試験が本物の `config/roster.json` を読まないよう、`adapter_roster` を `tests/conftest.py` へ移し、gemini・jev・decisions の試験で使う（自動で効く fixture にしてよい）。

7. **（Gemini の行指定の審査・中）** Gemini 全体の 1 日の上限（`daily_cap`）を、呼ぶ前に「当日の実額＋今回の見込み額」で判定する（今は当日の実額だけで判定し、上限の直前から 1 回分〔Argon なら約 $0.082〕超えうる。名簿の行ごとの上限は行ごとに数えるので、Flash と Argon の合計は daily_cap だけが抑えている）。
8. **（同・中）** `check_status` にも、名簿の行と使うモデル名の一致確認を入れる（不一致なら点検でも拒否と表示）。
9. **（同・低）** 試験の追加: 存在しない id／state=adopted が通る／ORCH_GEMINI_MODEL が名簿と違うと拒否・同じなら通る／CLI の `--entry` が渡る。

## テスト
- role_key で選べる／role_key が無ければ日本語名で選べる／role_key と名簿が食い違えば拒否（通信しない）。
- scope_check: 実行中の gate_ledger への追記（正しい JSON 行）は違反にならない、壊れた行・負の数・既存部分の書き換えは違反。
- 上の 3〜6 の各試験。既存の試験がすべて通ること。

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点（名簿に足すべき role_key の 2 行を含む）
