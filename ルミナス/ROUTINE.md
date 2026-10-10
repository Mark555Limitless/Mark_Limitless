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
| 毎日 | digest 1 件、HANDOVER.md に節を追加、Obsidian 同期、外部AIの支出確認（`.venv/bin/python -m orch.usage --days 1`） | 司令塔（hook が催促） |
| 毎週 | digest 7 件を読み返し、繰り返し出る問題を ADR か ROUTINE 改訂にする | 司令塔＋レビュー役 |
| 毎月 | `state/escalations.log` の監査（妥当性・コスト）。基準を CLAUDE.md に反映 | レビュー役（Sonnet）→ 必要時 Opus |
| 四半期 | 憲章の見直し提案（変更は Mark 承認） | 司令塔 → Mark |

## 5. hooks の対応表

| イベント | スクリプト | 役割 |
|---|---|---|
| SessionStart (startup/resume/clear/compact/fork) | `.claude/hooks/restore-charter.sh` | 憲章 §1-2-4・VIRTUAL_MARK §3・ROUTINE §1・HANDOVER.md の最新の節・最新 digest・Obsidian「最新」・最終プロンプト冒頭を注入（過去の記録は「データ」と明示）。保護ファイルの未承認差分を警告。開始時刻を `state/.sessions/<id>.start` に記録 |
| PreToolUse（すべての道具 `*`） | `.claude/hooks/halt-guard.sh` | 全体停止の印（`data/.luminous_halt`）があれば、読むだけの道具（Read・Grep・Glob）と TaskStop・AskUserQuestion 以外を止める。印は `bash tools/luminous_halt.sh on 理由` で誰でも付けられ、消すのは Mark が端末で `off`。印が無くても `true luminous-hook-canary` だけは常に断る（hooks が効いているかの確認用）。**終了の関門を外す `LUMINOUS_STOP_GATE=off` とは別物**（あちらは記録の催促を外すだけで、作業は止めない）。仕様: `docs/specs/20261008_global_halt.md` |
| PreToolUse (Edit/Write) | `.claude/hooks/codex-lock-guard.sh` | Codex の実行中（`data/codex_runs/.lock` の持ち主が生きている）は、このフォルダ内の編集を止める（実行中の編集は範囲検査で違反になる） |
| PreToolUse (Bash) | `.claude/hooks/guard-protected.sh` | 保護ファイルへの Bash 書き込み、鍵ファイルの Bash 読み取り、`--no-verify`・`core.hooksPath` の変更を止める |
| PreToolUse (Bash) | `.claude/hooks/guard-secrets.sh` | `git commit` / `git push` を含むコマンドの前に、作業ツリー・ステージ・未追跡ファイルを `scripts/secret-scan.sh` で検査してブロック（早期警告） |
| git pre-commit / pre-push | `.githooks/pre-commit`, `.githooks/pre-push` | 実際にコミット・送出される差分を検査（本命）。`scripts/setup.sh` で `core.hooksPath` を設定 |
| PostToolUse (Edit/Write) | `.claude/hooks/mark-edited.sh` | このセッションで編集があったことを記録（`LUMINOUS_GATE_MODE=edits` 用） |
| PostModelSwitch | `.claude/hooks/log-model-switch.sh` | モデル切替を `state/escalations.log` に機械記入。Codex の実行中は Codex が書けない置き場（`~/.cache/luminous-codex/escalations.pending`）に保留し、次の切替か SessionEnd で機械的な書式の行だけを移す。モデル名は英数字と記号の一部に限る |
| Stop | `.claude/hooks/stop-gate.sh` | 今日（Asia/Tokyo）の digest・HANDOVER.md・Obsidian ハブが、このセッションの開始後に更新されていなければ終了をブロック。無人実行（`FABLE5_HEADLESS=1`）では止めない。全体停止中も止めない（閉じ込めない） |
| SessionStart（同上の中） | `.venv/bin/python -m orch.health --quiet`（.venv が無ければ動く python3） | 外部AI（Codex・Gemini・Jev）の点検を 3 行で表示。結果が出なければ `bash scripts/setup.sh` を促す 1 行を出す。無人実行では出さない |
| SessionEnd | `.claude/hooks/session-end.sh`（timeout 30 秒） | Obsidian 同期・docx 再生成（Codex の実行中と全体停止中は docx 再生成を見送る）。失敗は `state/.session-end.log` に残し、次回 SessionStart で警告 |
| permissions | `.claude/settings.json` | 保護ファイル（最終プロンプト・hooks が呼ぶ scripts・package*.json・.mcp.json を含む）の編集、`git push`、MCP の書き込み・送信・共有系は ask。`printenv`/`env`、`.env`・`settings.local.json`・鍵ファイルの読取は deny |

- 環境変数（hooks・scripts・tools が読むもの。鍵はここに書かない）:
  - `LUMINOUS_OBSIDIAN_DIR` — Obsidian vault の絶対パス（SessionEnd の同期先。未設定なら同期しない）
  - `LUMINOUS_OBSIDIAN_FORCE` — `1` で `.obsidian` の無い場所にも同期する（確信があるときだけ一時的に）
  - `LUMINOUS_TZ` — digest の日付の時間帯（既定 Asia/Tokyo）
  - `LUMINOUS_GATE_MODE` — Stop ゲートの範囲（always｜edits。既定 always）
  - `LUMINOUS_STOP_GATE` — Stop ゲート（on｜off。off は今日の digest に理由が要る。下記）
  - `LUMINOUS_SAFE_DIR` — Codex が書けない置き場（既定 `~/.cache/luminous-codex`）。通常は設定しない。設定するなら端末と Claude Code（`settings.local.json`）の両方に同じ絶対パスで書く（全体停止の記録を同じ場所で突き合わせるため）
  - `XDG_CACHE_HOME` — `LUMINOUS_SAFE_DIR` が無いときの置き場の基準（`$XDG_CACHE_HOME/luminous-codex`）。端末と Claude Code で同じにする
  - `FABLE5_HEADLESS` — `1` は無人実行の印（Stop ゲートと外部AIの点検を出さない）。無人の `claude -p` のコマンドにだけ付け、`settings.local.json` や `.zshrc` には書かない
  - `CODEX_BIN` — Codex 本体の絶対パス（既定は ChatGPT アプリ同梱 → `CODEX_OLD_BIN` → PATH の順に探す）。`.env` にも書ける
  - `CODEX_MODEL` — Codex のモデル（空なら `~/.codex/config.toml` の既定）。`.env` にも書ける
  - `CODEX_FALLBACK_MODEL` — 失敗・無変更のとき 1 回だけやり直すモデル（既定 gpt-5.6-sol。空ならやり直さない）。`.env` にも書ける
  - `CODEX_DISABLE_FEATURES` — Codex に `--disable` で渡す機能名（既定 memories multi_agent）
  - `ORCH_CODEX` — `0` で Codex を止める（`data/.codex_disabled` と同じ。`docs/support-ai.md` の停止スイッチ）
  - `LUMINOUS_SETTLE_S` — Codex の終了後に検査まで待つ秒数（既定 2）
  - `LUMINOUS_PRIVATE_DIR` — 鍵の控えの置き場（既定はこのフォルダの隣の `ルミナス_非公開/`。git の管理外であること）
- 書く場所: Mac では `.claude/settings.local.json` の `env`（例: `.claude/settings.local.json.example`）に書く。デスクトップアプリから開いたセッションの hooks には `.zshrc` の `export` が届かないことがあるので、シェルだけに書かない。`env` の値は `~` や `$HOME` を使わず絶対パスで書く。**クラウドセッションは `settings.local.json` を読まない**ので、環境側の環境変数に設定する
- ゲートを一時的に外す必要があるとき（緊急時）は `LUMINOUS_STOP_GATE=off` を設定し、**今日の digest に「STOP_GATE=off: 理由」を書く**（書かないと解除されない）
- jq も動く python3 も無いとき（Mac で Xcode コマンドラインツールが未導入だと `/usr/bin/python3` は「有るが動かない」）: hooks は止める側に倒れる。`guard-secrets.sh` はすべての `git commit`・`git push` を止め、`guard-protected.sh` は広く止める。直し方は `xcode-select --install` か jq の導入
- SessionStart で「git フック（pre-commit / pre-push）が効いていません」と出たら、`bash scripts/setup.sh` を実行する（鍵の検査の本命が未設定）
- 再現テスト: `scripts/test-hooks.sh`（使い捨てディレクトリだけに書き込む）

## 6. ファイルの置き場（Mac 正本と写し）

- 正本: Mac の正本フォルダ（このフォルダで `claude` を起動する。初回に `scripts/setup.sh`）
- 写し: GitHub `Mark555Limitless/Mark_Limitless` の `ルミナス/`。コミットで同期する
