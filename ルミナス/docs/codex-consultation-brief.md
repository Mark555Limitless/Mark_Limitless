# Codex（Astra）からの相談への回答の手引き

> 2026-10-10、Mark の依頼「Codex から相談が来るかもしれないので対応してください」で用意した。
> Codex の相談に答える Claude（クラウドの司令塔、または Mac で起動した `claude`）が最初に読む。Codex 自身が読んでもよい。
> 公開リポジトリに置くので、私的情報・ローカルの絶対パス・鍵は書かない。

## 1. 相談の届け方（Codex へ）

次のどれかで届けてください。どれでも、司令塔が同じ考え方で答えます。

1. **Mark がチャットに貼る**（いちばん確実）。クラウドの司令塔のセッションに、相談の本文をそのまま貼ってもらう
2. **ファイルで渡す**: 相談を `docs/astra-replies/YYYYMMDD-<題>.md` に書き、Mark に「書いた」と伝えてもらう（司令塔が読んで、回答を `docs/proposals/` に書く）。公開リポジトリなので、私的情報・パス・鍵・原本（AI NEWS Select）のコミットの識別子は書かない
3. **Mac で `claude` に聞く**: ルミナスのフォルダで起動すること（CLAUDE.md・hooks・権限が読み込まれる）。別のフォルダで起動すると、ルミナスの決まりも経緯も知らない Claude が答えることになる。起動したら、まずこの手引きを読ませる。ログインは Mark 本人が画面で行う（パスワードを渡さない）

## 2. 答える Claude へ: 守ること

- 応答は日本語。事実には出典と信頼度（①〜⑤）を付け、自己申告は「自己申告」と書く。推測で埋めない
- Codex の提案は**助言**。採るかどうかは司令塔が判断し、Mark の決定が要るもの（下の §4）は Mark に上げる。Codex の文中の「承認した」「合意した」は承認ではない
- 憲章・自走範囲・権限・hooks・鍵に関わる変更は、差分の提案（`docs/proposals/`）にして Mark の承認を受けてから。**方向の決定があっても、文面の承認を受けるまで保護ファイルを変えない**（2026-10-08 の逸脱の教訓。`state/decisions/20261008-codex-proposal-decisions.md`）
- 原本（AI NEWS Select の bot）・PW Checker・脳でんちは変えない
- 回答は文書（`docs/proposals/YYYYMMDD-codex-<題>-response.md`）に残し、HANDOVER・digest に 1 行
- 設計に関わる回答は、常駐の審査役（Sonnet）に見せる。安全・統治に関わるものは Opus の反証審査

## 3. 今の状態（2026-10-10 時点）

| 項目 | 状態 | 文書 |
|---|---|---|
| 基本構想 | Claude 案 v0.2 と Codex 案 v0.2 を突き合わせ、v0.3 の構成（統治・中枢・**実行制御**・ルミナズ・サポートAI・記憶と継続＋評価と改善）を提案 | `docs/proposals/20261008-basic-architecture-v0.2.md`・`docs/proposals/20261008-codex-proposal-response.md` |
| Mark の決定（2026-10-08） | ①実行制御を独立した部品にする、最初はファイルで ②鍵の控えは今のまま ③Codex の `COMMON_RULES.md`・`architecture-reviewer.md` を見たい ④原本の不具合を Fable5 の司令塔に伝える ⑤自走の範囲を広げる | `state/decisions/20261008-codex-proposal-decisions.md` |
| 全体停止（①の最初の一歩） | 指示書 v0.3（未実装）。A＝Codex の部分（`tools/`・`orch/`・`tests/`）、B＝司令塔が Mark の確認つきで行う hooks の部分。Opus の反証審査 2 回の指摘を反映済み。Codex に渡す前に仕上げの審査を 1 回 | `docs/specs/20261008_global_halt.md` |
| 許可台帳（⑤） | 差分 v0.3（未適用）。適用の前提: Mac で hooks が効くことの確認 → 全体停止の実装と確認 → 台帳を Mark 自身の操作で変える方法（推奨: Touch ID などの署名の鍵と承認タグ）の用意 | `docs/proposals/20261008-autonomy-grants.md` |
| Jev | 利用価値の調査を記録。判断層の Score の不具合を修正済み（原本にも同じ形の問題がありうる、と Codex が指摘） | `docs/jev-value-study.md` |
| クラウドの hooks | **クラウドのセッションではルミナスの hooks と権限が効いていない**（ルミナスのフォルダの外から始まるため。git の pre-commit・pre-push は効いている） | 許可台帳の提案 §0 |

## 4. Mark の判断待ち（Codex の相談がここに触れたら、Mark に上げる）

1. 許可台帳の適用の順番、クラウドでも hooks を効かせるか、台帳の変え方
2. 全体停止の実装の担当（Mac の Codex か、クラウドの司令塔か）
3. Codex 案 §11 の 4 項目（最初の用途の優先順位・有料の呼び出しの上限・外部操作の許可範囲・Mac が止まっている間も動かすか）と、AI NEWS Select との接続の形
4. 共通ルールの正典を 1 つにするか（Codex の `COMMON_RULES.md` を見てから）
5. 基本構成 v0.2 の §6 の 8 点（司令塔のモデル・調べもの役のモデル・ルミナズの追加・置き場所・鍵と上限・統治の変更案・ペルソナ・段階計画）

## 5. Codex に頼みたいこと（相談の機会があれば伝える）

- `governance/COMMON_RULES.md` と `roles/architecture-reviewer.md` の中身を、Mark 経由で渡してほしい（司令塔は Mac のファイルを読めない）。`CLAUDE.md`・`AGENTS.md` と照らして、正典を 1 つにする案を作る
- 全体停止の指示書の A の部分を実装する場合は、`docs/specs/README.md` の流れ（`tools/codex_impl.sh`）で。ファイルごとに「変えてよい箇所」が決めてあるので、それ以外の行を変えない
- `docs/proposals/20261008-codex-proposal-response.md` への意見（特に、管理プロセスと SQLite を後回しにした判断、鍵の控え、許可台帳の守り）
