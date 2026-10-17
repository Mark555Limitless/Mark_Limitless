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
| 7 | `prompts/ルミナス_最終プロンプト.md` | 自分の運用プロンプト（正本） | SessionStart hook が冒頭を注入。docx は配布用で、md が変わったときだけ再生成（`LUMINOUS_PRIVATE_DIR` があれば非公開フォルダにも写す） |

## 1. セッション開始時の手順（司令塔）

- [ ] 憲章の要約を読み、直近の判断に憲章違反がないか 1 分で自己点検する
- [ ] `HANDOVER.md` の最新の節の「未解決」から再開点を決める。外部AIの点検（orch.health の 3 行）に異常がないか見る
- [ ] 作業の重要度から探索予算（低・中・高）を宣言する（`VIRTUAL_MARK.md` §4）
- [ ] 使うモデルを宣言する（最安十分。切り替えたら `state/escalations.log` に 1 行）
- [ ] 「復元完了」を 1 行で報告してから本題に入る

## 2. 作業中の手順

- **[伝] Mark への伝え方（Mark の指示 2026-10-11・2026-10-15・2026-10-17 再指示・恒久）**: 過程の説明は書かない（実況・手順の説明・やり直しの経緯なし。途中で書くのは判断・確認が要るとき、重大な問題、状況の一言を求められたときだけで、その一言は「〜中」と何の作業中かを日本語で 1 文だけ＝待っている理由・依存関係・次の手順・道具の名前は書かない）。完了の報告にも、差し戻し・やり直し・回数・使った道具・調べた順・問題のなかった確認・試験の件数・審査の合否・コミット番号は書かない（Mark の判断や操作に関わるときだけ例外）。
- **壁打ち（相談）と実装を分ける（Mark の承認 2026-10-17・ADR `state/decisions/20261016-consult-vs-implement.md`）**: 外部 AI との往復の最中は、回答と記録（壁打ち記録・ADR・引き継ぎ書）だけを書く。指示書の作成・コードの変更・Codex の起動・コミットは往復が終わってから Mark の指示で行う。同じ会話を 2 つの窓で動かさない（気づいたら止まって Mark に確かめる）。結果・Mark の判断や操作が要ること・知らないと困ること（失敗・未完了・誤り・費用・外から見える影響）だけを、省略せず具体的に書く。正本は `CLAUDE.md`「Mark への伝え方」。hooks（SessionStart の先頭・UserPromptSubmit）が毎回注入する
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
| 5 | `prompts/ルミナス_最終プロンプト.md` → `☆ルミナス_最終プロンプト.docx` | 運用ルールが変わったときだけ md を更新 | SessionEnd hook が、md が変わったときだけ docx を再生成（`LUMINOUS_PRIVATE_DIR` があれば非公開フォルダにも写す） |
| 6 | git | 書く前に `git pull`、コミットしたらすぐ作業ブランチへ push（クラウドと Mac の衝突を減らす。push は自走範囲内） | 手動（`guard-secrets.sh` が鍵の混入を止める） |

## 4. 定期ルーチン

| 周期 | 内容 | 担当 |
|---|---|---|
| 毎日 | digest 1 件、HANDOVER.md に節を追加、Obsidian 同期、外部AIの支出確認（`.venv/bin/python -m orch.usage --days 1`） | 司令塔（hook が催促） |
| 毎週 | digest 7 件を読み返し、繰り返し出る問題を ADR か ROUTINE 改訂にする | 司令塔＋レビュー役 |
| 毎週（週次の AI 調査のたび） | 現行手順の記録（P0）を `state/p0/YYYY-Www-cycleN.md` に書く（様式は `docs/baseline/weekly-report-template.md` の下半分。工程ごとの時間・呼び出しとトークン・結果・見落とし候補・人の判断。Mark の関与は、会話で分かる範囲〔指示・承認の回数と、承認待ちの時間〕を司令塔が記録し、Mark に記入を求めない）。Mark の指示 2026-10-15 | 司令塔 |
| 毎月 | `state/escalations.log` の監査（妥当性・コスト）。基準を CLAUDE.md に反映 | レビュー役（Sonnet）→ 必要時 Opus |
| 四半期 | 憲章の見直し提案（変更は Mark 承認） | 司令塔 → Mark |

## 5. hooks の対応表

| イベント | スクリプト | 役割 |
|---|---|---|
| SessionStart (startup/resume/clear/compact/fork) | `.claude/hooks/restore-charter.sh` | 憲章 §1-2-4・VIRTUAL_MARK §3・ROUTINE §1・HANDOVER.md の最新の節・最新 digest・Obsidian「最新」・最終プロンプト冒頭を注入（過去の記録は「データ」と明示）。保護ファイルの未承認差分を警告。開始時刻を `state/.sessions/<id>.start` に記録 |
| UserPromptSubmit | `.claude/hooks/tell-rule.sh` | Mark への伝え方 [伝]（過程の説明は書かず、伝える必要がある部分だけを詳しく）を Mark の発言ごとに注入する。SessionStart でも restore-charter.sh が先頭で同じ文を出す |
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
  - `LUMINOUS_PRIVATE_DIR` — 鍵の控えの置き場（既定はこのフォルダの隣の `ルミナス_非公開/`。git の管理外であること）。SessionEnd が最終プロンプトの docx もここへ写す（絶対パスで書く。`~` は不可。設定があるのに写せなければ「失敗」と記録し、次の SessionStart が警告する）
- 書く場所: Mac では `.claude/settings.local.json` の `env`（例: `.claude/settings.local.json.example`）に書く。デスクトップアプリから開いたセッションの hooks には `.zshrc` の `export` が届かないことがあるので、シェルだけに書かない。`env` の値は `~` や `$HOME` を使わず絶対パスで書く。**クラウドセッションは `settings.local.json` を読まない**ので、環境側の環境変数に設定する
- ゲートを一時的に外す必要があるとき（緊急時）は `LUMINOUS_STOP_GATE=off` を設定し、**今日の digest に「STOP_GATE=off: 理由」を書く**（書かないと解除されない）
- jq も動く python3 も無いとき（Mac で Xcode コマンドラインツールが未導入だと `/usr/bin/python3` は「有るが動かない」）: hooks は止める側に倒れる。`guard-secrets.sh` はすべての `git commit`・`git push` を止め、`guard-protected.sh` は広く止める。直し方は `xcode-select --install` か jq の導入
- SessionStart で「git フック（pre-commit / pre-push）が効いていません」と出たら、`bash scripts/setup.sh` を実行する（鍵の検査の本命が未設定）
- 再現テスト: `scripts/test-hooks.sh`（使い捨てディレクトリだけに書き込む）

## 6. ファイルの置き場（正本と同期）

- 正本: GitHub `Mark555Limitless/Mark_Limitless` を Mac に clone した `ルミナス/`（作業ブランチ `claude/dreamy-euler-k2f60s`）。ここで `claude` を起動する（デスクトップアプリは Project folder に指定し、worktree は使わない）。初回に `scripts/setup.sh`。clone を移したら `.venv` を作り直す（`rm -rf .venv && bash scripts/setup.sh`）
- 同期: クラウドのセッションも同じブランチで作業する。記録（HANDOVER・digest・escalations.log）は書く前に `git pull`、書いたらすぐ `git push`。この 3 つは `.gitattributes` の merge=union で、両方の書き込みを残して自動でマージする
- ルミナス単独のリポジトリにはしない（親の Mark_Limitless の一部のまま）。git 管理外のもの（`.env`・`data/`・`logs/`・`state/.sessions/`・非公開フォルダ）は pull では届かない
