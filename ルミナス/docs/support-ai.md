# サポートAI（Codex・Gemini・Jev）— AI NEWS Select の仕組みをルミナスへ移す v0.1

> Mark の「Fable5.1 AI NEWS Select」（AIニュースの検証と解説）では、司令塔 Claude のもとで
> **Codex・Gemini・Jev を常用**している。ルミナスはその三者を「サポートAI」として同じ位置に置く。
> AI NEWS Select 側の定義ファイル（CLAUDE.md / ROUTINE.md / digest 等）は本調査では見つからなかったため、
> 本書は Mark の指示と各サービスの公開情報から再構成したものである。**実物のファイルを `docs/ai-news-select-ref/` に置いてもらえれば、
> 用語・手順をそちらに合わせて v0.2 で揃える。**

## 1. 三者の役割分担（ルミナスでの標準）

| サポートAI | 得意 | ルミナスでの役割（TRINITY 風） | 典型的な呼び方 | 鍵の環境変数 |
|---|---|---|---|---|
| **Codex**（GPT-6 Astra / Sol） | 長時間の自律作業、実装、第二意見 | **Worker（実装）** と **Thinker 第二意見（反証役）** | `scripts/ask-astra.sh <パケット>`（`codex exec`） | `OPENAI_API_KEY`（または `codex login`） |
| **Gemini**（Gemini CLI / API） | 長文・多モーダル・Google 検索グラウンディング、別ベンダーの視点 | **StarPulse（調査）** と **クロスベンダー検証**（Claude/Codex と答えが割れたときの第三の目） | `scripts/ask-gemini.sh <パケット>`（`gemini -p`） | `GEMINI_API_KEY` |
| **Jev**（TypeSafe AI）【実験】 | 文章を生成せず、型付きの判定だけを返す（Noul=はい/いいえの確率、Choice=選択、Score=採点） | **止める側の信号だけ**: NO-GO・保留、出典の信頼度分類、エスカレーション要否、憲章違反の疑いフラグ。通す根拠や改善の採点には使わない（`docs/eval-design.md`） | `scripts/jev_gate.py`（`POST /v1/systemone`。OpenRouter 経由も可） | `TYPESAFE_API_KEY`（OpenRouter 経由なら `OPENROUTER_API_KEY`） |

鍵はいずれも **Mark のシェルや OS のキーチェーンから、各ラッパースクリプトが実行時に読む**。ファイル（`settings.local.json` を含む）・チャット・コミットに書かない（憲章 I-4）。
司令塔は値を表示・記録しない。`printenv`・`env` と鍵ファイルの読取は permissions で deny しているが、環境変数は原理的にプロセスから読めるため、残るリスクは「司令塔のセッション環境に鍵を置かない」運用で下げる（鍵が要るのはラッパーを実行する Mark のシェル側）。

## 2. なぜこの三者か（AI NEWS Select の仕組みの読み替え）

AI NEWS Select の検証規則（Mark の指示）は次の通りで、三者はそれぞれの段に対応する。

| AI NEWS Select の段 | 内容 | 担当 |
|---|---|---|
| 一次情報の収集・照合 | 公式発表・論文・公式 GitHub を直接読み、報道の要約と照合 | Claude（司令塔）＋ **Gemini**（検索グラウンディング・長文読解） |
| 出典の信頼度判定 | ①一次情報 〜 ⑤個人ブログ の 5 段階に分類。自己申告か第三者測定かを区別 | **Jev**（Choice: ①〜⑤ の分類、Noul: 「自己申告のみか」） |
| 矛盾・極端な主張の深掘り | 数値の食い違い、裏付けの薄い極端な主張をサブ LLM で検証し GO/NO-GO | **Codex**（反証役）＋ Claude（Opus）。最終 GO/NO-GO の数値化は **Jev**（Score） |
| エスカレーション | 通常 Opus 4.8 以下、極めて重大・矛盾深刻時のみ Fable 5 | **Jev**（Noul: 「上位モデルの裁定が必要か」）→ 司令塔が切替し `state/escalations.log` に記録 |
| 機能確認 | 製品・モデルの実能力を公式ドキュメント・デモ・第三者レビューで確認 | **Codex**（実際に動かす）＋ Gemini（第三者レビューの収集） |

Jev を「止める側のゲート」に置く理由: 文章を生成しないので速く安く（公開情報では入力 100 万トークンあたり約 0.042 USD、出力無料。自己申告・2026-09 時点）、
判定が確率と信頼度で返るため **閾値をルールとして書ける**（例: 「出典が③以下の確率 > 0.6 なら投稿しない」）。
ただし Jev 自身の判定も「主張」であり、閾値と採点基準は評価セットで校正する（ROUTINE §4、Phase 1）。

## 3. 呼び出しの標準形（パケット方式）

三者とも **パケット（Markdown の依頼文）を渡し、回答をファイルに保存**する。これにより会話が切れても結果が残り、司令塔が裏取りしてから採用できる。

- Codex: `docs/astra-packets/*.md` → `docs/astra-replies/`
- Gemini: `docs/gemini-packets/*.md` → `docs/gemini-replies/`
- Jev: 判定リクエストは JSON（`scripts/jev_gate.py --state-file <対象> --questions docs/jev-questions/news-gate.json`）→ `state/jev/` に判定ログ（確率・閾値・結論・usage）。API は `POST https://api.typesafe.ai/v1/systemone`（model `jev-latest`）、または OpenRouter `POST /api/alpha/decisions`（model `typesafe/jev-1.13`）。公式 SDK は `pip install typesafe-sdk` / `npm install @typesafe-ai/sdk`

## 4. ネットワークと鍵（クラウド環境で動かす場合）

| 宛先 | 用途 | 2026-10-07 の到達性（クラウド環境） |
|---|---|---|
| `api.openai.com`, `auth.openai.com`, `chatgpt.com` | Codex | 遮断（403） |
| `generativelanguage.googleapis.com` | Gemini API / CLI | 到達可（鍵は未設定） |
| `api.typesafe.ai`（または `openrouter.ai`） | Jev | 遮断（403） |
| `api.x.ai` | Grok | 遮断（403） |

クラウド環境で動かすには上記ホストの許可と、環境側の「Network secrets／環境変数」への鍵登録が必要（司令塔の環境にも鍵が見える点は上記のとおり残るリスク。許可ホストは最小限にする）。
Mac で動かす場合は Mark のシェル環境（キーチェーン経由を推奨）に鍵を置き、`.claude/settings.local.json` には書かない。

## 5. 外部へ渡す範囲（境界）

- 送出の単位は「パケット」ではなく**外部AIが読めるもの全部**。Codex・Gemini は `scripts/export-public.sh` が書き出した使い捨てディレクトリで起動する
  （中身は `docs/external-allowlist.txt` の公開可パスだけ。push 済みの上流から書き出すので、未 push の変更は外に出ない。`state/`・`digest/`・`obsidian/`・他AIの回答は含めない）
- パケットは `docs/astra-packets/`・`docs/gemini-packets/` に置いたものだけを受け付ける。送信前に鍵の検査を通す
- Jev は判定対象の全文が第三者に渡る。allowlist の外の文書は `--public-ok`（公開予定であることを Mark が確認済み）が要る
- 残るリスク: read-only のサンドボックスでも、外部 CLI が使い捨てディレクトリの外を読めるかは未確認（検証台帳の優先 1）。秘匿情報の検査は鍵の形しか見ず、個人情報や第三者の名前は検出しない

## 6. 各社の条件の確認表（Mark が記入。半年ごとと契約プランの変更時に見直す）

この表が埋まるまでは、公開リポジトリに push 済みのものだけを送る。

| 確認項目 | Codex（ChatGPT ログイン） | Codex（API キー） | Gemini（無料枠） | Gemini（有料） | Jev（直接） | OpenRouter 経由 |
|---|---|---|---|---|---|---|
| 学習に使われるか（既定・オプトアウトの設定名） | | | | | | |
| 保持期間（不正監視用を含む）・ゼロ保持の可否 | | | | | | |
| 人がレビューするか | | | | | | |
| 適用される規約（消費者向け／API・事業者向け） | | | | | | |
| 再委託先・処理地域 | | | | | | |
| 出力の利用制限（競合モデル開発の禁止など） | | | | | | |
| 自動実行・API 利用の条項 | | | | | | |
| CLI のテレメトリ | | | | | | |
| 第三者の個人情報の条項 | | | | | | |
| 確認日・一次情報 URL・規約の版 | | | | | | |

## 7. 未確認・要確認

- Jev API のリクエスト形式はコミュニティの実例と公式 SDK README から再構成した（公式ドキュメント本文は未読）。直接 API は早期アクセス待ちとの記述が一つあり、その場合は OpenRouter 経由（`JEV_PROVIDER=openrouter`）で動かす
- AI NEWS Select で使っている Gemini のモデル名、Jev の質問セット（実物の定義ファイルを参照したい）
- Grok（xAI）を Phase 1 から入れるか
