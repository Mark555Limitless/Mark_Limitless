# サポートAI（Codex・Gemini・Jev）— AI NEWS Select の仕組みをルミナスへ移す v0.1

> Mark の「Fable5.1 AI NEWS Select」（X: @Fable5AINEWS、AIニュースの検証と解説）では、司令塔 Claude のもとで
> **Codex・Gemini・Jev を常用**している。ルミナスはその三者を「サポートAI」として同じ位置に置く。
> AI NEWS Select 側の定義ファイル（CLAUDE.md / ROUTINE.md / digest 等）は本調査では見つからなかったため、
> 本書は Mark の指示と各サービスの公開情報から再構成したものである。**実物のファイルを `docs/ai-news-select-ref/` に置いてもらえれば、
> 用語・手順をそちらに合わせて v0.2 で揃える。**

## 1. 三者の役割分担（ルミナスでの標準）

| サポートAI | 得意 | ルミナスでの役割（TRINITY 風） | 典型的な呼び方 | 鍵の環境変数 |
|---|---|---|---|---|
| **Codex**（GPT-6 Astra / Sol） | 長時間の自律作業、実装、第二意見 | **Worker（実装）** と **Thinker 第二意見（反証役）** | `scripts/ask-astra.sh <パケット>`（`codex exec`） | `OPENAI_API_KEY`（または `codex login`） |
| **Gemini**（Gemini CLI / API） | 長文・多モーダル・Google 検索グラウンディング、別ベンダーの視点 | **StarPulse（調査）** と **クロスベンダー検証**（Claude/Codex と答えが割れたときの第三の目） | `scripts/ask-gemini.sh <パケット>`（`gemini -p`） | `GEMINI_API_KEY` |
| **Jev**（TypeSafe AI） | 文章を生成せず、型付きの判定だけを返す（Noul=はい/いいえの確率、Choice=選択、Score=採点） | **Verifier のゲート**: GO/NO-GO、出典の信頼度分類、エスカレーション要否、憲章違反の疑いフラグ | `scripts/jev_gate.py`（`POST /v1/systemone`。OpenRouter 経由も可） | `TYPESAFE_API_KEY`（OpenRouter 経由なら `OPENROUTER_API_KEY`） |

鍵はいずれも **環境変数で渡す**。ファイル・チャット・コミットに書かない（憲章 I-4）。ルミナスは値を表示しない。

## 2. なぜこの三者か（AI NEWS Select の仕組みの読み替え）

AI NEWS Select の検証規則（Mark の指示）は次の通りで、三者はそれぞれの段に対応する。

| AI NEWS Select の段 | 内容 | 担当 |
|---|---|---|
| 一次情報の収集・照合 | 公式発表・論文・公式 GitHub を直接読み、報道の要約と照合 | Claude（司令塔）＋ **Gemini**（検索グラウンディング・長文読解） |
| 出典の信頼度判定 | ①一次情報 〜 ⑤個人ブログ の 5 段階に分類。自己申告か第三者測定かを区別 | **Jev**（Choice: ①〜⑤ の分類、Noul: 「自己申告のみか」） |
| 矛盾・極端な主張の深掘り | 数値の食い違い、裏付けの薄い極端な主張をサブ LLM で検証し GO/NO-GO | **Codex**（反証役）＋ Claude（Opus）。最終 GO/NO-GO の数値化は **Jev**（Score） |
| エスカレーション | 通常 Opus 4.8 以下、極めて重大・矛盾深刻時のみ Fable 5 | **Jev**（Noul: 「上位モデルの裁定が必要か」）→ 司令塔が切替し `state/escalations.log` に記録 |
| 機能確認 | 製品・モデルの実能力を公式ドキュメント・デモ・第三者レビューで確認 | **Codex**（実際に動かす）＋ Gemini（第三者レビューの収集） |

Jev を「ゲート」に置く理由: 文章を生成しないので速く安く（公開情報では入力 100 万トークンあたり約 0.042 USD、出力無料。自己申告・2026-09 時点）、
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

クラウド環境の設定で上記を許可し、鍵を「Network secrets／環境変数」に登録すれば、新しいセッションから `scripts/ask-*.sh` がそのまま動く。
Mac で動かす場合はシェルの環境変数に鍵を置く（`.claude/settings.local.json` の `env` でもよい。git 管理外）。

## 5. 未確認・要確認

- Jev API のリクエスト形式はコミュニティの実例と公式 SDK README から再構成した（公式ドキュメント本文は未読）。直接 API は早期アクセス待ちとの記述が一つあり、その場合は OpenRouter 経由（`JEV_PROVIDER=openrouter`）で動かす
- AI NEWS Select で使っている Gemini のモデル名、Jev の質問セット（実物の定義ファイルを参照したい）
- Grok（xAI）を Phase 1 から入れるか
