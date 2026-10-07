# HANDOVER — 引き継ぎ書（新しい節を先頭に足す）

> 各セッションの終わりに、この下に新しい節を足す（Stop hook が未更新なら終了を止める）。
> 書くこと: 状態・やったこと・決定・未解決・次の一手。Mark の指示と決定は処理した時点で書く。鍵・ローカルの絶対パスは書かない。

## 2026-10-08 分譲指示書の取り込み（司令塔: Claude Opus 5.5）
- 状態: ルミナス基本構想 v0.1。AI NEWS Select の司令塔が書いた「分譲指示書 — Codex・Gemini・Jev を常に使える仕組み」（2026-10-08）を Mark から受け取り、段階1〜4 の部品を仕様から再構築した（原本の bot はクラウドから読めないため、コピーではなく再実装）
- やったこと:
  - 段階1 Codex: `tools/codex_impl.sh`・`tools/scope_check.py`・`tools/codex_opinion.sh`・`docs/review.md`・試験用の指示書 2 本
  - 段階2 Gemini: `orch/gemini.py`（API 直接・上限・記録・点検・停止スイッチ）、`orch/usage.py`（全ベンダー共通台帳）、`tools/set_env_key.sh`、`.env.example`
  - 段階3 Jev: `orch/jev.py`・`orch/decisions.py`（jev → claude -p（Haiku→Sonnet）→ 既定値）
  - 段階4: `orch/health.py` を SessionStart で表示（無人実行 `FABLE5_HEADLESS=1` では出さない）
  - テスト 58 件（外部 API はすべてモック、偽の codex でラッパーの終了コードを確認）
  - 旧ラッパー（Gemini CLI 版・jev_gate）は指示書の方式に置き換えて削除。引き継ぎは本ファイル（旧 state/latest.md）に一本化
- 決定: 分譲指示書の原本はローカルの絶対パスを含むため公開リポジトリに入れない（Mac の非公開フォルダで保管）。鍵は `.env`（600・git 管理外）だけ、入力は Mark が `tools/set_env_key.sh` で行う
- 未解決（Mark の判断）:
  - 分譲指示書 §3.3: 鍵をルミナス専用に新規発行するか（推奨）／上限（推奨: Gemini 1日 $1、Jev 1日60回・月 $1、Codex の1日の実行回数の目安）／ルミナスを公開リポジトリに置き続けるか
  - README §11 の各項目（統治の強化提案、各社条件の確認表、ペルソナ など）
- 次の一手（Mac で）: `scripts/setup.sh`（venv・git フック）→ 段階1 の試験1〜3 → 鍵を入れて段階2・3 の確認（`python3 -m orch.gemini check`、`python3 -m orch.decisions --check`）

## 2026-10-07 基本構想 v0.1（司令塔: Claude Fable 5.1 → Opus 5.5）
- 状態: 構想・憲章・仮想Mark・ROUTINE・hooks・レビュー役・最終プロンプトを作成。Sonnet の審査 24 件と Opus の上位審査（実装分）を反映
- 決定: 「身内を欺く」「数値を毎回盛る」は不採用。名称は継承し意味を現実化。統治ルールの変更案は `docs/proposals/20261007-governance-v0.2.md`（Mark 承認待ち・未適用）
- 未解決: Codex（Astra）への作業パケット WP-1〜4 は Mac で `tools/codex_opinion.sh` を使って実行する
