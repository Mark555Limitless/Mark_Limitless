# 直近セッション要約

- 更新日: 2026-10-07
- 進行中: ルミナス基本構想 v0.1（`ルミナス/` フォルダ）。レビュー役（Sonnet）の審査結果を反映中
- 未解決:
  - Codex（GPT-6 Astra）への作業分担（WP-1〜4）は、クラウド環境から OpenAI ホストが遮断されているため Mark の手元で実行する（`docs/astra-consultation.md` §2）。クラウドで動かすなら同書 §4 の設定
  - Gemini・Jev の鍵と疎通（`scripts/ask-gemini.sh`・`scripts/jev_gate.py`）。Jev は直接 API か OpenRouter 経由かを確認
  - 「Fable5.1 AI NEWS Select」の定義ファイル（CLAUDE.md / ROUTINE.md / digest 等）の所在。見つかれば `docs/ai-news-select-ref/` に置き用語を統一
  - ペルソナ（探偵アニ文体）の既定、サポートAI の範囲（Grok）、費用上限、知識の置き場は Mark の判断待ち（README §11）
- 直近の判断: 「身内を欺く」「数値を毎回盛る」は憲章で不採用。名称（ルミナス/ルミナズ/探偵アニ/仮想Mark）は継承し意味を現実化。サポートAI は Codex・Gemini・Jev の三者を標準に
- 次の一手: レビュー指摘の反映 → コミット・push（`claude/dreamy-euler-k2f60s`）→ Mac の `Claude提供用/ルミナス` に写しを配置 → Astra 回答と Mark の決定を取り込み v0.2 → Phase 1（役割別エージェント・鍵設定・評価セット v0）
