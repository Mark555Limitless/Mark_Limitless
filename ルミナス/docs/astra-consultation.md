# Codex（GPT-6 Astra）への相談・作業分担（構想 v0.1 用）

## 現状（2026-10-07）

- クラウド作業環境（claude.ai のクラウドセッション）から OpenAI のホスト（`api.openai.com` / `auth.openai.com` / `chatgpt.com`）へは
  **環境のネットワークポリシーで接続が拒否された（HTTP 403）**。Codex CLI 自体は導入できたが、Astra を呼べない
- 憲章 I-4 により、ルミナスは鍵を受け取らない・探さない。したがって **Astra の実行は Mark の手元（Mac）で行う**か、
  クラウド環境の設定を変える（§4）必要がある

## 1. Astra に分担させる作業（パケット）

| ID | 内容 | 役割 | 回答の使い先 |
|---|---|---|---|
| WP-1 | 構想 v0.1 の批評 7 問（致命的な穴、Codex 統合、意思統一、エスカレーション、防御、失敗想定、Astra の最適な役割） | astra-architect（read-only） | 構想 v0.2 |
| WP-2 | 評価セット v0（20 課題）の草案 | astra-architect | Phase 1 の評価セット |
| WP-3 | hooks・同期スクリプトのレッドチーム | astra-architect | hooks の修正 |
| WP-4 | Claude ⇄ Codex の受け渡し設計（TOML・指示書テンプレート・差分形式・非対話実行） | astra-architect | `.codex/agents`、指示書テンプレート |

パケット本文は `docs/astra-packets/`。回答は `docs/astra-replies/YYYYMMDD-<ID>.md` に保存する。

## 2. Mac での実行手順

```bash
# 1) 一度だけ: Codex を入れてブラウザでログイン（鍵は貼らない）
npm i -g @openai/codex
codex login

# 2) ルミナスのフォルダで、パケットを渡す（モデルは環境に合わせて）
cd "<Mac の正本フォルダ>"
ASTRA_MODEL=gpt-6-astra scripts/ask-astra.sh docs/astra-packets/WP-1-architecture-review.md
scripts/ask-astra.sh docs/astra-packets/WP-2-eval-set-v0.md
scripts/ask-astra.sh docs/astra-packets/WP-3-hooks-redteam.md
scripts/ask-astra.sh docs/astra-packets/WP-4-codex-integration.md
```

- `ASTRA_MODEL` の既定は `gpt-6-astra`。無効と言われたら Codex が示すモデル名（GPT-6 Sol 等）に変える
- 回答は `docs/astra-replies/` に自動保存される。コミットして司令塔に渡す
- 対話で使う場合は `codex` を起動し「.codex/agents/astra-architect.toml の役割で docs/astra-packets/WP-1-architecture-review.md に答えて」と頼めばよい

## 3. 回答の取り込み規則（司令塔）

- Astra の提案も「主張」として扱い、憲章 I-6 の基準で裏取りしてから採用する
- 憲章の不変条件（I-1〜I-8）に反する提案は、理由を記録して不採用にする
- 採用・保留・不採用を `state/decisions/` に ADR として残し、構想を v0.2 に上げる
- 迷う場合は Mark に 2 案と判断材料を出して決めてもらう

## 4. クラウド環境から直接 Astra を呼べるようにする設定（任意）

1. クラウド環境の設定で、ネットワーク許可に `api.openai.com`・`auth.openai.com`・`chatgpt.com`（Codex）、`api.typesafe.ai`（Jev）を追加する（Gemini の `generativelanguage.googleapis.com` は既に到達可）
2. 同じ設定画面の「Network secrets（API 資格情報）」または環境変数に `OPENAI_API_KEY`・`GEMINI_API_KEY`・`TYPESAFE_API_KEY` を登録する。チャットには貼らない
3. 新しいセッションで `scripts/ask-astra.sh` を実行すると、スクリプト自身が環境変数から Codex にログインする（司令塔は値を扱わず、表示もしない）。残るリスクは `docs/support-ai.md` §1 のとおり

この設定が無い間は §2 の手順で分担する。
