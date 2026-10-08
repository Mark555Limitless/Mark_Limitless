# 参考調査と出典（2026-10-07 時点）

本構想で参照した外部システム・研究と、その出典の信頼度。
（2026-10-08 追記: Mark が環境のネットワークを一時的に Full にし、curl 経由で一次情報を直接読めるようになった。手順は `docs/network-allowlist-request.md`。arXiv 2606.21228 は v1 2026-06-19、v2 2026-06-23）クラウド作業環境では `sakana.ai` / `arxiv.org` / `openai.com` / `huggingface.co` への直接取得が
ネットワークポリシーで遮断されたため、**直接読めたもの**と**検索結果の要約・GitHub README 経由で確認したもの**を区別して記す。

信頼度: ①一次情報 ②査読・第三者評価 ③技術メディア・通信社 ④個人SNS・GitHub Issue ⑤動画・個人ブログ

## 1. Sakana AI のオーケストレーション系

| 対象 | 要点 | 出典 | 信頼度 / 確認方法 |
|---|---|---|---|
| Multi-LLM AB-MCTS / TreeQuest | 推論時に「新しい案を広げる（wider）」か「既存案を深める（deeper）」かを適応的に選び、複数の異種 LLM を混ぜて試行錯誤する。ARC-AGI-2 で単体モデルを上回ったと報告（自己申告）。TreeQuest は Apache-2.0、`generate` 関数と 0〜1 のスコアを与える ask/tell 型 API | https://sakana.ai/ab-mcts/ ・ https://github.com/SakanaAI/treequest ・ arXiv 2503.04412 | ①（README は直接確認。sakana.ai 本文と arXiv は検索要約のみ） |
| TRINITY（ICLR 2026） | 約 0.6B の小型コーディネータ＋約 10K パラメータのヘッドを CMA-ES（進化戦略）で最適化。各ターンで Thinker / Worker / Verifier のいずれかの役割を選んだ LLM に割り当てる。LiveCodeBench 86.2% を主張（自己申告） | arXiv 2512.04695 ・ https://sakana.ai/trinity/ | ②相当（ICLR 採択は検索結果で確認。論文本文は未読・要再確認） |
| Conductor（ICLR 2026） | 7B のコーディネータを RL で学習し、自然言語でワークフロー（手順・担当エージェント・可視範囲＝通信トポロジ）を設計する。LiveCodeBench・GPQA で単体を上回ると主張（自己申告） | arXiv 2512.04388 ・ https://sakana.ai/learning-to-orchestrate/ | ②相当（同上。本文未読） |
| Sakana Fugu（2026-10-08 再調査） | 複数の最先端モデルを内部で使い分ける「1 つのモデルとして使えるマルチエージェント」。2026-06-22 公開。種類は Fugu・Fugu Ultra v2（2026-09-11、入力 $5・出力 $30）・Fugu Max（$2・$6）・Fugu Cyber（申請制）。土台は TRINITY と Conductor（Sakana の説明では ICLR 2026）に商用向けの改良。Ultra v2 のプールに Fable 5・Fable 5.1・GPT-6 Astra は入っていない。問いごとにどのモデルを使ったかは非公開。EU・EEA では使えない。ベンチマークは**すべて Sakana の自己申告**で、他社の数値は各社の公表値。2026-10 時点で第三者評価機関（Artificial Analysis など）の結果は見つからない。公式の定性例（AutoResearch）の差は Fugu 自身のばらつきより小さく、比較相手は一世代前（Gemini 3.1 Pro・Opus 4.8・GPT 5.5）。**技術報告書（2026-06-22 版）の Table 1 を本文で一次確認**: プールの中の最良の単体モデルに対する Fugu Ultra の差は、コーディングで +4〜5 点（SWE-Bench Pro 73.7 対 Opus 4.8 69.2、LiveCodeBench 93.2 対 Gemini 88.5）、知識・推論では小さい（HLE 50.0 対 49.8、GPQA 95.5 対 94.3）、MRCRv2 では負け（93.6 対 GPT-5.5 94.8）。比較相手の数値は「提供元の公表値を使える限り使う」。プール外の Fable 5 は SWE-Bench Pro 80.0・HLE 53.3 で Fugu Ultra を上回る（図 1）。独立検証役（Sonnet、2026-10-08）の判定: 10 主張中 9 件 GO、第三者評価は見つからない。**仕組み（技術報告書 §3 を一次確認）**: 標準の Fugu は TRINITY が土台だが役割は割り当てず、入力ごとに 1 つのモデルを選んで任せる（応答の速さは直接呼んだときと同程度）。Fugu Ultra は Conductor が土台で、強化学習（GRPO）で鍛えた言語モデルが作業の分け方・担当・見せる文脈を自然言語で書き、自分自身も担当にできる。指揮役の大きさは報告書に書かれていない。Qiita の解説（@moritaoy、2026-06-29、Mark が本文を提供、④）は報告書の例と一致するが、「約 0.6B」は TRINITY の論文の値、「Ultra は圧倒的な精度向上」は報告書の表（コーディングで +4〜5 点、知識はほぼ互角）より強い表現、参考に公式でない GitHub（Sakana-AI-labs）を含む | sakana.ai/fugu（Mark が本文を提供）・sakana.ai/fugu-max-release・console.sakana.ai/pricing・github.com/SakanaAI/fugu・arXiv 2606.21228 | ①（公式ページは Mark が貼った本文で確認。クラウドからは sakana.ai を直接読めない）／ベンチは〔自己申告〕 |
| Sakana Namazu | 日本語特化の単一モデル。Moonshot AI のオープンモデル Kimi K2.6（2026-04-20 公開）に社内データで日本語・日本の業務向けの調整。入力 $0.95・出力 $4。Web 検索とコード実行を内蔵。EU・EEA・英国・スイスでは使えない。性能は〔自己申告〕（推論系は元のモデルと同等を維持、日本語系は上回る。FairPoliticsQA 34.10%→56.30%）。導入事例の医師国家試験 96.8%・96.4% は導入企業が自社条件で測った値（画像問題を除く、検索と検証機能を含むシステム全体の成績）。第 119 回は 2025-04 に正答が公開済みで学習に含まれた可能性を否定できない | sakana.ai/namazu（Mark が本文を提供）・sakana.ai/namazu-api | ①／〔自己申告〕 |
| Sakana AI（会社） | 戦略（METI Journal 2026-02-02、伊藤錬氏のインタビュー、Mark が本文を提供）: 「つくり方で米国の後追いはしない」（モデルを大きくする競争は資金力の勝負で米国以外は勝てない）、「使えるものをつくる」（業務の暗黙知を吸い上げる）、「AI は産業とのかけ算」。創業から約 1 年で評価額 10 億ドル超は日本最速（同記事）。日本スタートアップ大賞 2026 で情報通信スタートアップ賞（総務大臣賞）を受賞。大賞（内閣総理大臣賞）は Mujin、応募 317 件・受賞 10 社（総務省 2026-09-25 発表）。伊藤氏の肩書きは資料で揺れる（METI 記事は COO、会社情報は会長、総務省の発表は代表取締役社長）。GitHub の公開リポジトリは 63（Apache-2.0・MIT が中心。スターの多い順に AI-Scientist・AI-Scientist-v2・Continuous Thought Machines・evolutionary-model-merge・ShinkaEvolve。fugu はクライアント用でライセンス表記なし）。資金調達: シード 3,000 万ドル（Lux・Khosla）→ シリーズ A 2024-09 約 300 億円（約 2.14 億ドル、企業価値 15 億ドル。Bloomberg が関係者の話として報道）→ シリーズ B 2025-11 約 200 億円（約 1.35 億ドル、企業価値 26.5 億ドル。TechCrunch が CEO の話として報道。出資者に MUFG・Khosla・NEA・Lux・In-Q-Tel など）。Wikipedia（2026-09-02 最終編集、Mark が本文を提供）はシリーズ A までで、「日経が 2024 年に企業価値を 190 億円と推定」の脚注 [7] は別会社（リージョナルフィッシュ）の記事の題名で、本文の主張を支えていない（記事本文は未確認）。同じ記事の脚注 [1]（Bloomberg、15 億ドル）とも桁が合わない。社員数 20 人も 2024 年の値。2023-07 東京で創業。David Ha（CEO）・伊藤錬（会長）・Llion Jones（CTO、Transformer 論文の共著者）。社名と logo は魚の群れの集合知から。研究・Applied（金融・防衛・インテリジェンス）・Product の 3 部門。金融は三菱UFJ銀行・SMBC グループ・大和証券グループ、防衛は防衛省・防衛装備庁・総務省の事業。研究は Nature（The AI Scientist）・ICLR・NeurIPS・ICML などに採択と同社が掲載。2025-02 の AI CUDA Engineer は評価の抜け穴を突いた結果と判明し謝罪・訂正（TechCrunch ③） | sakana.ai/company-info・sakana.ai/ja（Mark が本文を提供）・TechCrunch 2025-02-21 | ①／③ |
| Sakana AI の防衛分野の講演（防衛装備庁 技術シンポジウム 2025、2025-11-11、佐藤元紀氏） | 主流の「モデル・データ・学習を大きく」以外の道として自然に学ぶ研究を紹介。AI Scientist の枠組み（着想→試行→まとめ→次の手、LLM による採点）を防衛に応用: ①無人機の自律制御（カメラ映像と自然言語のミッションから基盤モデルが move_forward などの命令を出す。機種に依存しない。デモは室内で戦車の模型を小型ドローンが探すもの。通信がない環境向けに端末で動く小型モデル）、②インテリジェンス分析（偽画像の判定、SNS の言説の抽出・分類・急な拡散の検知、AI エージェントによるシミュレーション）。今後はサイバー防衛も。精度などの数値は資料に無い。「完全に AI が書いた論文が査読を通過した世界初」は ICLR 2025 のワークショップ（ICBINB）での採択で、事前に決めた取り下げ・本会議の水準ではないと Sakana 自身が説明、「世界初」には異論あり。この講演の後に、2026-03 の防衛装備庁の委託研究（指揮統制、ドローン上の小型の視覚言語モデル）と 2026-08 の防衛省の受注が続く | mod.go.jp/atla/research/ats2025/pdf_oral_matl/1111_1525_s10.pdf（Mark が PDF を提供。中身の照合は資料の表紙と検索結果で、サイトはこの環境に 403）・sakana.ai/ai-scientist-first-publication | ①（講演資料）／査読通過の件は①と③ |
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
| TypeSafe AI「Jev」 | 文章を生成せず型付き判定を返す「System One」モデル（RLCD で校正を目標に学習）。質問型は Noul（はい/いいえの確率）・Choice（最大 255 択、各確率と確信度）・Score（2〜10 段階、score は段階番号×確率の和）。`POST https://api.typesafe.ai/v1/systemone`。現行 `jev-1.13.0`、入力 10 億トークン $42・出力無料、約 0.1 秒、毎秒 80 回・10 万トークン（変動）、文脈 64k。英語が主で CJK は精度が下がる。顧客データで学習しない（ZDR は法人向け）。既知の弱点 9 項目（計算・日付・注入・選択肢の順番ほか）。事例集 18 本の数値はすべて自己申告。詳細は `docs/jev-value-study.md` | https://docs.typesafe.ai/llms-full.txt （2026-10-08 に Full で全文取得）・ https://docs.typesafe.ai/model-jaggedness/jev-1.13 ・ https://docs.typesafe.ai/models ・ https://docs.typesafe.ai/api | ①（仕様）／性能・速度・価格比は〔自己申告〕。第三者の検証は `docs/jev-value-study.md` §6 |
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
| 4 | Jev の API（`/v1/systemone`、`Bearer`、`{"state": 文字列, "model": "jev-latest", "questions"}`） | 送り先と本文の形は〔Mark の稼働実績〕（分譲指示書）。問いの wire 形式と応答の形は公式の API リファレンスで確認①（2026-10-08）。価格は〔自己申告〕 | orch/jev.py・orch/decisions.py | Mac で `python3 -m orch.decisions --demo --backend jev` | |
| 5 | GPT-6 Astra のモデル ID（gpt-6-astra）とフォールバック（gpt-5.6-sol）。TOML のエージェントを `codex exec` から名前で呼べるか | モデル ID は〔Mark の稼働実績〕（分譲指示書）。TOML の呼び出しは〔未確認〕 | tools/codex_*.sh、.codex/agents | Mac の Codex で確認 | |
| 6 | Sakana の TRINITY／Conductor／Fugu の記述 | 〔二次のみ〕（Fugu README は一次確認） | README §3・§10（着想のみ） | Phase 3 で論文本文 | |

この台帳は四半期の見直し（ROUTINE §4）で更新する。

