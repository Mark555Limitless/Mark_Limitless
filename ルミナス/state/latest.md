# 直近セッション要約

- 更新日: 2026-10-07
- 進行中: ルミナス基本構想 v0.1（`ルミナス/` フォルダ）。Sonnet 審査 24 件と Opus 上位審査（実装分）は反映済み。統治の変更案は `docs/proposals/20261007-governance-v0.2.md`（Mark 承認待ち・未適用）
- 未解決:
  - Codex（GPT-6 Astra）への作業分担（WP-1〜4）は、クラウド環境から OpenAI ホストが遮断されているため Mark の手元で実行する（`docs/astra-consultation.md` §2）。クラウドで動かすなら同書 §4 の設定
  - Gemini・Jev の鍵と疎通（`scripts/ask-gemini.sh`・`scripts/jev_gate.py`）。Jev は直接 API か OpenRouter 経由かを確認
  - 「Fable5.1 AI NEWS Select」の定義ファイル（CLAUDE.md / ROUTINE.md / digest 等）の所在。見つかれば `docs/ai-news-select-ref/` に置き用語を統一
  - Mark の判断待ち（README §11 の 10 項目）: ペルソナ既定、Grok の範囲、費用上限の意味、知識の置き場、正本の運用、最終プロンプトの正本、公開情報の掲載、憲章と Mark の指示の衝突時の扱い など
  - `state/jev/`（Jev の判定ログ）は git 管理外。監査ログとしての保管先を決める
- 直近の判断: 鍵の混入は git pre-commit / pre-push が本命（`scripts/setup.sh` で有効化）。保護ファイルの編集と push は permissions で確認。Jev は実験扱い。「身内を欺く」「数値を毎回盛る」は憲章で不採用。名称（ルミナス/ルミナズ/探偵アニ/仮想Mark）は継承し意味を現実化。サポートAI は Codex・Gemini・Jev の三者を標準に
- 次の一手: Mark の判断（README §11、特に統治提案と確認表）→ Mac の正本フォルダで `scripts/setup.sh` → 検証台帳の優先 1〜3 を実地確認→ Mac の正本フォルダに写しを配置 → Astra 回答と Mark の決定を取り込み v0.2 → Phase 1（役割別エージェント・鍵設定・評価セット v0）
