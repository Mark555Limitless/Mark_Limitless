# 20261015_gate_wiring

## 目的（1〜3行）
P4 ゲート（`orch/gate.py`）を、実際に外部 AI を呼ぶ 2 つのアダプタ（`orch/gemini.py`・`orch/jev.py`）の**呼び出しの直前**につなぐ。あわせて、名簿で役割の担当を切り替えて元に戻す小さな仕組み（`orch/roster.py`）と、その模擬試験（素体の完成条件⑤）を作り、前回の審査の軽 5 件を直す。
方針（Mark 2026-10-15）: 小さく、柔軟性と発展性を重視。宛先・価格・上限はコードに書かず名簿から読む。共通の抽象化は作らない。

## 触ってよいファイル
<!-- ALLOWED -->
orch/gate.py
orch/gemini.py
orch/jev.py
orch/decisions.py
orch/roster.py
tests/test_gate.py
tests/test_gemini.py
tests/test_jev.py
tests/test_decisions.py
tests/test_roster.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで。`ORCH_DATA_DIR` を一時ディレクトリに向ける）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない（読むだけ。テストは一時ディレクトリの名簿）

## 背景
- 指示書 `docs/specs/20261015_gate_send_budget.md`・`docs/specs/20261015_gate_review_fixes.md`。設計 `docs/baseline/00-sotai-map.md`・`docs/baseline/roster-schema.md`。名簿の実物 `config/roster.json`（Mark 承認済み）の行 `gemini-drafter`（hosts `generativelanguage.googleapis.com`・1 日 $0.25）と `jev-signal`（hosts `api.typesafe.ai`・1 日 60 回・月 $1）。
- 失敗しても本流を止めない（不変条件 4）: ゲートに拒否されたら、各アダプタの既存の「基盤の失敗」の経路（Gemini は rc=2 で Claude に戻す、Jev は失敗として判断層が Claude CLI→既定値へ）に乗せる。拒否の理由（`GateDenied.reason`）だけを既存のログ・台帳に残し、本文は書かない。
- Python 3.9 で動くこと。

## 変更
1. **送信区分を呼び出し側が明示する**: `gemini.generate(...)` と `jev.call(...)` に引数 `data_class`（"A"・"B"・"C"・None）を足す。**既定は None で、None はゲートが C とみなして拒否する**（区分の付いていない送信はしない）。`decisions.ask` から `jev.call` へは "A" を渡す（判断層に渡す内容は公開可に限るという既存の約束。`docs/support-ai.md` §5・§7）。`python3 -m orch.gemini gen` には `--data-class` を足し、既定は指定なし（＝拒否）。
2. **呼び出しの直前にゲート**: 両アダプタは、ネットワークに出る直前に `gate.gate(...)` を呼ぶ。名簿のパスは `config.ROOT / "config" / "roster.json"`（環境変数 `ORCH_ROSTER` で上書き可。試験用）。台帳は `config.data_dir() / "gate_ledger.jsonl"`。hops は実際に送る URL（1 つ）。max_chars と最大トークンは各アダプタの既存の値から決める。拒否されたら呼ばない。
3. **リダイレクトを追わない**: 実際の `requests.post` / `requests.get` は `allow_redirects=False` にし、3xx は基盤の失敗として扱う（ゲートが検査した宛先以外へ行かない）。
4. **精算**: 応答の後に `Budget.settle(...)` で実額（使用量が読めなければ既存の控えめな計上と同じ額）を精算する。例外・中断でも精算か停止の記録を残す。既存の `usage.jsonl` への記録と上限の判定（`daily_cap` など）は**そのまま残す**（二重の守り）。
5. **`orch/roster.py`（新設・小さく）**: `active(roster, role) -> entry`（その役割で状態が adopted の行。無ければ trial、どちらも無ければ例外）、`plan_switch(roster, role, new_id) -> dict`（新しい名簿の辞書を返すだけ。旧行を `retired` にせず `hold` に、新行を `adopted` に。新行は同じ役割で、状態が trial であること）、`plan_rollback(roster, role) -> dict`（直前に hold にした行へ戻す。戻し先が無ければ例外）。**ファイルは書かない**（名簿の書き換えは人が Edit で行う。名簿は確認つきのファイル）。
6. **前回の審査の軽 5 件**（`orch/gate.py`）: (1) 旧形式の台帳（entry_id の無い行）は理由 `ledger_entry` で拒否し、docstring に「この変更より前のゲートの台帳は作り直す」と書く (2) `release` は同じ (entry_id, task_id) の組だけを消す (3) `Budget.reserve` は直接呼ばれても名簿の caps を通らない形にしない＝内部用の `_reserve` にして `gate()` からだけ呼ぶ（公開の `reserve` は残すなら名簿の行の caps を必ず合成する）(4) stop の後に精算が来ない予約を人が閉じる手順（`stop()`→`settle(task, None, None, epoch)`）を docstring に書く (5) detector が True を返したときの拒否（`detector_denied`）を、detector の例外（`detector_error`）と区別する。docstring の不自然な改行も直す。

## テスト（外部 API はモック。一時ディレクトリの名簿・台帳だけ）
- Gemini・Jev: data_class が None・"C"・名簿の上限を超える区分で**ネットワーク（モック）が呼ばれない**こと、許可された呼び出しでは呼ばれて台帳に予約と精算が残ること、ゲートの拒否が既存の失敗経路（Gemini rc=2・Jev は失敗→判断層のフォールバック）に乗ること、3xx が失敗になること、名簿の 1 日の上限（$0.25・60 回）を超える呼び出しがゲートで止まること、`allow_redirects=False` で呼んでいること。
- decisions: `jev.call` に "A" が渡ること、ゲートの拒否で Claude CLI のフォールバック（モック）に進むこと。
- roster（完成条件⑤）: 模擬の 2 行（同じ役割、A＝adopted・B＝trial）で、`plan_switch` 後に `active` が B を返し、模擬アダプタの呼び出しが B に行くこと、`plan_rollback` 後に A に戻ること。役割違い・状態違い・戻し先なしで例外。名簿のファイルが書き換わらないこと。
- gate の軽 5 件の各回帰試験。既存の試験はすべて通ること。

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
