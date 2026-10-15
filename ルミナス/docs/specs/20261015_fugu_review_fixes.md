# 20261015_fugu_review_fixes

## 目的（1〜3行）
`orch/fugu.py`（指示書 `docs/specs/20261015_fugu_adapter.md`）の Opus 審査 REJECT の指摘を直す。とくに、使用量が読めないときの計上が固定の $0.05 で実額より少なくなりうる点と、調整用トークンの名前が推測だった点。

## 触ってよいファイル
<!-- ALLOWED -->
orch/fugu.py
tests/test_fugu.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない

## 背景（一次情報 console.sakana.ai/models、2026-10-15 確認）
- 調整用（orchestration）トークンは入力・出力とは**別に**数えられ、通常の入力・出力と同じ単価で請求される。応答の `usage` の例（Responses 形式）: `input_tokens`・`output_tokens`・`total_tokens`、`input_tokens_details` に `cached_tokens`・`orchestration_input_tokens`・`orchestration_input_cached_tokens`、`output_tokens_details` に `orchestration_output_tokens`。Chat Completions 形式（`prompt_tokens`・`completion_tokens`）の `prompt_tokens_details`・`completion_tokens_details` に同じ名前が入るかは未確認。
- Web 道具（1 回 $0.007）の回数は `usage` に無い。

## 変更
1. **（中 2）控えめな計上**: 使用量が読めない応答・解析失敗・タイムアウト・通信例外・5xx の計上を、固定の `UNKNOWN_USAGE_USD` ではなく `max(UNKNOWN_USAGE_USD, 送る前の見込み額)` にする（見込み額は `generate` の上限判定で使う額と同じもの。`usage` の台帳とゲートの `settle` の両方に同じ額）。
2. **（中 3）調整用トークン**: `_counts` を次のとおりにする。
   - 入力 = `prompt_tokens`（無ければ `input_tokens`）。出力 = `completion_tokens`（無ければ `output_tokens`）。どちらも 0 以上の整数でなければ「使用量不明」。
   - 入力側の詳細（`prompt_tokens_details` または `input_tokens_details`）の `orchestration_input_tokens` と `orchestration_input_cached_tokens` を入力に加える（キャッシュ分も控えめに通常の入力単価で数える）。出力側の詳細（`completion_tokens_details` または `output_tokens_details`）の `orchestration_output_tokens` を出力に加える。`reasoning_tokens`・`cached_tokens` は内数なので加えない。
   - `token_details`（説明文に出てくる名前）も辞書なら同じ規則で読む。
   - 詳細の中に**名前に `orchestration` を含む知らない項目**があれば「使用量不明」（1. の控えめな額）にする。それ以外の知らない項目は無視する。値が負・整数でないときも「使用量不明」。
   - 根拠（上の一次情報）を説明文に 1〜2 行で書く。
3. **（軽 4）本流を止めない**: `generate` の入口で `prompt` が文字列でなければ rc=2「入力不正」を返す（通信しない）。`daily_usd()` が読めない（OSError など）ときは「上限到達」扱いにする（fail-closed）。
4. **（軽 6）** モジュールの説明文に「記録する実額に Web 道具の料金（1 回 $0.007）は含まれない（応答に回数が無いため）。見込み額には 3 回分を含める」と書く。
5. **（軽 7）試験の追加**: ゲートの直前の全体停止／区分 B の拒否（名簿の上限 A を超える）／`--entry` の受け渡し／`content: null`／`check` が失敗したときの終了コード（`--quiet` ありは 0、なしは 2）／調整用トークンの加算（Chat 形式と Responses 形式の両方、キャッシュ分を含む）／`orchestration` を含む知らない項目→控えめな額／使用量が無い応答とタイムアウトで計上が見込み額以上／文字列でない prompt／`daily_usd` の OSError。

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
