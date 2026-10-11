# obsidian — Obsidian vault へ同期するノート

- `ルミナス.md`: ハブノート。目的・現在地・リンク集。セッション終了時に「最新」節を更新する
- 同期: `scripts/sync-obsidian.sh` が、`obsidian/*.md`・`digest/*.md`・`CHARTER.md`・`ROUTINE.md` を
  `$LUMINOUS_OBSIDIAN_DIR/ルミナス/` に複製する（SessionEnd hook から呼ばれる。変数が無ければ何もしない）
- vault の場所は `.claude/settings.local.json`（git 管理外）の `env.LUMINOUS_OBSIDIAN_DIR` に書く

## LUMINOUS_OBSIDIAN_DIR の書き方（Mac）
- 値は vault の根（直下に `.obsidian/` があるフォルダ）の**絶対パス**で、`/Users/<名前>/…` の形で書く。`~` や `$HOME` は展開されず、
  `sync-obsidian.sh` が「絶対パスにしてください」で止まる（exit 1）
- 空白を含むパスも JSON の文字列としてそのまま書いてよい。iCloud の vault の例:
  `"LUMINOUS_OBSIDIAN_DIR": "/Users/<名前>/Library/Mobile Documents/iCloud~md~obsidian/Documents/<vault 名>"`
  （途中の `iCloud~md~obsidian` の `~` はフォルダ名の一部なので、そのままでよい。不可なのは先頭の `~/` だけ）
- vault は **Obsidian で一度開いておく**（開くと直下に `.obsidian/` ができる）。無いと「Obsidian の vault と確認できません」で止まる。
  `LUMINOUS_OBSIDIAN_FORCE=1` で外せるが、確信があるときに一時的に使うだけにする
- 複製先は vault の中の `ルミナス/`（無ければ作る）。vault 側で編集されたファイルは `<名前>.vault-edit-<時刻>.md` に退避してから上書きする

## 届いているかの確かめ方
1. **デスクトップアプリに値が届いているか**: アプリのセッションの Bash で `echo "${LUMINOUS_OBSIDIAN_DIR:-unset}"` を実行する。
   `unset` なら届いていない（`settings.local.json` を直したら、セッションを開き直す）。デスクトップアプリは `.zshrc` の `export` を引き継がないことがある
2. **手で同期してみる**（ドライランは無く、本当に複製する）: 端末で、clone の `ルミナス/` に入って
   `LUMINOUS_OBSIDIAN_DIR="<vault の絶対パス>" bash scripts/sync-obsidian.sh; echo "rc=$?"`
   を実行し、最後に `sync-obsidian: <時刻> → <vault>/ルミナス（N 件）` と `rc=0` が出れば成功
3. **セッションの終わりの同期**: SessionEnd の結果は `state/.session-end.log` に残る。`tail -n 6 state/.session-end.log` で
   `sync-obsidian: … （N 件）` の行を見る。「未設定のためスキップ」なら 1 の値が届いていない。失敗は次の SessionStart で警告される
- 「`<vault>/ルミナス/digest` を作れません」と出たら、macOS のシステム設定 → プライバシーとセキュリティで、Claude アプリ
  （端末で試したならターミナル）に vault のフォルダ（iCloud の vault なら iCloud Drive）へのアクセスを許可する。
  どの項目（ファイルとフォルダ・フルディスクアクセス）に出るかは macOS の版による
