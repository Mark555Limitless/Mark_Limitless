# ROUTINE.md — ルミナスの恒久ルーチン v0.1

> 「毎回読む・毎回書く」を定義する文書。hooks が自動化できる部分は自動化し、残りは司令塔が手で行う。
> AI NEWS Select と同じ考え方: 開始時に **CLAUDE.md → CHARTER → ROUTINE → state/latest.md → 直近 digest** を読み、
> 終了時に **digest → state/latest.md → Obsidian → 最終プロンプト(.docx)** を書く。

## 0. 毎回読むファイル（セッション開始時・圧縮後）

| 順 | ファイル | 役割 | 自動化 |
|---|---|---|---|
| 1 | `CLAUDE.md` | 共通ルール | Claude Code が自動で読む |
| 2 | `CHARTER.md` | 始源の目的・不変条件 | SessionStart hook が §1-2 を注入 |
| 3 | `ROUTINE.md`（本書） | 今回やるべき手順 | SessionStart hook が §1 のチェックリストを注入 |
| 4 | `state/latest.md` | 直近の進行状況・未解決 | SessionStart hook が先頭を注入 |
| 5 | `digest/` の最新 1 件 | 前回の要約・判断・数値 | SessionStart hook が先頭を注入 |
| 6 | `prompts/ルミナス_最終プロンプト.md` | 自分の運用プロンプト（正本） | 変更があれば読み直す（docx は配布用） |

## 1. セッション開始時の手順（司令塔）

- [ ] 憲章の要約を読み、直近の判断に憲章違反がないか 1 分で自己点検する
- [ ] `state/latest.md` の「未解決」から再開点を決める
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
| 1 | `digest/YYYY-MM-DD.md` | その日の要約（やったこと・判断・数値・未解決・次の一手）。同日 2 回目以降は追記 | **Stop hook が未更新なら停止をブロック**して書かせる |
| 2 | `state/latest.md` | 直近状態を全面更新 | 同上 |
| 3 | `state/escalations.log` | モデル切替があれば追記 | 手動 |
| 4 | `obsidian/ルミナス.md` と `obsidian/` 配下 | ハブノートの「最新」節を更新。digest をリンク | SessionEnd hook が `scripts/sync-obsidian.sh` で vault へ同期 |
| 5 | `prompts/ルミナス_最終プロンプト.md` → `☆ルミナス_最終プロンプト.docx` | 運用ルールが変わったときだけ更新 | SessionEnd hook が md の方が新しければ docx を再生成 |
| 6 | git | 作業ブランチにコミット（push は自走範囲内） | 手動（`guard-secrets.sh` が鍵の混入を止める） |

## 4. 定期ルーチン

| 周期 | 内容 | 担当 |
|---|---|---|
| 毎日 | digest 1 件、latest.md 更新、Obsidian 同期 | 司令塔（hook が催促） |
| 毎週 | digest 7 件を読み返し、繰り返し出る問題を ADR か ROUTINE 改訂にする | 司令塔＋レビュー役 |
| 毎月 | `state/escalations.log` の監査（妥当性・コスト）。基準を CLAUDE.md に反映 | レビュー役（Sonnet）→ 必要時 Opus |
| 四半期 | 憲章の見直し提案（変更は Mark 承認） | 司令塔 → Mark |

## 5. hooks の対応表

| イベント | スクリプト | 役割 |
|---|---|---|
| SessionStart (startup/resume/clear/compact) | `.claude/hooks/restore-charter.sh` | 憲章・ROUTINE §1・latest.md・最新 digest を注入。開始時刻を `state/.session-start` に記録 |
| PreToolUse (Bash) | `.claude/hooks/guard-secrets.sh` | `git commit` 時に鍵らしき文字列を検知してブロック |
| Stop | `.claude/hooks/stop-gate.sh` | 今日の digest と latest.md が開始後に更新されていなければ停止をブロックし、理由を返す |
| SessionEnd | `.claude/hooks/session-end.sh` | Obsidian 同期・docx 再生成（無理なら黙ってスキップし、記録だけ残す） |

ゲートを一時的に外す必要があるとき（緊急時）は `.claude/settings.local.json` の `env` に `LUMINOUS_STOP_GATE=off` を置く。使ったら digest に理由を書く。

## 6. ファイルの置き場（Mac 正本と写し）

- 正本: Mac の `Claude提供用/ルミナス`（Obsidian vault の場所は `.claude/settings.local.json` の `LUMINOUS_OBSIDIAN_DIR` に設定。例は `.claude/settings.local.json.example`）
- 写し: GitHub `Mark555Limitless/Mark_Limitless` の `ルミナス/`。コミットで同期する
