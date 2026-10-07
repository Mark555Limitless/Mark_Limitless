# ROUTINE.md — ルミナスの恒久ルーチン v0.1

> 「毎回読む・毎回書く」を定義する文書。hooks が自動化できる部分は自動化し、残りは司令塔が手で行う。
> AI NEWS Select と同じ考え方: 開始時に **CLAUDE.md → CHARTER → ROUTINE → HANDOVER.md → 直近 digest → 外部AIの点検** を読み、
> 終了時に **HANDOVER.md（先頭に新しい節）→ digest → Obsidian → 最終プロンプト(.docx)** を書く。

## 0. 毎回読むファイル（セッション開始時・圧縮後）

| 順 | ファイル | 役割 | 自動化 |
|---|---|---|---|
| 1 | `CLAUDE.md` | 共通ルール | Claude Code が自動で読む |
| 2 | `CHARTER.md` | 始源の目的・不変条件 | SessionStart hook が §1-2 を注入 |
| 3 | `ROUTINE.md`（本書） | 今回やるべき手順 | SessionStart hook が §1 のチェックリストを注入 |
| 4 | `HANDOVER.md` | 引き継ぎ（新しい節が先頭） | SessionStart hook が最新の節を注入 |
| 5 | `digest/` の最新 1 件 | 前回の要約・判断・数値 | SessionStart hook が最後の見出しブロックを注入 |
| 6 | `obsidian/ルミナス.md` | Obsidian 側の要約（「最新」節） | SessionStart hook が「最新」節を注入 |
| 7 | `prompts/ルミナス_最終プロンプト.md` | 自分の運用プロンプト（正本） | SessionStart hook が冒頭を注入。docx は配布用で毎回再生成 |

## 1. セッション開始時の手順（司令塔）

- [ ] 憲章の要約を読み、直近の判断に憲章違反がないか 1 分で自己点検する
- [ ] `HANDOVER.md` の最新の節の「未解決」から再開点を決める。外部AIの点検（orch.health の 3 行）に異常がないか見る
- [ ] 作業の重要度から探索予算（低・中・高）を宣言する（`VIRTUAL_MARK.md` §4）
- [ ] 使うモデルを宣言する（最安十分。切り替えたら `state/escalations.log` に 1 行）
- [ ] 「復元完了」を 1 行で報告してから本題に入る

## 2. 作業中の手順

- 文書・設定・コードを作ったら `luminous-reviewer`（Sonnet）に審査させる。重大な論点が残れば Opus へ上げる
- 事実を書くときは出典と信頼度（①〜⑤）を添える。自己申告ベンチは「自己申告」と書く
- 判断を下したら `state/decisions/YYYYMMDD-題.md`（ADR）に 5 行で残す（背景・選択肢・決定・理由・影響）
- 不可逆な操作の前は止まって Mark に確認する

## 3. セッション終了時の手順（毎回書くファイル）

| 順 | ファイル | 書くこと | 自動化 |
|---|---|---|---|
| 1 | `digest/YYYY-MM-DD.md` | その日の要約（やったこと・判断・数値・未解決・次の一手）。同日 2 回目以降は追記。日付は日本時間 | **Stop hook が未更新なら終了をブロック**して書かせる |
| 2 | `HANDOVER.md` | 先頭に新しい節（状態・やったこと・決定・未解決・次の一手） | 同上 |
| 3 | `state/escalations.log` | モデル切替があれば追記 | 手動 |
| 4 | `obsidian/ルミナス.md` | ハブノートの「最新」節を更新。digest をリンク | **Stop hook が未更新なら停止をブロック**。SessionEnd hook が `scripts/sync-obsidian.sh` で vault へ同期（`LUMINOUS_OBSIDIAN_DIR` 設定時） |
| 5 | `prompts/ルミナス_最終プロンプト.md` → `☆ルミナス_最終プロンプト.docx` | 運用ルールが変わったときだけ md を更新 | SessionEnd hook が docx を毎回再生成 |
| 6 | git | 作業ブランチにコミット（push は自走範囲内） | 手動（`guard-secrets.sh` が鍵の混入を止める） |

## 4. 定期ルーチン

| 周期 | 内容 | 担当 |
|---|---|---|
| 毎日 | digest 1 件、HANDOVER.md に節を追加、Obsidian 同期、外部AIの支出確認（`python3 -m orch.usage --days 1`） | 司令塔（hook が催促） |
| 毎週 | digest 7 件を読み返し、繰り返し出る問題を ADR か ROUTINE 改訂にする | 司令塔＋レビュー役 |
| 毎月 | `state/escalations.log` の監査（妥当性・コスト）。基準を CLAUDE.md に反映 | レビュー役（Sonnet）→ 必要時 Opus |
| 四半期 | 憲章の見直し提案（変更は Mark 承認） | 司令塔 → Mark |

## 5. hooks の対応表

| イベント | スクリプト | 役割 |
|---|---|---|
| SessionStart (startup/resume/clear/compact/fork) | `.claude/hooks/restore-charter.sh` | 憲章 §1-2-4・VIRTUAL_MARK §3・ROUTINE §1・HANDOVER.md の最新の節・最新 digest・Obsidian「最新」・最終プロンプト冒頭を注入（過去の記録は「データ」と明示）。保護ファイルの未承認差分を警告。開始時刻を `state/.sessions/<id>.start` に記録 |
| PreToolUse (Bash) | `.claude/hooks/guard-protected.sh` | 保護ファイルへの Bash 書き込み、鍵ファイルの Bash 読み取り、`--no-verify`・`core.hooksPath` の変更を止める |
| PreToolUse (Bash) | `.claude/hooks/guard-secrets.sh` | `git commit` / `git push` を含むコマンドの前に、作業ツリー・ステージ・未追跡ファイルを `scripts/secret-scan.sh` で検査してブロック（早期警告） |
| git pre-commit / pre-push | `.githooks/pre-commit`, `.githooks/pre-push` | 実際にコミット・送出される差分を検査（本命）。`scripts/setup.sh` で `core.hooksPath` を設定 |
| PostToolUse (Edit/Write) | `.claude/hooks/mark-edited.sh` | このセッションで編集があったことを記録（`LUMINOUS_GATE_MODE=edits` 用） |
| PostModelSwitch | `.claude/hooks/log-model-switch.sh` | モデル切替を `state/escalations.log` に機械記入 |
| Stop | `.claude/hooks/stop-gate.sh` | 今日（Asia/Tokyo）の digest・HANDOVER.md・Obsidian ハブが、このセッションの開始後に更新されていなければ終了をブロック。無人実行（`FABLE5_HEADLESS=1`）では止めない |
| SessionStart（同上の中） | `python3 -m orch.health --quiet` | 外部AI（Codex・Gemini・Jev）の点検を 3 行で表示。無人実行では出さない |
| SessionEnd | `.claude/hooks/session-end.sh`（timeout 30 秒） | Obsidian 同期・docx 再生成。失敗は `state/.session-end.log` に残し、次回 SessionStart で警告 |
| permissions | `.claude/settings.json` | 保護ファイル（最終プロンプト・hooks が呼ぶ scripts・package*.json・.mcp.json を含む）の編集、`git push`、MCP の書き込み・送信・共有系は ask。`printenv`/`env`、`.env`・`settings.local.json`・鍵ファイルの読取は deny |

- 環境変数: `LUMINOUS_OBSIDIAN_DIR`（vault の絶対パス）、`LUMINOUS_TZ`（既定 Asia/Tokyo）、`LUMINOUS_GATE_MODE`（always｜edits）、`LUMINOUS_STOP_GATE`（on｜off）。Mac では `.claude/settings.local.json` の `env`（例: `.claude/settings.local.json.example`）かシェルで設定。**クラウドセッションは `settings.local.json` を読まない**ので、環境側の環境変数に設定する。鍵はここに書かない
- ゲートを一時的に外す必要があるとき（緊急時）は `LUMINOUS_STOP_GATE=off` を設定し、**今日の digest に「STOP_GATE=off: 理由」を書く**（書かないと解除されない）
- 再現テスト: `scripts/test-hooks.sh`（使い捨てディレクトリだけに書き込む）

## 6. ファイルの置き場（Mac 正本と写し）

- 正本: Mac の正本フォルダ（このフォルダで `claude` を起動する。初回に `scripts/setup.sh`）
- 写し: GitHub `Mark555Limitless/Mark_Limitless` の `ルミナス/`。コミットで同期する
