# 参考調査と出典（2026-10-07 時点）

本構想で参照した外部システム・研究と、その出典の信頼度。
クラウド作業環境では `sakana.ai` / `arxiv.org` / `openai.com` / `huggingface.co` への直接取得が
ネットワークポリシーで遮断されたため、**直接読めたもの**と**検索結果の要約・GitHub README 経由で確認したもの**を区別して記す。

信頼度: ①一次情報 ②査読・第三者評価 ③技術メディア・通信社 ④個人SNS・GitHub Issue ⑤動画・個人ブログ

## 1. Sakana AI のオーケストレーション系

| 対象 | 要点 | 出典 | 信頼度 / 確認方法 |
|---|---|---|---|
| Multi-LLM AB-MCTS / TreeQuest | 推論時に「新しい案を広げる（wider）」か「既存案を深める（deeper）」かを適応的に選び、複数の異種 LLM を混ぜて試行錯誤する。ARC-AGI-2 で単体モデルを上回ったと報告（自己申告）。TreeQuest は Apache-2.0、`generate` 関数と 0〜1 のスコアを与える ask/tell 型 API | https://sakana.ai/ab-mcts/ ・ https://github.com/SakanaAI/treequest ・ arXiv 2503.04412 | ①（README は直接確認。sakana.ai 本文と arXiv は検索要約のみ） |
| TRINITY（ICLR 2026） | 約 0.6B の小型コーディネータ＋約 10K パラメータのヘッドを CMA-ES（進化戦略）で最適化。各ターンで Thinker / Worker / Verifier のいずれかの役割を選んだ LLM に割り当てる。LiveCodeBench 86.2% を主張（自己申告） | arXiv 2512.04695 ・ https://sakana.ai/trinity/ | ②（ICLR 採択は検索結果で確認。本文は未読） |
| Conductor（ICLR 2026） | 7B のコーディネータを RL で学習し、自然言語でワークフロー（手順・担当エージェント・可視範囲＝通信トポロジ）を設計する。LiveCodeBench・GPQA で単体を上回ると主張（自己申告） | arXiv 2512.04388 ・ https://sakana.ai/learning-to-orchestrate/ | ②（同上） |
| Sakana Fugu / Fugu Ultra（2026-06-22 β） | TRINITY と Conductor を商用化した「単一モデルとして振る舞うマルチエージェント」。Chat Completions / Responses 互換の API。Codex や Claude Code にワンライナーで組み込める旨。Gemini 3.1 Pro・Opus 4.8・GPT 5.5 を上回るとの比較は **Sakana 自己申告・独立検証なし**。README にライセンス記載なし | https://github.com/SakanaAI/fugu ・ https://sakana.ai/fugu-beta/ | ①（GitHub README を直接確認）／ベンチは自己申告 |
| ShinkaEvolve（ICLR 2026） | LLM を変異演算子にした進化的プログラム探索。親サンプリング、埋め込み類似度による新規性棄却、UCB バンディットでコスト意識の LLM 選択。Apache-2.0。`evaluate.py` が `combined_score` を返す | https://github.com/SakanaAI/ShinkaEvolve ・ arXiv 2509.19349 | ①（README 直接確認） |
| Darwin Gödel Machine（DGM） | 自分のコードを書き換えるコーディングエージェントのアーカイブを開放的に探索。SWE-bench / Polyglot で改善を報告。README に「モデル生成コードの実行は危険」と明記し Docker 隔離 | https://github.com/jennyzzt/dgm ・ arXiv 2505.22954 | ①（README 直接確認）／数値は論文の自己申告 |
| AI Scientist v2 | 研究プロセス自動化。2026-03 に Nature 掲載との報道 | 検索結果のみ | ③（未確認。構想では直接は使わない） |

**取り込むべき設計思想（Sakana 系）**
- 異種モデルの組み合わせは単体より強い（AB-MCTS / Fugu）。ただし効くのは「試行錯誤できる・採点できる課題」
- 役割を Thinker / Worker / Verifier に分けると小さなコーディネータでも統率できる（TRINITY）
- 「広げるか深めるか」を予算の中で適応的に決める（AB-MCTS）→ 好奇心ブーストの実装に対応
- 自己改善は「評価関数＋アーカイブ＋隔離実行」が前提（ShinkaEvolve / DGM）。評価のない自己改善はしない

## 2. OpenAI（Codex / GPT-6 Astra）

| 対象 | 要点 | 出典 | 信頼度 |
|---|---|---|---|
| GPT-6 Astra（2026-09-03） | OpenAI の最上位モデル。計算機操作・コーディング・サイバー・科学で最高性能と主張（自己申告）。長時間・複数エージェント協調を強調。API / ChatGPT 各プラン / Azure / Bedrock で提供 | https://openai.com/index/gpt-6-astra/ ・ https://openai.com/index/path-to-astra/ | ①（ページ本文は遮断のため検索要約のみ。要再確認） |
| GPT-6 Sol / Luna（2026-09-22） | Astra に近い知能を約 1/5 の価格で、との主張（自己申告）。Sol は Responses API でサブエージェント委譲（β） | https://openai.com/index/introducing-gpt-6-sol-and-luna/ | ①（同上） |
| Codex CLI サブエージェント | 組み込み `default` / `worker` / `explorer`。`.codex/agents/*.toml` に `name` / `description` / `developer_instructions`（任意で `model` / `model_reasoning_effort` / `sandbox_mode`）。`config.toml` の `[agents]` で `enabled` / `default_subagent_model` 等。`AGENTS.md` はディレクトリを辿って読み込まれる | https://developers.openai.com/codex/subagents ・ https://github.com/openai/codex/discussions/6109 | ①（Discussion は直接確認。公式ドキュメントは遮断） |

## 3. Anthropic（Claude Code / マルチエージェント）

| 対象 | 要点 | 出典 | 信頼度 |
|---|---|---|---|
| マルチエージェント研究システムの構築知見 | オーケストレーター＝ワーカー型。Opus 主導＋Sonnet 副 で単体 Opus より内部評価 90.2% 改善（幅優先の調査課題）。ただしトークンはチャットの約 15 倍。サブエージェントには目的・出力形式・ツール指針・境界を明示。LLM-as-judge と人手評価の併用。長時間実行の状態管理・チェックポイント・レインボーデプロイが本番の壁 | https://www.anthropic.com/engineering/built-multi-agent-research-system | ①（直接確認） |
| サブエージェント仕様 | `.claude/agents/*.md`（YAML frontmatter: `name` `description` `tools` `model`(sonnet/opus/haiku/fable/inherit) `effort` `hooks` `memory` `maxTurns` 等）。深さ 3・同時 20 が既定上限 | https://code.claude.com/docs/en/sub-agents | ①（直接確認） |
| hooks 仕様 | `SessionStart`（startup/resume/clear/compact）の stdout はコンテキストに注入。`PreToolUse` は exit 2 または `permissionDecision: deny` でブロック。`PreCompact` / `SubagentStop` / `TaskCompleted` 等 | https://code.claude.com/docs/en/hooks | ①（直接確認） |
| Agent Teams（実験的） | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`。リード＋チームメイトが共有タスクリストとメールボックスで協調。サブエージェントより高コスト。研究・レビュー・競合仮説の検証に向く。3〜5 人から | https://code.claude.com/docs/en/agent-teams | ①（直接確認） |
| モデルと価格（1M トークンあたり 入力/出力） | Fable 5.1 $10/$50、Opus 5.5 $4/$20、Sonnet 5.5 $2/$10、Haiku 4.5 $1/$5（Anthropic API 直販価格） | Claude Code 同梱 `claude-api` スキル（2026-09-25 時点のキャッシュ） | ① |

## 3b. その他のサポートAI

| 対象 | 要点 | 出典 | 信頼度 |
|---|---|---|---|
| TypeSafe AI「Jev」 | 文章を生成せず型付き判定を返す「System One」モデル。質問型は Noul（はい/いいえの確率）・Choice（最大 255 択、各確率と信頼度）・Score（2〜10 段階）。`POST https://api.typesafe.ai/v1/systemone`。SDK は `pip install typesafe-sdk` / `npm install @typesafe-ai/sdk`。公開 API は 2026-09-21、入力 100 万トークン 0.042 USD・出力無料（自己申告） | https://docs.typesafe.ai/introduction ・ https://github.com/rajivkuriakose/typesafe-jev-examples ・ https://github.com/kraayenjon/awesome-jev | ①（公式ドキュメントは遮断で未読。GitHub の例と検索要約で確認）／価格は自己申告 |
| Gemini CLI | 非対話は `gemini -p "..."`（`--output-format json` 可）、モデルは `-m`、認証は `GEMINI_API_KEY` か Google ログイン。コンテキストファイルは `GEMINI.md` | https://github.com/google-gemini/gemini-cli | ①（README 直接確認） |

## 4. Mark の既存運用（社内一次情報）

- `Mark555Limitless/nou-denchi` の `CLAUDE.md` / `AGENTS.md`: 司令塔＝Claude、実装＝Codex（指示書・`<!-- ALLOWED -->` で変更範囲を限定・git とネットワーク禁止）、`npm run verify` で検証、コード審査はモデル明示で APPROVE 後にコミット
- `Mark555Limitless/obsidian-vault`: 共通知識の置き場として指定されている（現状の内容は私的メモが中心のため、ルミナス用の区画を分ける）
- 「Fable5.1 AI NEWS Select」の AI チーム（X: @Fable5AINEWS）: Codex・Gemini・Jev を常用。本人指示（出典ピラミッド・サブ LLM 深掘り検証・GO/NO-GO・エスカレーション）から規則は把握できたが、定義ファイルの所在は未確認（Notion・Drive・両リポジトリに無し。Gmail は再認証が必要で未検索）

## 5. 利益相反の注記

Sakana Fugu と GPT-6 Astra の優位性主張は、いずれも開発元の自己申告であり、本調査時点で独立第三者（Artificial Analysis・LMArena・HELM 等）の数値は確認できていない。
採用判断は、ルミナス自身の評価セットでの実測に基づいて行う。
