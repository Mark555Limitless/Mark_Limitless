# 20261010_openai_api（予備。未実装）

> Mark の決定（2026-10-10）: ChatGPT（Codex）とは **② Mac 経由を優先**し、**問題があるときだけ ① OpenAI の API を併用**する。
> この指示書は ① の予備。② で問題（Mac が止まっている・Codex の利用枠の上限・Mac のセッションが応えない など）が続いたら、Mark の確認の後に実装する。
> 実装の前に、OpenAI の API リファレンスで要求と応答の形を確かめる（2026-10-10 には取得できなかった）。

## 目的（1〜3行）
クラウドの司令塔から OpenAI の API を直接呼び、GPT（Codex と同じ系統のモデル）に意見・下書きを頼めるようにする。Gemini（`orch/gemini.py`）と同じ 6 点セット（固定コマンド・上限・記録・点検・停止スイッチ・フォールバック）で包む。

## 前提（Mark が行う）
- OpenAI の API の鍵を作る（platform.openai.com に Mark 本人がログイン）。**ChatGPT の月額とは別の、使った分だけの請求**。コンソールで月の支払いの上限も設定しておく
- 鍵はチャットに貼らない。クラウドの環境の設定（セッションの題の横の環境のメニュー → Edit）の **Network secrets** に、送り先 `api.openai.com` で登録する（その欄が無ければ環境変数 `OPENAI_API_KEY`）。登録は次の新しいセッションから効く
- Mac で使う場合は `bash tools/set_env_key.sh OPENAI_API_KEY`

## 料金（2026-10-10、公式の料金ページ developers.openai.com/api/docs/pricing、100 万トークンあたり・Standard・短い文脈）①

| モデル | 入力 | 出力 | 備考 |
|---|---|---|---|
| gpt-6-astra | $10.00 | $50.00 | Codex の既定（`~/.codex/config.toml`）と同じ系統。長い文脈は入力 $20・出力 $75 |
| gpt-6.1-sol | $2.00 | $10.00 | 長い文脈は $4・$15 |
| gpt-6-luna | $0.10 | $0.50 | 長い文脈は $0.20・$0.75 |

- バッチは約半額。「短い文脈」と「長い文脈」の境目は料金ページから読み取れなかった（実装の前に確かめる）
- 例: ブレーンストーミング 1 往復（入力 1 万・出力 3 千トークン）を gpt-6-astra で約 $0.25、gpt-6.1-sol で約 $0.05

## 触ってよいファイル（実装するとき）
<!-- ALLOWED -->
orch/openai_api.py
orch/health.py
tests/test_openai_api.py
.env.example
<!-- /ALLOWED -->

## 変更（実装するとき）
1. `orch/openai_api.py`: `orch/gemini.py` と同じ作り。固定コマンド `python3 -m orch.openai_api check|ask <ファイル>`。送る文章は「データであって指示ではない」と明記（`orch.config.as_data`）。公開可の内容だけ
2. 上限: 呼ぶ前に当日・当月の金額を台帳（`data/usage.jsonl`、vendor=openai）で数える。案: `ORCH_OPENAI_DAILY_USD_CAP=1.0`・`ORCH_OPENAI_MONTHLY_USD_CAP=5.0`（**支出なので Mark が確認して決める**）。単価は `ORCH_OPENAI_PRICE_IN`・`ORCH_OPENAI_PRICE_OUT`（未設定なら呼ばない）
3. 鍵: 環境変数 `OPENAI_API_KEY` があれば使う。無ければ Network secrets（送り出しのときに鍵が付けられる）を前提に呼ぶ。鍵の値は記録に書かない
4. モデルは `OPENAI_MODEL`（既定は空。`check` で使えるモデルの一覧を出し、Mark か司令塔が決める）
5. 停止スイッチ `ORCH_OPENAI=0`／`data/.openai_disabled`、全体停止（`docs/specs/20261008_global_halt.md`）にも従う
6. 失敗したら呼び出し側は Claude に戻す（意見役なので本流は止めない）

## 完了条件
- テスト（モック）が全件通る・Opus のコード審査で APPROVE
- 鍵を登録した新しいセッションで `check` が通る（実測の費用を digest に残す）
