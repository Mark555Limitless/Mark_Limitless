# 20261016_cost_unknown_model_id

## 目的（1〜3行）
この Codex スレッドとの第 4 往復（`docs/brainstorm/20261014-luna-wallbounce.md`）の合意を実装する。(1) 費用が分からない応答・通信例外の計上を、Gemini でも Fugu と同じ「見込み額以上」にする。(2) 応答に含まれる実行時のモデル ID を記録し、名簿の `model` と食い違えば版の未知化として拒否する。(3) 同じ名簿の行で実費不明が 1 日 2 回以上なら、照合が済むまでその行を止める。
**Codex の共有枠は Fable5・脳でんちを優先**。枠が無ければ待つ。

## 触ってよいファイル
<!-- ALLOWED -->
orch/gemini.py
orch/fugu.py
orch/usage.py
tests/test_gemini.py
tests/test_fugu.py
tests/test_usage.py
<!-- /ALLOWED -->

## 禁止
- git の操作（commit・init を含む）・`.git` の作成や変更・.env／data／logs の読み書き（テストは一時ディレクトリで）・実際の外部 API 呼び出しやネットワーク通信（requests はモック）・上記以外のファイル・実行権限の付与・リンクや FIFO の作成
- `config/roster.json` を変更しない

## 背景
- Fugu（`orch/fugu.py`）は既に「使用量不明＝ `max(UNKNOWN_USAGE_USD, 送る前の見込み額)`」を計上している。Gemini（`orch/gemini.py`）はまだ一律 `UNKNOWN_USAGE_USD`（$0.05）で、長い入力のタイムアウトで実費より少なく記録されうる。
- 実行時のモデル ID: Gemini の応答は `modelVersion`（例 `gemini-3.8-flash-001`）、Fugu（OpenAI 互換）は `model` を返す。名簿の `model` は alias（`gemini-3.8-flash`・`fugu-max`）なので、**前方一致**（応答の値が名簿の値で始まる、または等しい）で一致とみなす。
- `usage.record` は 1 回 1 行（`data/usage.jsonl`）。`status` は ok／skip／error。

## 変更
1. **Gemini の計上**: `generate` の見込み額（入力の UTF-8 バイト数×入力単価＋`maxOutputTokens`×出力単価）を呼び出し前に計算し、使用量が読めない応答・解析失敗・タイムアウト・通信例外・5xx の計上を `max(UNKNOWN_USAGE_USD, 見込み額)` にする（`usage` の台帳とゲートの `settle` の両方）。上限の判定も「当日の実額＋見込み額 > daily_cap」にする（gate_followups の 7 と同じ。先にこちらで実装してよい）。
2. **実行時のモデル ID の記録**: Gemini・Fugu とも、応答の `modelVersion`／`model` を `Result.usage` に残し、`_log` の 1 行に `served=<値>` を足す（無ければ `served=-`）。`usage.record` に任意の引数 `served_model: str = ""` を足して台帳にも書く（無ければ省く。既存の行の形は変えない）。
3. **版の未知化**: 応答の実行時モデル ID が名簿の `model` と前方一致しなければ、本文を使わず rc=2 `served_model_mismatch` で返す（費用は実額で計上。再試行しない）。空や無い場合は一致扱い（記録は `served=-`）。
4. **実費不明の回数での停止**: `orch/usage.py` に `today_unknown(vendor) -> int`（当日の `status == "error"` かつ `unknown=True` の行の数）を足し、`usage.record` に任意の引数 `unknown: bool = False` を足す。Gemini・Fugu の `_log` は、計上が「見込み額以上の控えめな額」だったとき `unknown=True` で記録する。`generate` の入口で `today_unknown(vendor) >= 2` なら rc=2「要照合」で止める（通信しない）。`check_status` にも「要照合（実費不明 n 回）」を表示する。解除は Mark が照合した後、日付が変わるか `ORCH_<VENDOR>_RECONCILED=1` を付ける（環境変数があれば止めない）。
5. 既存の試験が通ること。Python 3.9 互換。

## テスト
- Gemini: 長い入力（見込み額 > $0.05）がタイムアウト・5xx・使用量なし・解析失敗のとき、台帳と settle の額が見込み額以上／短い入力なら $0.05／上限の判定が「実額＋見込み額」
- served の記録: 一致（前方一致を含む）で本文が返る／不一致で rc=2・本文なし・費用は実額／無いときは `served=-`
- 要照合: 当日 unknown 2 回で通信せず rc=2、`ORCH_GEMINI_RECONCILED=1`（Fugu も）で通る、check_status の表示
- `usage.today_unknown` の数え方（他のベンダーの行・前日の行を数えない）
- 新しい環境変数は tests/conftest.py の FLAG_VARS に無いので、試験の中で monkeypatch で消す・設定する（conftest は ALLOWED 外。未解決に「FLAG_VARS に ORCH_GEMINI_RECONCILED・ORCH_FUGU_RECONCILED を足す」と書く）

## 完了条件
- `.venv/bin/python -m pytest tests -q` が全件通る（件数を報告）／`bash scripts/test-hooks.sh` が全件通る
- `git diff --stat` が ALLOWED のファイルだけ
- 最後に変更ファイル・要点3行・未解決の点
