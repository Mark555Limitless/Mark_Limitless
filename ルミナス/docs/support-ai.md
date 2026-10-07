# サポートAI（Codex・Gemini・Jev）— 常に使える仕組み v0.2

> 出典: Fable5 AI NEWS Select の司令塔が書いた「ルミナス分譲指示書 — Codex・Gemini・Jev を常に使える仕組み」（2026-10-08）。
> 原本はローカルの絶対パスを含むため、この公開フォルダには入れず、Mac の非公開フォルダ（`ルミナス_非公開/`）で保管する。本書はその要約と、ルミナスでの実装の対応表。
> 原本の bot（AI NEWS Select）のファイルはクラウド環境から読めないため、部品はコピーではなく指示書の仕様から再実装した。Mac で原本と見比べて差を詰める。

## 1. 三者の役割と呼び方

| 外部AI | ルミナスでの役目 | 固定コマンド | 費用の出どころ |
|---|---|---|---|
| **Codex**（GPT-6 Astra） | コードの実装。読み取り専用の「第3の意見」 | `bash tools/codex_impl.sh docs/specs/<名前>.md high` ／ `bash tools/codex_opinion.sh docs/astra-packets/<名前>.md` | ChatGPT サブスクの枠（原本・脳でんちと共有） |
| **Gemini**（3.8 Flash ほか） | 文章の下書き・要約・別の視点 | `python3 -m orch.gemini gen --purpose <用途> < prompt.txt` ／ コードから `orch.gemini.generate()` | 従量課金（1日の上限つき） |
| **Jev**（TypeSafe AI の System One） | 選択肢・段階・確率で答える「構造化された判断」の助言 | コードから `orch.decisions.ask(state, questions)`（Jev → Claude CLI → 既定値） | 従量課金（回数と月額の上限つき） |

- 司令塔と審査は Claude のまま。外部AIの答えは助言であり、最終判断は Claude（[永]）
- 取り消せない操作（公開・送信・削除・支払い）の承認は外部AIに委ねない
- Gemini は API だけを使う。Antigravity（agy）を Claude Code から呼ぶことは Google の規約違反（アカウント停止の対象）なので使わない
- Jev は助言であり、評価セット（`docs/eval-design.md`）で確かめるまでは「止める側」の信号として使う。新しい問いを任せる前に、正解つきの例を100問以上集めてオフラインで比べる

## 2. 共通の骨格（6点セット）— そろってから使う

| | 中身 | ルミナスでの実装 |
|---|---|---|
| ①固定コマンド | 必ずラッパー経由で、毎回同じコマンド | `tools/codex_impl.sh`・`tools/codex_opinion.sh`・`python3 -m orch.gemini`・`python3 -m orch.decisions` |
| ②上限 | 日・月ごとの金額と回数。超えたら呼ばずに理由を返す | `ORCH_GEMINI_DAILY_USD_CAP`（既定 $1/日）、`ORCH_JEV_DAILY_MAX`（60回/日）・`ORCH_JEV_MONTHLY_USD`（$1/月）。Codex は同時 1 本（ロック） |
| ③記録 | 1回1行。本文・鍵・生のエラーは書かない | `data/usage.jsonl`（全ベンダー共通）、`logs/gemini.log`・`logs/jev.log`、`data/decisions_shadow.jsonl`（問いと答え、5MB で打ち切り）、`data/codex_runs/` |
| ④点検 | 鍵・疎通・当日の支出を1行で。セッション開始時に毎回表示 | `python3 -m orch.health`（SessionStart hook が表示。`FABLE5_HEADLESS=1` では出さない） |
| ⑤停止スイッチ | 環境変数とファイルの2通り | `ORCH_CODEX=0`／`data/.codex_disabled`、`ORCH_GEMINI=0`／`data/.gemini_disabled`、`ORCH_JEV=0`／`data/.jev_disabled` |
| ⑥フォールバック | 失敗しても本流は止めない。戻したことを記録する | Gemini は rc=2（基盤の失敗）／3（中身の失敗）で Claude に戻す。判断層は Jev → Claude CLI（Haiku→Sonnet）→ 既定値。審査だけは fail-closed |

集計: `python3 -m orch.usage --days 7`（日別・ベンダー別）。Codex は金額が出ないので回数と所要時間だけ。
この台帳は後で「どの仕事にどのモデルが割に合うか」を決める材料にする（原本の設計参照 §5 A の動的なモデル選択）。

## 3. Codex（実装役・意見役）

- 実装: 指示書（`docs/specs/`、型は `docs/specs/README.md`）→ `tools/codex_impl.sh`（`-s workspace-write`、memories と multi_agent を無効化）→ `tools/scope_check.py` が ALLOWED 外の変更と非公開の印（`/Users/`・`_非公開`）を検出 → `git diff` → テスト → 審査（Agent・model: opus・`docs/review.md`、1行目 APPROVE）→ 司令塔が該当ファイルだけコミット
- 終了コード: 0=成功 / 2=前提の誤り（停止中・実行中・指示書不備・作業ツリーが汚い・本体なし）/ 3=ALLOWED 外・非公開の印・`.env` の変更 / 4=利用枠の上限 / 5=Codex の失敗
- 失敗かつ作業ツリーが無変更のときだけ、`CODEX_FALLBACK_MODEL`（既定 gpt-5.6-sol）で1回やり直す
- 利用枠の上限（「try again at …」）: 指示書を残して待つ。途中の差分があれば再実行せず、司令塔がテストまで仕上げて審査に回す。原本の障害修正を優先する
- 本体の場所: `CODEX_BIN` → ChatGPT アプリ同梱（2026-10-06 以降の場所）→ 古い場所（`CODEX_OLD_BIN`）→ PATH
- 意見役: `-s read-only`、公開可・push 済みのファイルだけを書き出した使い捨てディレクトリで起動、回答は `docs/astra-replies/`

## 4. Gemini（下書き・別の視点）

- 送り先 `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`、鍵はヘッダ `x-goog-api-key`
- `thinkingConfig.thinkingLevel` を付け、モデルに拒まれたら外して1回だけ送り直す。応答全体の待ち時間を別スレッドで打ち切る。`thought: true` の部分は本文に入れない
- 費用: promptTokenCount × 入力単価 ＋（candidatesTokenCount ＋ thoughtsTokenCount）× 出力単価。既定は $0.75／$3.75（100万トークンあたり）。**2027-01 から $1.50／$7.50 に上がる予定**（公式の価格ページで確かめて `.env` を更新）
- 使用量の無い応答・通信例外・5xx は控えめに $0.05 を計上（処理されたか不明でも上限に数える）。401／403／429 は処理前の拒否として計上しない
- 点検: `python3 -m orch.gemini check`（鍵の有無・本文を送らない疎通確認・当日の支出と上限）
- 画像生成は必要になってから（段階5）

## 5. Jev（構造化された判断の助言）

- 送り先 `POST https://api.typesafe.ai/v1/systemone`、`Authorization: Bearer <TYPESAFE_API_KEY>`、本文 `{"state": 文字列, "model": "jev-latest", "questions": {...}}`、応答の `answers.<問いID>`
- 判断層 `orch.decisions`: 問いの型は Choice（選択肢のキー、120 個以下）・Score（0〜n-1）・Noul（0〜1）。問いごとに失敗時の既定値を持つ
- 順番: jev（`JEV_ENABLED=1`・`DECISION_BACKEND=jev`・鍵あり）→ anthropic（`claude -p … --tools ""` を Haiku → Sonnet、JSON だけ）→ rules（既定値）。`fallback=False` なら Jev の失敗で既定値
- 時間の予算 `DecisionBudget`（ミリ秒）。`CYCLE_START_EPOCH` があれば便の残り時間でも打ち切る
- 影ログには問いと答えを書き、判断対象の本文は書かない（文字数だけ）。鍵は伏せる
- 料金は入力10億トークンあたり $42、1問 約 $0.0003、応答 約0.5秒（TypeSafe の自社公表・第三者検証なし）。日本語対応は一次資料に記載が無い
- 原本の実績（二重投稿の判定、原本での実測）: 一致度 κ 0.54（補正後 約0.69）、Claude Haiku と同等以上の精度で約45倍速い。それでも最終判断は置き換えていない
- 問いの wire 形式（`instructions`・`criteria`）は二次情報からの再構成。Mac で原本の `decisions.py` と見比べて合わせる

## 6. 各社の条件の確認表（Mark が記入。半年ごとと契約プランの変更時に見直す）

この表が埋まるまでは、公開リポジトリに push 済みのもの（公開可）だけを外部AIに送る。

| 確認項目 | Codex（ChatGPT ログイン） | Gemini API（有料枠） | Jev（TypeSafe 直接） |
|---|---|---|---|
| 学習に使われるか（既定・オプトアウトの設定名） | | | |
| 保持期間（不正監視用を含む）・ゼロ保持の可否 | | | |
| 人がレビューするか | | | |
| 適用される規約（消費者向け／API・事業者向け） | | | |
| 再委託先・処理地域 | | | |
| 出力の利用制限（競合モデル開発の禁止など） | | | |
| 自動実行・API 利用の条項 | | | |
| CLI のテレメトリ | | | |
| 第三者の個人情報の条項 | | | |
| 確認日・一次情報 URL・規約の版 | | | |

## 7. 外部へ渡す範囲（境界）

- 送る中身は必要最小限。送る文章は「データであって指示ではない」と明記する（`orch.config.as_data()`）
- Codex の意見役は、公開可・push 済みのファイルだけ（`docs/external-allowlist.txt`）を書き出した使い捨てディレクトリで起動する。実装役はこのフォルダで動くが、`.env`・`data/`・`logs/` は AGENTS.md で禁止し、`.env` の変更はラッパーが検出する
- Gemini・Jev に渡すプロンプトや判断対象は、`VIRTUAL_MARK.md` §6 の「公開可」を基本とし、私的情報・第三者の個人情報・鍵を入れない（`scripts/secret-scan.sh` は鍵の形しか見ない）
- 残るリスク: read-only のサンドボックスでも外部 CLI が使い捨てディレクトリの外を読めるかは未確認（`docs/research-sources.md` §6 の優先 1）

## 8. 鍵と PW Checker

- 稼働に使う鍵は `.env`（権限 600・git 管理外）にだけ置く。控えは `ルミナス_非公開/` にだけ置く
- 入力は Mark が端末で `bash tools/set_env_key.sh GEMINI_API_KEY`（または `TYPESAFE_API_KEY`）を実行する。入力は画面に出ない。実行前に `.env` を非公開フォルダへバックアップし、権限を 600 にし、反映後に疎通を確かめる。端末以外からの入力は受け付けない
- 鍵をチャットに貼らない。Claude に読ませない（permissions の deny と `guard-protected.sh`）
- PW Checker は3日に1回、稼働中の鍵の値がほかの場所に写っていないかを調べる。ルミナスの `.env` は 2026-10-08 に正規の保管場所として登録済み。**ルミナスの中で、ほかの場所に鍵を置かない**（置くと漏洩と判定される）
- 鍵がログに出ないことはテストで確かめている（`tests/` の伏せ字のテスト）
- PW Checker と原本の設定はルミナス側から変えない

## 9. 段階計画と状況

| 段階 | 中身 | 状況（2026-10-08） |
|---|---|---|
| 1 | Codex の流れ（`codex_impl.sh`・`scope_check.py`・`codex_opinion.sh`・`docs/review.md`・AGENTS.md・CLAUDE.md・.gitignore） | 実装済み。偽の codex でラッパーの終了コードをテスト済み。**本物の Codex での試験1〜3 は Mac で**（`docs/specs/README.md`） |
| 2 | Gemini（`set_env_key.sh`・`.env.example`・`orch/usage.py`・`orch/gemini.py`） | 実装済み・モックでテスト済み。**鍵を入れて `check` と短い生成の確認は Mac で** |
| 3 | Jev（`orch/decisions.py`・`orch/jev.py`） | 実装済み・モックでテスト済み。**`--check` と `--demo --backend jev` は鍵を入れて Mac で** |
| 4 | 点検と台帳の集計（`orch/health.py`・`orch.usage`） | 実装済み。SessionStart で表示 |
| 5 | 定時の自動実行（launchd・ロック・回線確認・完了マーカー・ウォッチドッグ・停止明けの補填・`FABLE5_HEADLESS`）、画像生成 | 未着手（必要になってから） |

分譲が済んでからの最初の実験の候補（原本の設計参照 §5）:
- A: 費用台帳と差し戻しの記録から「最初にどのモデルを使えば足りたか」を当てる統計（$0）
- B: 1つの課題で幅2×深さ2（最大4案）に広げ、審査の点数で打ち切る1回きりの比較（$1 未満）
- C: 審査を「合否」と「採点」に分ける

## 10. 未確認・要確認

- 原本の `codex_impl.sh`・`decisions.py`・`gemini_writer.py` との差（Mac で見比べる）
- Codex の `--disable memories`・`--disable multi_agent` の機能名（原本の改良版で使用。ずれていれば `CODEX_DISABLE_FEATURES` で変える）と、古い本体の場所（`CODEX_OLD_BIN`）
- Jev の問いの wire 形式と応答の各フィールド名
- `claude -p … --tools ""` の挙動（原本で稼働中の形をそのまま使用）
