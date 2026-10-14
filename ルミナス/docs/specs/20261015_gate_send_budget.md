# 20261015_gate_send_budget

## 目的（1〜3行）
素体の安全の核（P4）。外部 AI を呼ぶ**前に**、送信区分・宛先・予算を名簿（`config/roster.json`）に照らして検査し、通らなければ呼ばない「ゲート」を、ネットワークを使わない純粋な Python のモジュールとして作る。既定は拒否（fail-closed）、ただし許可された入力は通す。
方針（Mark 2026-10-15）: 最初は小さく、柔軟性と発展性を重視。→ 宛先・価格・区分の上限はコードに書かず、すべて名簿から読む。共通の抽象化は作らない。既存の `orch/gemini.py`・`orch/jev.py` への組み込みは**この指示書ではしない**（次の指示書）。

## 触ってよいファイル
<!-- ALLOWED -->
orch/gate.py
tests/test_gate.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない（テストは一時ディレクトリに作った名簿を使う）

## 背景
- 設計: `docs/baseline/00-sotai-map.md`（§3 送信区分と合成規則・未知の接続）、`docs/baseline/roster-schema.md`（名簿の項目と状態）、最終提案 `docs/proposals/20261015-prototype-baseline.md` §6 P4 と完成条件 1。
- 壁打ちでの合意: 上限は停止条件であって実行許可ではない／費用不明をゼロとしない／故障注入のすべてで呼び出し前に停止し、かつ許可された入力は通る／試験の合格は試験した範囲だけの保証。
- Python 3.9 で動くこと（`/usr/bin/python3` が 3.9）。標準ライブラリだけ。

## 変更
1. `orch/gate.py` を新設。公開する関数とデータ:
   - `class GateDenied(Exception)`（`reason` 属性に短い理由。本文や鍵を入れない）
   - `load_roster(path) -> dict`: JSON を読み、`entries` の各行に必須項目（`id, role, provider, model, version_kind, state, max_data_class, hosts, price, evidence, rollback_to, review_by`）があるか確かめる。壊れていれば `GateDenied`。
   - `classify(parts) -> str`: `parts` は `[(text, label)]`。label は `"A"`・`"B"`・`"C"` か `None`。**全体の区分は最も重いもの（A<B<C）**。label が `None` や想定外の値なら C。text に私的語句（`/Users/`・`_非公開`・`orch.config` の鍵の形の正規表現 `_GENERIC_SECRET` 相当。import できない環境でも動くよう、同等の正規表現をこのモジュールに持ってよい）が含まれれば C。
   - `check_destination(roster, entry_id, hops) -> dict`: 行が存在し、`state` が `adopted` か `trial`、`hosts` が空でないこと。`hops` は URL の列（最初の宛先＋リダイレクト先）。**すべての hop のホスト名**が行の `hosts` に完全一致（大文字小文字は無視、ポート・ユーザー情報つき・IP 直書きは拒否）。`https` 以外は拒否。通れば行を返す。
   - `check_send(roster, entry_id, parts, max_chars) -> str`: `classify` の結果が行の `max_data_class` 以下で、C でなく、文字数の合計が `max_chars` 以下であること。通れば区分を返す。
   - `class Budget`: `__init__(self, ledger_path, caps)`。`caps` は `{"usd_per_day", "calls_per_day", "tokens_per_day", "seconds_per_task"}` の一部。`reserve(entry, calls, max_in_tokens, max_out_tokens, task_id) -> dict`: 行の `price` が null、または input/output が数値でない・負・無限大なら `GateDenied`（**費用不明は予約できない**）。見積り＝`calls ×（max_in × input + max_out × output）/ 1e6`。台帳（JSON 行の追記）の当日分の予約と精算を合算し、どの上限を超えても `GateDenied`。同じ `task_id` の未精算の予約があれば `GateDenied`（**再開時の二重実行の防止**）。`settle(task_id, actual_usd, actual_tokens, epoch)`: 予約を精算し、実額が見積りの 1.5 倍以上なら警告フラグ、2 倍以上なら `stopped=True` を記録して以後その task_id を拒否。`stop(epoch)` を呼んだあとの古い epoch の `settle` は**適用せず**「遅延応答」として記録だけする（**停止後の遅延応答を適用しない**）。台帳の壊れた行・数値でない値は 0 ではなく**その日の予約を拒否**する側に倒す。
   - `gate(roster_path, entry_id, hops, parts, max_chars, budget, calls, max_in_tokens, max_out_tokens, task_id, detector=None) -> dict`: 上の検査を順に行い、`detector` が与えられればそれも呼ぶ（`detector(text)->bool` が True なら拒否。**例外を投げたら拒否**）。どこかで失敗すれば `GateDenied`。すべて通れば予約の記録を返す。予約は最後に行う（途中で拒否されたら予約しない）。
2. どの関数もネットワークを使わない。ファイルの書き込みは `Budget` の台帳だけ。

## テスト（`tests/test_gate.py`。一時ディレクトリの名簿と台帳だけを使う）
- 正常系: 採用の行・許可ホスト・区分 A・上限内 → 通り、台帳に予約が 1 行増える。
- 故障注入（すべて**呼び出し前に**拒否され、台帳に予約が増えない）: 未知のホスト／リダイレクトの途中か最後が許可外／`http://`／IP 直書き／ポートつき／名簿に無い id／状態が `candidate`・`hold`・`stopped`／区分 B を A 上限の行へ／label なしの部分（C 扱い）／`/Users/` を含む本文／鍵の形を含む本文／文字数超過／price が null・負・NaN・文字列／上限超過（金額・回数・トークン）／台帳の壊れた行／同じ task_id の二重予約／detector が True／detector が例外。
- 遅延応答: `stop()` の後の古い epoch の `settle` が適用されない。2 倍超過で以後の予約が拒否される。1.5 倍で警告。
- 名簿の読み込み: 必須項目の欠け・JSON の破損で `GateDenied`。
- 境界値: 文字数・金額がちょうど上限のときは通る、1 を超えると拒否。

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
