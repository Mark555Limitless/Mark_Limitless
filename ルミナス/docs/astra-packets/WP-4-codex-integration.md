あなたは「Astra」。Codex 側の統合アーキテクトとして、**Claude 司令塔 ⇄ Codex 実装役の受け渡し**を設計してください。
先に AGENTS.md → CHARTER.md → README.md §3.3・§5 → .codex/agents/*.toml を読むこと（変更はしない）。

答えてほしいこと:
1. .codex/agents/astra-architect.toml と astra-implementer.toml の不足・過剰（フィールド、sandbox_mode、model/model_reasoning_effort の置き方、config.toml [agents] との関係）
2. 指示書（司令塔 → 実装役）の最小テンプレート: 目的／ALLOWED／禁止／検証コマンド／受け入れ基準／返却形式。nou-denchi で使っている `<!-- ALLOWED -->` 方式を前提に、壊れやすい点を直す
3. 差分の返し方: パッチ（git diff）か、ファイル全体か、変更点の説明か。司令塔がレビュー→コミットする前提で最も事故が少ない形式と、その理由
4. 非対話実行（codex exec）での失敗パターン（承認待ちで止まる、サンドボックスで書けない、モデル名無効）と、tools/codex_impl.sh・tools/codex_opinion.sh に足りない対策
5. GPT-6 Astra と GPT-6 Sol の使い分け（費用対効果）。第二意見は Astra、実装は Sol、など具体的な割り当て案と、その根拠（自己申告の数値は自己申告と明記）

出力: Markdown。TOML や指示書のテンプレートはコードブロックで。最後に「採用推奨／要検討／不採用推奨」。
