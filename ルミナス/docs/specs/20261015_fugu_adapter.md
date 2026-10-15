# 20261015_fugu_adapter

## 目的（1〜3行）
Sakana の API（Fugu）を、6 点セット（固定コマンド・上限・記録・点検・停止スイッチ・フォールバック）とゲート（`orch/gate.py`）を通して呼べる最小の呼び出し口 `orch/fugu.py` を作る。用途は **Mark の指示による実測（応答速度・正答・費用）だけ**。Fugu に自身の構成・振り分け方を尋ねる用途には使わない（規約の「仕組みの解析」に当たるため。ADR `state/decisions/20261015-sakana-fugu.md`）。
方針: 小さく。`orch/gemini.py` の作りに合わせる（共通の抽象化は作らない）。宛先・価格・上限はコードに書かず名簿から読む。

## 触ってよいファイル
<!-- ALLOWED -->
orch/fugu.py
tests/test_fugu.py
tests/conftest.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで。`ORCH_DATA_DIR`・`ORCH_LOG_DIR` を一時ディレクトリに向ける）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない（読むだけ。テストは一時ディレクトリの名簿。名簿の Fugu の行は人が足す）

## 背景
- API（一次情報 console.sakana.ai、2026-10-15 確認）: OpenAI 互換。`POST https://api.sakana.ai/v1/chat/completions`、ヘッダー `Authorization: Bearer <SAKANA_API_KEY>`・`Content-Type: application/json`、本文 `{"model": ..., "messages": [{"role": "user", "content": ...}], "max_completion_tokens": N}`。応答は `choices[0].message.content` と `usage`（`prompt_tokens`・`completion_tokens`。`completion_tokens_details.reasoning_tokens` や、Ultra では `token_details` に調整用トークンが入ることがある）。
- 料金: Fugu Max（`fugu-max`）は入力 $2・出力 $6／100 万トークン。Fugu Max は内部の Web 道具を 1 回 $0.007 で使うことがあり、応答からは回数が分からない場合がある。
- 名簿に足す予定の行（人が足す。テストではこれと同じ形の行を一時ディレクトリの名簿に作る）: id `sakana-fugu-max`、role `外部オーケストレーターの実測`、provider `sakana`、model `fugu-max`、state `trial`、max_data_class `A`、hosts `["api.sakana.ai"]`、price `{input: 2.0, output: 6.0, unit: usd_per_mtok}`、caps `{usd_per_day: 0.25}`。
- 鍵の名前 `SAKANA_API_KEY` は `orch/config.py` の伏せ字の対象に登録済み。
- 失敗しても本流を止めない（不変条件 4）。Python 3.9 で動くこと。

## 変更
1. **`orch/fugu.py`**（`orch/gemini.py` と同じ骨組み）:
   - `ROLE = "外部オーケストレーターの実測"`。名簿の行は `entry_id`（既定 `sakana-fugu-max`）で選び、`provider == "sakana"` かつ state が adopted/trial でなければ `GateDenied("roster_selection")`。`model` を渡して行と違えば `GateDenied("model_mismatch")`。
   - `generate(prompt, *, entry_id="sakana-fugu-max", model=None, max_output_tokens=2048, timeout=180, purpose="", data_class=None) -> Result`（`Result` は rc・reason・text・usage・**sec（応答までの秒、小数）**を持つ）。順番は gemini と同じ: 全体停止→`GlobalHalt`／`config.disabled("fugu")`→rc=2「停止中」／鍵なし→rc=2「鍵なし」／当日の実額＋今回の見込み額が `ORCH_FUGU_DAILY_USD_CAP`（既定 0.25）を超える→rc=2「上限到達」／requests 無し→rc=2。見込み額は「入力の UTF-8 バイト数×入力単価＋max_output_tokens×出力単価」に、Web 道具の分として 0.007×3 を足した額。
   - ゲート: `gate.gate(roster_path, entry["id"], [url], [(wire, data_class)], len(wire), budget, 1, len(wire.encode("utf-8")), max_output_tokens, task)`。`data_class` 未指定・C は拒否される（ゲートの既定どおり）。リダイレクトを追わない（`allow_redirects=False`）。応答全体の待ち時間を別スレッドで打ち切る（gemini の `_post_with_timeout` と同じ）。終わったら必ず `budget.settle`（失敗時は `stop`）。再試行はしない（1 回だけ）。
   - 費用: `usage.prompt_tokens×入力単価＋(usage.completion_tokens＋調整用トークン)×出力単価`。usage が読めない応答・通信例外・5xx は控えめに 0.05 を計上。401/403→rc=2「未認証」・429→rc=2「上限到達(429)」・5xx→rc=2「API障害」・その他の非 200→rc=2「API障害(HTTP n)」・本文が空→rc=3「空応答」・`finish_reason == "content_filter"`→rc=3「安全フィルタ」・解析失敗→rc=3。
   - 記録: `logs/fugu.log` と `usage.record("fugu", ...)` に 1 回 1 行（model・rc・sec・chars・in・out・usd・reason）。本文・生のエラー・鍵は書かない（`config.redact` を通す）。記録の失敗で本流を止めない。
   - `check_status(net=True)`: 全体停止を先に表示。名簿の行・鍵の有無・当日の支出と上限を 1 行。`net=True` なら `GET https://api.sakana.ai/v1/models`（本文は送らない・ゲートを data_class "A" で通す・allow_redirects=False）で認証を確かめる。
   - CLI: `python3 -m orch.fugu check [--quiet] [--no-net]`／`python3 -m orch.fugu gen --data-class A [--entry ID] [--purpose 用途] [--max-output N] [--timeout S] < prompt.txt`。成功なら本文を標準出力へ、標準エラーに `fugu: sec=… usd=…` を 1 行。終了コード = rc（全体停止は `config.HALT_EXIT_CODE`）。
   - モジュールの説明文に「Fugu に自身の構成・振り分け方を尋ねる用途に使わない（規約）」と書く。
2. **`tests/conftest.py`**: FLAG_VARS に `ORCH_FUGU`・`ORCH_FUGU_DAILY_USD_CAP`・`SAKANA_API_KEY` を足す（テストが本物の環境変数を拾わないように）。

## テスト（`tests/test_fugu.py`。requests はモック、名簿は一時ディレクトリ）
- 正常: 本文・費用（prompt 1000・completion 500 → $0.005）・sec が返り、台帳と log に 1 行、本文は記録に無い
- 送信区分の未指定・C は通信せずに拒否／宛先が名簿の hosts 以外なら拒否
- 停止スイッチ（`ORCH_FUGU=0`・`data/.fugu_disabled`）・全体停止（GlobalHalt）・鍵なし・上限到達（当日の実額＋見込み額で判定）はどれも通信しない
- 401・429・500・content_filter・空本文・JSON でない応答・タイムアウト・リダイレクト（302 は成功にしない）
- 名簿の行が無い／provider が違う／state が hold → 通信しない／model の不一致は拒否
- `check` の CLI と `gen` の CLI（`--data-class` の受け渡し）
- 既存の試験がすべて通ること

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
