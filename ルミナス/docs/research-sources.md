# 参考調査と出典（2026-10-07 時点）

本構想で参照した外部システム・研究と、その出典の信頼度。
クラウド作業環境では `sakana.ai` / `arxiv.org` / `openai.com` / `huggingface.co` への直接取得が
ネットワークポリシーで遮断されたため、**直接読めたもの**と**検索結果の要約・GitHub README 経由で確認したもの**を区別して記す。

信頼度: ①一次情報 ②査読・第三者評価 ③技術メディア・通信社 ④個人SNS・GitHub Issue ⑤動画・個人ブログ

## 1. Sakana AI のオーケストレーション系

| 対象 | 要点 | 出典 | 信頼度 / 確認方法 |
|---|---|---|---|
| Multi-LLM AB-MCTS / TreeQuest | 推論時に「新しい案を広げる（wider）」か「既存案を深める（deeper）」かを適応的に選び、複数の異種 LLM を混ぜて試行錯誤する。ARC-AGI-2 で単体モデルを上回ったと報告（自己申告）。TreeQuest は Apache-2.0、`generate` 関数と 0〜1 のスコアを与える ask/tell 型 API | https://sakana.ai/ab-mcts/ ・ https://github.com/SakanaAI/treequest ・ arXiv 2503.04412 | ①（README は直接確認。sakana.ai 本文と arXiv は検索要約のみ） |
| TRINITY（ICLR 2026） | 約 0.6B の小型コーディネータ＋約 10K パラメータのヘッドを CMA-ES（進化戦略）で最適化。各ターンで Thinker / Worker / Verifier のいずれかの役割を選んだ LLM に割り当てる。LiveCodeBench 86.2% を主張（自己申告） | arXiv 2512.04695 ・ https://sakana.ai/trinity/ | ②相当（ICLR 採択は検索結果で確認。論文本文は未読・要再確認） |
| Conductor（ICLR 2026） | 7B のコーディネータを RL で学習し、自然言語でワークフロー（手順・担当エージェント・可視範囲＝通信トポロジ）を設計する。LiveCodeBench・GPQA で単体を上回ると主張（自己申告） | arXiv 2512.04388 ・ https://sakana.ai/learning-to-orchestrate/ | ②相当（同上。本文未読） |
| Sakana Fugu / Fugu Ultra | TRINITY と Conductor を商用化した「単一モデルとして振る舞うマルチエージェント」。Chat Completions / Responses 互換の API。Codex や Claude Code にワンライナーで組み込める旨。他社フロンティアモデルを上回るとの比較は **Sakana 自己申告・独立検証なし**（README の比較対象の表記は要再確認）。README にライセンス記載なし。β公開日「2026-06-22」は技術メディアの報道（③） | https://github.com/SakanaAI/fugu ・ https://sakana.ai/fugu-beta/ | ①（GitHub README を直接確認。sakana.ai 本文は未読）／ベンチは自己申告 |
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
| GPT-6 Astra（2026-09-03） | OpenAI の最上位モデル。計算機操作・コーディング・サイバー・科学で最高性能と主張（自己申告）。長時間・複数エージェント協調を強調。API / ChatGPT 各プラン / Azure / Bedrock で提供 | https://openai.com/index/gpt-6-astra/ ・ https://openai.com/index/path-to-astra/ | 一次ページ未読（検索要約のみ。要再確認） |
| GPT-6 Sol / Luna（2026-09-22） | Astra に近い知能を約 1/5 の価格で、との主張（自己申告）。Sol は Responses API でサブエージェント委譲（β） | https://openai.com/index/introducing-gpt-6-sol-and-luna/ | 一次ページ未読（検索要約のみ） |
| Codex CLI サブエージェント | 組み込み `default` / `worker` / `explorer`。`.codex/agents/*.toml` に `name` / `description` / `developer_instructions`（任意で `model` / `model_reasoning_effort` / `sandbox_mode`）。`config.toml` の `[agents]` で `enabled` / `default_subagent_model` 等。`AGENTS.md` はディレクトリを辿って読み込まれる | https://developers.openai.com/codex/subagents ・ https://github.com/openai/codex/discussions/6109 | ①（Discussion は直接確認。公式ドキュメントは遮断） |

## 3. Anthropic（Claude Code / マルチエージェント）

| 対象 | 要点 | 出典 | 信頼度 |
|---|---|---|---|
| マルチエージェント研究システムの構築知見 | オーケストレーター＝ワーカー型。Opus 主導＋Sonnet 副 で単体 Opus より内部評価 90.2% 改善（幅優先の調査課題）。ただしトークンはチャットの約 15 倍。サブエージェントには目的・出力形式・ツール指針・境界を明示。LLM-as-judge と人手評価の併用。長時間実行の状態管理・チェックポイント・レインボーデプロイが本番の壁 | https://www.anthropic.com/engineering/built-multi-agent-research-system | ①（直接確認） |
| サブエージェント仕様 | `.claude/agents/*.md`（YAML frontmatter: `name` `description` `tools` `model`(sonnet/opus/haiku/fable/inherit) `effort` `hooks` `memory` `maxTurns` 等）。深さ 3・同時 20 が既定上限 | https://code.claude.com/docs/en/sub-agents | ①（直接確認） |
| hooks 仕様 | `SessionStart`（startup/resume/clear/compact）の stdout はコンテキストに注入。`PreToolUse` は exit 2 または `permissionDecision: deny` でブロック。`PreCompact` / `SubagentStop` / `TaskCompleted` 等 | https://code.claude.com/docs/en/hooks | ①（直接確認） |
| Agent Teams（実験的） | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`。リード＋チームメイトが共有タスクリストとメールボックスで協調。サブエージェントより高コスト。研究・レビュー・競合仮説の検証に向く。3〜5 人から | https://code.claude.com/docs/en/agent-teams | ①（直接確認） |
| モデルと価格（1M トークンあたり 入力/出力） | Fable 5.1 $10/$50、Opus 5.5 $4/$20、Sonnet 5.5 $2/$10、Haiku 4.5 $1/$5（Anthropic API 直販価格） | Claude Code 同梱 `claude-api` スキル（2026-09-25 時点のキャッシュ） | ①相当だがキャッシュ。一次ページ（anthropic.com の価格表）は未読 |

## 3b. その他のサポートAI

| 対象 | 要点 | 出典 | 信頼度 |
|---|---|---|---|
| TypeSafe AI「Jev」 | 文章を生成せず型付き判定を返す「System One」モデル。質問型は Noul（はい/いいえの確率）・Choice（最大 255 択、各確率と信頼度）・Score（2〜10 段階）。`POST https://api.typesafe.ai/v1/systemone`。SDK は `pip install typesafe-sdk` / `npm install @typesafe-ai/sdk`。公開 API は 2026-09-21、入力 100 万トークン 0.042 USD・出力無料（自己申告） | https://docs.typesafe.ai/introduction ・ https://github.com/rajivkuriakose/typesafe-jev-examples ・ https://github.com/kraayenjon/awesome-jev | ①（公式ドキュメントは遮断で未読。GitHub の例と検索要約で確認）／価格は自己申告 |
| Gemini CLI | 非対話は `gemini -p "..."`（`--output-format json` 可）、モデルは `-m`、認証は `GEMINI_API_KEY` か Google ログイン。コンテキストファイルは `GEMINI.md` | https://github.com/google-gemini/gemini-cli | ①（README 直接確認） |

## 4. Mark の既存運用（社内一次情報）

- `Mark555Limitless/nou-denchi` の `CLAUDE.md` / `AGENTS.md`: 司令塔＝Claude、実装＝Codex（指示書・`<!-- ALLOWED -->` で変更範囲を限定・git とネットワーク禁止）、`npm run verify` で検証、コード審査はモデル明示で APPROVE 後にコミット
- Obsidian vault: 共通知識の置き場として指定されている（ルミナス用の区画 `ルミナス/` を分けて同期する）
- 「Fable5 AI NEWS Select」の AI チーム（Mark の X アカウントで運用）: Codex・Gemini・Jev を常用。仕組みは 2026-10-08 に AI NEWS Select の司令塔が書いた「ルミナス分譲指示書」で受け取った（原本はローカルパスを含むため非公開フォルダで保管、要約は `docs/support-ai.md`）。指示書に載っている稼働中の形は、検証台帳で〔Mark の稼働実績〕として扱う

## 5. 利益相反の注記

Sakana Fugu と GPT-6 Astra の優位性主張は、いずれも開発元の自己申告であり、本調査時点で独立第三者（Artificial Analysis・LMArena・HELM 等）の数値は確認できていない。
採用判断は、ルミナス自身の評価セットでの実測に基づいて行う。

## 6. 検証台帳（未検証の外部事実）

本文中の事実にはラベルを付ける: 〔一次確認 日付〕〔Mark の稼働実績〕〔二次のみ〕〔未確認〕〔自己申告〕。〔Mark の稼働実績〕は、AI NEWS Select の原本で実際に動いている形（分譲指示書 2026-10-08 に記載）を指す。未確認の事実に頼る処理は、失敗したら止まる側に倒す。
確認の優先順位は「設計への依存度 × 外れたときの損害 × 確認の手軽さ」で決めた（上位審査 2026-10-07）。

| 優先 | 主張 | ラベル | 依存箇所 | 確認方法 | 確認日 |
|---|---|---|---|---|---|
| 1 | `codex exec` のオプション（`-C`・`-s`・`--skip-git-repo-check`・`-m`・`-o`・`--disable`）と、read-only での読み取り範囲 | オプションは〔一次確認 2026-10-07〕（codex-cli 0.161.0 の `--help`）。読み取り範囲は〔未確認〕 | tools/codex_impl.sh・tools/codex_opinion.sh | Mac で `codex exec --help`、read-only で ROOT 外のファイルを読めるか実験 | |
| 2 | Gemini API の `thinkingConfig.thinkingLevel`・`x-goog-api-key`・価格（$0.75／$3.75、2027-01 から $1.50／$7.50） | 〔Mark の稼働実績〕（分譲指示書・原本で稼働中） | orch/gemini.py | Mac で `python3 -m orch.gemini check` と短い生成 | |
| 3a | Claude Code の PostModelSwitch hook | イベントの存在は〔一次確認 2026-10-07〕（hooks 公式文書の一覧）。入力の `from_model`/`to_model` は〔未確認〕 | .claude/hooks/log-model-switch.sh | 実際に `/model` を切り替えて escalations.log を確認 | |
| 3b | `Edit(/CHARTER.md)` の ask が実際に確認を出すか。リダイレクトは Edit 規則の対象、`sed -i` は対象外 | リダイレクトの扱いは〔一次確認 2026-10-07〕（permissions 公式文書）。実地は〔未確認〕 | .claude/settings.json、guard-protected.sh | このフォルダで起動し CHARTER.md を Edit してみる | |
| 3c | bypass・auto モードで ask と PreToolUse hook がどう動くか | 〔未確認〕 | 統治全体 | 実地テスト 1 回 | |
| 4 | Jev の API（`/v1/systemone`、`Bearer`、`{"state": 文字列, "model": "jev-latest", "questions"}`） | 送り先と本文の形は〔Mark の稼働実績〕（分譲指示書）。問いの wire 形式は〔二次のみ〕。価格は〔自己申告〕 | orch/jev.py・orch/decisions.py | Mac で `python3 -m orch.decisions --demo --backend jev` | |
| 5 | GPT-6 Astra のモデル ID（gpt-6-astra）とフォールバック（gpt-5.6-sol）。TOML のエージェントを `codex exec` から名前で呼べるか | モデル ID は〔Mark の稼働実績〕（分譲指示書）。TOML の呼び出しは〔未確認〕 | tools/codex_*.sh、.codex/agents | Mac の Codex で確認 | |
| 6 | Sakana の TRINITY／Conductor／Fugu の記述 | 〔二次のみ〕（Fugu README は一次確認） | README §3・§10（着想のみ） | Phase 3 で論文本文 | |

この台帳は四半期の見直し（ROUTINE §4）で更新する。

